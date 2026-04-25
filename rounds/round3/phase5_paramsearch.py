"""Phase 5 — fast parameter search.

Step 1: pre-compute per-voucher LOO smile residuals (deviations) for every
tick. This is the expensive part (~30k ticks × 6 strikes × polyfit-of-5).
Step 2: sweep over EMA / threshold / size combos cheaply by replaying the
tape against pre-computed deviations.
"""

import os
import sys
import math
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bs_pricer import implied_vol

DATA_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "round3"
)
ACTIVE_STRIKES = [5000, 5100, 5200, 5300, 5400, 5500]
ACTIVE_PRODUCTS = [f"VEV_{k}" for k in ACTIVE_STRIKES]
START_TTE_DAYS = 5
TICKS_PER_DAY = 10_000
TIMESTAMP_STEP = 100


def tte_years(global_t):
    tick = global_t / TIMESTAMP_STEP
    return (START_TTE_DAYS * TICKS_PER_DAY - tick) / (TICKS_PER_DAY * 365)


def load_books():
    frames = []
    for d in (0, 1, 2):
        df = pd.read_csv(os.path.join(DATA_DIR, f"prices_round_3_day_{d}.csv"),
                         sep=";")
        df = df[df["product"].isin(ACTIVE_PRODUCTS + ["VELVETFRUIT_EXTRACT"])]
        df["day"] = d
        df["global_t"] = df["day"] * 1_000_000 + df["timestamp"]
        frames.append(df)
    full = pd.concat(frames, ignore_index=True)
    pieces = {}
    for col in ("bid_price_1", "ask_price_1", "mid_price"):
        pieces[col] = full.pivot_table(
            index="global_t", columns="product", values=col, aggfunc="first",
        ).sort_index()
    return pieces


def precompute_deviations(books):
    """Return arrays of (T x K) shape: dev_loo, bid, ask, mid, tte."""
    mids = books["mid_price"]
    bids = books["bid_price_1"]
    asks = books["ask_price_1"]
    t_index = mids.index.values
    n_t = len(t_index)
    n_k = len(ACTIVE_STRIKES)

    dev = np.full((n_t, n_k), np.nan)
    bid = np.full((n_t, n_k), np.nan)
    ask = np.full((n_t, n_k), np.nan)
    ttes = np.array([tte_years(t) for t in t_index])

    for j, sym in enumerate(ACTIVE_PRODUCTS):
        if sym in bids.columns:
            bid[:, j] = bids[sym].values
        if sym in asks.columns:
            ask[:, j] = asks[sym].values

    for i in range(n_t):
        T = ttes[i]
        if T <= 0:
            continue
        S = mids["VELVETFRUIT_EXTRACT"].values[i]
        if not np.isfinite(S):
            continue
        ms = np.full(n_k, np.nan)
        ivs = np.full(n_k, np.nan)
        for j, K in enumerate(ACTIVE_STRIKES):
            mid_v = mids[ACTIVE_PRODUCTS[j]].values[i]
            if not np.isfinite(mid_v):
                continue
            iv = implied_vol(float(mid_v), float(S), float(K), float(T))
            if math.isnan(iv):
                continue
            ms[j] = math.log(K / S) / math.sqrt(T)
            ivs[j] = iv
        valid = np.isfinite(ivs)
        if valid.sum() < 5:
            continue
        for j in range(n_k):
            if not valid[j]:
                continue
            mask = valid.copy(); mask[j] = False
            cf = np.polyfit(ms[mask], ivs[mask], 2)
            iv_fit = cf[0] * ms[j] ** 2 + cf[1] * ms[j] + cf[2]
            dev[i, j] = ivs[j] - iv_fit

    return {"dev": dev, "bid": bid, "ask": ask, "tte": ttes,
            "t_index": t_index}


