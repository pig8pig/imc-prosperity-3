"""Phase 5 — Smile-deviation OptionTrader for VE vouchers.

Self-contained module. Will be inlined into trader_r3.py before submission.
"""

import math
import json
import numpy as np

from datamodel import Order
from trader_r3 import (
    ProductTrader,
    VELVET_SYMBOL,
    VOUCHER_SYMBOLS,
    ACTIVE_STRIKES,
)
from bs_pricer import bs_delta, implied_vol


# ─── Tunables (top-level so the inliner can find them) ──────────────────────
N_OPEN = 2.0
N_CLOSE = 1.0
PER_TRADE_CAP = 30
WARMUP_TICKS = 200
DELTA_CAP = 150.0
EMA_MEAN_WINDOW = 500
EMA_VAR_WINDOW = 1000
USE_LOO = True  # leave-one-out smile fit (avoids self-regression bias)

# Spec wrote `voucher.ask(best_bid, size)` (cross the spread). On these
# vouchers half-spread (3, 2, 1.5, 1, 0.5, 0.5) >> per-trade signal edge
# (~0.1/unit), so taking always loses. We post passive instead: floor(mid)
# for sells, ceil(mid) for buys. Skip if no room (spread ≤ 1).
PASSIVE_EXEC = True

# ─── TTE schedule ───────────────────────────────────────────────────────────
START_TTE_DAYS = 5     # Round 3 starts here per Phase 5 spec
TICKS_PER_DAY = 10_000
TIMESTAMP_STEP = 100   # market timestamp increments by 100 per tick


def tte_years(timestamp):
    """TTE in years given the (cumulative) timestamp.

    tick = timestamp / 100; one full day = 10,000 ticks; year = 365 days.
    """
    tick = timestamp / TIMESTAMP_STEP
    return (START_TTE_DAYS * TICKS_PER_DAY - tick) / (TICKS_PER_DAY * 365)


class OptionTrader:
    """Trades the 6 active VE vouchers off deviations from the live IV smile."""

    def __init__(self, state, prints, new_trader_data):
        self.state = state
        self.prints = prints
        self.new_trader_data = new_trader_data

        last = {}
        try:
            if state.traderData:
                last = json.loads(state.traderData)
        except Exception:
            last = {}
        self.last_traderData = last

        self.tte = tte_years(state.timestamp)

    def _log(self, kind, payload, group="SMILE"):
        bucket = self.prints.get(group, {})
        bucket[kind] = payload
        self.prints[group] = bucket

    # ───────────────────────── public API ──────────────────────────────────
    def get_orders(self):
        result = {sym: [] for sym in VOUCHER_SYMBOLS}

        if self.tte <= 0:
            return result

        # Underlying spot from VE wall_mid
        try:
            ve = ProductTrader(VELVET_SYMBOL, self.state, self.prints,
                               self.new_trader_data, product_group='SMILE')
        except Exception as e:
            self._log("ERR_VE", str(e))
            return result
        S = ve.wall_mid
        if S is None or S <= 0:
            self._log("SKIP", "no_underlying_mid")
            return result

        # ── Per-voucher snapshot: IV, moneyness, half-spread ────────────────
        snaps = []
        for sym, K in zip(VOUCHER_SYMBOLS, ACTIVE_STRIKES):
            try:
                pt = ProductTrader(sym, self.state, self.prints,
                                   self.new_trader_data, product_group='SMILE')
                if pt.best_bid is None or pt.best_ask is None:
                    continue
                if pt.wall_mid is None:
                    continue
                iv = implied_vol(float(pt.wall_mid), float(S),
                                 float(K), float(self.tte))
                if math.isnan(iv):
                    continue
                m = math.log(K / S) / math.sqrt(self.tte)
                hs = max(0.5, (pt.best_ask - pt.best_bid) / 2.0)
                snaps.append({
                    "sym": sym, "K": K, "pt": pt,
                    "mid": pt.wall_mid, "iv": iv, "m": m, "hs": hs,
                })
            except Exception as e:
                self._log(f"ERR_{sym}", str(e))

        if len(snaps) < 4:
            self._log("SKIP", f"too_few_iv_n{len(snaps)}")
            return result

        # ── Quadratic smile fit weighted by 1/half-spread ───────────────────
        # USE_LOO=True: per-voucher leave-one-out fit so the residual is a
        # genuine out-of-sample deviation, not constrained by self-regression.
        ms = np.array([s["m"] for s in snaps], dtype=float)
        ivs = np.array([s["iv"] for s in snaps], dtype=float)
        ws = np.array([1.0 / s["hs"] for s in snaps], dtype=float)
        try:
            coeffs_full = np.polyfit(ms, ivs, 2, w=ws)
        except Exception as e:
            self._log("FIT_FAIL", str(e))
            return result
        self._log("FIT", {"a": round(float(coeffs_full[0]), 5),
                          "b": round(float(coeffs_full[1]), 5),
                          "c": round(float(coeffs_full[2]), 5),
                          "S": round(S, 2), "tte": round(self.tte, 6)})

        candidates = []

        # ── Per-voucher EMA update + signal ─────────────────────────────────
        alpha_m = 2.0 / (EMA_MEAN_WINDOW + 1)
        alpha_v = 2.0 / (EMA_VAR_WINDOW + 1)

        for j, s in enumerate(snaps):
            sym = s["sym"]
            if USE_LOO and len(snaps) >= 5:
                mask = np.ones(len(snaps), dtype=bool)
                mask[j] = False
                cf = np.polyfit(ms[mask], ivs[mask], 2, w=ws[mask])
            else:
                cf = coeffs_full
            a_j, b_j, c_j = float(cf[0]), float(cf[1]), float(cf[2])
            iv_fit = a_j * s["m"] ** 2 + b_j * s["m"] + c_j
            deviation = s["iv"] - iv_fit

            key = f"SMILE_{sym}"
            prev = self.last_traderData.get(
                key, {"ema_dev": 0.0, "ema_var": 0.0, "n": 0}
            )
            ema_dev = float(prev.get("ema_dev", 0.0))
            ema_var = float(prev.get("ema_var", 0.0))
            n_prev = int(prev.get("n", 0))

            diff = deviation - ema_dev
            ema_dev_new = ema_dev + alpha_m * diff
            ema_var_new = (1.0 - alpha_v) * (ema_var + alpha_v * diff * diff)
            stddev = math.sqrt(max(ema_var_new, 0.0))
            n_new = n_prev + 1

            # Persist immediately so failures downstream don't drop state
            self.new_trader_data[key] = {
                "ema_dev": ema_dev_new,
                "ema_var": ema_var_new,
                "n": n_new,
            }

            z = (deviation - ema_dev_new) / max(stddev, 0.001)
            if z > 10.0:
                z = 10.0
            elif z < -10.0:
                z = -10.0

            delta = bs_delta(S, s["K"], self.tte, max(iv_fit, 1e-3))
            pos = self.state.position.get(sym, 0)

            self._log(sym, {
                "iv": round(s["iv"], 5),
                "fit": round(iv_fit, 5),
                "dev": round(deviation, 5),
                "ema": round(ema_dev_new, 5),
                "sd": round(stddev, 5),
                "z": round(z, 3),
                "p": pos, "n": n_new,
            })

            if n_new <= WARMUP_TICKS:
                continue

            pt = s["pt"]
            spread = pt.best_ask - pt.best_bid
            if PASSIVE_EXEC:
                # Join top-of-book: sell at best_ask (above market) and buy
                # at best_bid (below market). Fills only on aggressors crossing
                # our quote — pays no spread cost when filled. For wide-spread
                # vouchers we step one tick inside top-of-book to improve
                # queue priority while still not crossing.
                if spread > 1:
                    sell_px = pt.best_ask - 1
                    buy_px = pt.best_bid + 1
                else:
                    sell_px = pt.best_ask
                    buy_px = pt.best_bid
            else:
                # Spec's taking execution (cross spread). Mathematically
                # unprofitable on these vouchers (round-trip cost >> edge).
                sell_px = pt.best_bid
                buy_px = pt.best_ask

            # Available size: position limit headroom only — passive orders
            # don't consume book volume, so book volume isn't a binding cap.
            if z > N_OPEN and sell_px is not None:
                size = min(PER_TRADE_CAP, pt.max_allowed_sell_volume)
                if size >= 1:
                    candidates.append({
                        "sym": sym, "side": "ask", "price": sell_px,
                        "size": int(size), "abs_z": abs(z),
                        "delta": delta, "pt": pt, "is_close": False,
                    })
            elif z < -N_OPEN and buy_px is not None:
                size = min(PER_TRADE_CAP, pt.max_allowed_buy_volume)
                if size >= 1:
                    candidates.append({
                        "sym": sym, "side": "bid", "price": buy_px,
                        "size": int(size), "abs_z": abs(z),
                        "delta": delta, "pt": pt, "is_close": False,
                    })
            elif abs(z) < N_CLOSE and pos != 0:
                if pos > 0 and sell_px is not None:
                    size = min(pos, pt.max_allowed_sell_volume)
                    if size >= 1:
                        candidates.append({
                            "sym": sym, "side": "ask", "price": sell_px,
                            "size": int(size), "abs_z": abs(z),
                            "delta": delta, "pt": pt, "is_close": True,
                        })
                elif pos < 0 and buy_px is not None:
                    size = min(-pos, pt.max_allowed_buy_volume)
                    if size >= 1:
                        candidates.append({
                            "sym": sym, "side": "bid", "price": buy_px,
                            "size": int(size), "abs_z": abs(z),
                            "delta": delta, "pt": pt, "is_close": True,
                        })

        # ── Existing-position delta (for the cap baseline) ───────────────────
        # Use the full-fit coeffs for existing-delta baseline; LOO would be
        # over-engineered here since this is just a hedge sanity sum.
        a_f, b_f, c_f = (float(coeffs_full[0]), float(coeffs_full[1]),
                          float(coeffs_full[2]))
        existing_delta = 0.0
        for s in snaps:
            iv_fit_s = a_f * s["m"] ** 2 + b_f * s["m"] + c_f
            d_s = bs_delta(S, s["K"], self.tte, max(iv_fit_s, 1e-3))
            existing_delta += self.state.position.get(s["sym"], 0) * d_s
        net_delta = existing_delta

        # Closes prioritised, then highest |z| open trades
        candidates.sort(key=lambda c: (not c["is_close"], -c["abs_z"]))

        for c in candidates:
            signed_size = c["size"] if c["side"] == "bid" else -c["size"]
            d_after = net_delta + signed_size * c["delta"]
            if abs(d_after) > DELTA_CAP:
                self._log(f"SKIP_DELTA_{c['sym']}",
                          {"would": round(d_after, 1),
                           "side": c["side"], "size": c["size"]})
                continue
            net_delta = d_after
            pt = c["pt"]
            if c["side"] == "bid":
                pt.bid(c["price"], c["size"])
            else:
                pt.ask(c["price"], c["size"])
            result[c["sym"]] = list(pt.orders)
            self._log(f"EXEC_{c['sym']}", {
                "side": c["side"], "p": c["price"], "v": c["size"],
                "z": round(c["abs_z"], 2), "close": c["is_close"],
            })

        self._log("NETD", round(net_delta, 1))
        return result