def simulate(precomp, params, exec_mode="cross"):
    """Replay strategy with cached deviations.

    exec_mode:
      'cross' — sell at bid, buy at ask (live default; full spread cost)
      'mid'   — sell at mid, buy at mid (theoretical upper bound)
      'join'  — sell at ask, buy at bid (passive; assumes 100% fill)
    """
    dev = precomp["dev"]
    bid = precomp["bid"]
    ask = precomp["ask"]
    mid = (bid + ask) / 2.0
    n_t, n_k = dev.shape

    alpha_m = 2.0 / (params["EMA_M"] + 1)
    alpha_v = 2.0 / (params["EMA_V"] + 1)

    ema_dev = np.zeros(n_k)
    ema_var = np.zeros(n_k)
    n_samples = np.zeros(n_k, dtype=int)
    pos = np.zeros(n_k, dtype=int)
    entry_price = np.full(n_k, np.nan)

    pnl_total = 0.0
    trades = 0
    wins = 0
    by_sym = {sym: 0.0 for sym in ACTIVE_PRODUCTS}

    for i in range(n_t):
        for j in range(n_k):
            d = dev[i, j]
            if not np.isfinite(d):
                continue
            diff = d - ema_dev[j]
            ema_dev[j] += alpha_m * diff
            ema_var[j] = (1 - alpha_v) * (ema_var[j] + alpha_v * diff * diff)
            sd = math.sqrt(max(ema_var[j], 0.0))
            n_samples[j] += 1
            if n_samples[j] <= params["WARMUP"]:
                continue
            z = (d - ema_dev[j]) / max(sd, 0.001)
            if z > 10: z = 10
            elif z < -10: z = -10

            b, a, m = bid[i, j], ask[i, j], mid[i, j]
            if not (np.isfinite(b) and np.isfinite(a)):
                continue
            if exec_mode == "cross":
                sell_px, buy_px = b, a
            elif exec_mode == "mid":
                sell_px = buy_px = m
            else:  # join
                sell_px, buy_px = a, b

            if pos[j] == 0:
                if z > params["N_OPEN"]:
                    pos[j] = -params["SIZE"]; entry_price[j] = sell_px
                elif z < -params["N_OPEN"]:
                    pos[j] = +params["SIZE"]; entry_price[j] = buy_px
            elif abs(z) < params["N_CLOSE"]:
                if pos[j] > 0:
                    pnl = pos[j] * (sell_px - entry_price[j])
                else:
                    pnl = pos[j] * (buy_px - entry_price[j])
                pnl_total += pnl; trades += 1
                if pnl > 0: wins += 1
                by_sym[ACTIVE_PRODUCTS[j]] += pnl
                pos[j] = 0; entry_price[j] = np.nan

    # Final mark-to-mid close
    last_bid = np.array([bid[~np.isnan(bid[:, j]), j][-1]
                         if (~np.isnan(bid[:, j])).any() else np.nan
                         for j in range(n_k)])
    last_ask = np.array([ask[~np.isnan(ask[:, j]), j][-1]
                         if (~np.isnan(ask[:, j])).any() else np.nan
                         for j in range(n_k)])
    for j in range(n_k):
        if pos[j] == 0:
            continue
        if pos[j] > 0:
            pnl = pos[j] * (last_bid[j] - entry_price[j])
        else:
            pnl = pos[j] * (last_ask[j] - entry_price[j])
        if np.isfinite(pnl):
            pnl_total += pnl
            by_sym[ACTIVE_PRODUCTS[j]] += pnl

    return {"pnl": pnl_total, "trades": trades,
            "win_rate": wins / max(1, trades),
            "by_sym": by_sym}


def main():
    print("loading books..."); sys.stdout.flush()
    books = load_books()
    print(f"  ticks: {len(books['mid_price']):,}"); sys.stdout.flush()

    print("precomputing LOO deviations..."); sys.stdout.flush()
    precomp = precompute_deviations(books)
    n_dev = np.isfinite(precomp["dev"]).sum()
    print(f"  deviations computed: {n_dev:,}"); sys.stdout.flush()

    grid = []
    for ema in [(500, 1000), (1000, 2000)]:
        for n_open in (2.0, 2.5, 3.0):
            for n_close in (0.5, 1.0):
                for size in (10, 30):
                    grid.append({
                        "EMA_M": ema[0], "EMA_V": ema[1], "WARMUP": 200,
                        "N_OPEN": n_open, "N_CLOSE": n_close, "SIZE": size,
                    })

    print(f"\nsweeping {len(grid)} configs × 3 exec modes...")
    print(f"{'mode':<6} {'EMA_M':>6} {'EMA_V':>6} {'OPEN':>5} {'CLOSE':>6} "
          f"{'SIZE':>5} {'PnL':>10} {'trades':>7} {'win%':>6}")
    sys.stdout.flush()
    rows = []
    for mode in ("cross", "join", "mid"):
        for p in grid:
            r = simulate(precomp, p, exec_mode=mode)
            rows.append((mode, p, r))
            print(f"{mode:<6} {p['EMA_M']:>6} {p['EMA_V']:>6} "
                  f"{p['N_OPEN']:>5.1f} {p['N_CLOSE']:>6.2f} {p['SIZE']:>5d} "
                  f"{r['pnl']:>10.0f} {r['trades']:>7d} "
                  f"{r['win_rate']*100:>5.1f}%")
            sys.stdout.flush()

    rows.sort(key=lambda x: -x[2]["pnl"])
    print("\nTop 5:")
    for mode, p, r in rows[:5]:
        print(f"  [{mode}] {p} -> PnL={r['pnl']:.0f} trades={r['trades']} "
              f"win={r['win_rate']*100:.1f}%")
        for s, v in r["by_sym"].items():
            print(f"     {s}: {v:.0f}")


if __name__ == "__main__":
    main()
