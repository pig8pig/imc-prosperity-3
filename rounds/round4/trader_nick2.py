from typing import List, Any, Dict
import json
import math
import statistics

import numpy as np

from datamodel import Listing, Observation, Order, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState


# ──────────────────────────────────────────────────────────────────────────
# Logger (binary-search truncation so logs never exceed 3750 chars)
# ──────────────────────────────────────────────────────────────────────────
class Logger:
    def __init__(self) -> None:
        self.logs = ""
        self.max_log_length = 3750

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(self, state: TradingState, orders: dict, conversions: int, trader_data: str) -> None:
        base_length = len(self.to_json([
            self.compress_state(state, ""),
            self.compress_orders(orders),
            conversions, "", "",
        ]))
        max_item_length = (self.max_log_length - base_length) // 3
        print(self.to_json([
            self.compress_state(state, self.truncate(state.traderData, max_item_length)),
            self.compress_orders(orders),
            conversions,
            self.truncate(trader_data, max_item_length),
            self.truncate(self.logs, max_item_length),
        ]))
        self.logs = ""

    def compress_state(self, state, trader_data):
        return [
            state.timestamp, trader_data,
            self.compress_listings(state.listings),
            self.compress_order_depths(state.order_depths),
            self.compress_trades(state.own_trades),
            self.compress_trades(state.market_trades),
            state.position,
            self.compress_observations(state.observations),
        ]

    def compress_listings(self, listings):
        return [[l.symbol, l.product, l.denomination] for l in listings.values()]

    def compress_order_depths(self, order_depths):
        return {sym: [od.buy_orders, od.sell_orders] for sym, od in order_depths.items()}

    def compress_trades(self, trades):
        out = []
        for arr in trades.values():
            for t in arr:
                out.append([t.symbol, t.price, t.quantity, t.buyer, t.seller, t.timestamp])
        return out

    def compress_observations(self, obs):
        co = {}
        for product, o in obs.conversionObservations.items():
            co[product] = [o.bidPrice, o.askPrice, o.transportFees, o.exportTariff,
                           o.importTariff, o.sugarPrice, o.sunlightIndex]
        return [obs.plainValueObservations, co]

    def compress_orders(self, orders):
        out = []
        for arr in orders.values():
            for o in arr:
                out.append([o.symbol, o.price, o.quantity])
        return out

    def to_json(self, value):
        return json.dumps(value, cls=ProsperityEncoder, separators=(",", ":"))

    def truncate(self, value, max_length):
        if not value:
            return value
        lo, hi = 0, min(len(value), max_length)
        out = ""
        while lo <= hi:
            mid = (lo + hi) // 2
            candidate = value[:mid]
            if len(candidate) < len(value):
                candidate += "..."
            if len(json.dumps(candidate)) <= max_length:
                out = candidate
                lo = mid + 1
            else:
                hi = mid - 1
        return out


logger = Logger()


# ──────────────────────────────────────────────────────────────────────────
# Trader — minimally-corrected version of trader4_nick.py
#
# WHAT CHANGED VS NICK:
#   • velvetfruit_orders: REMOVED.
#       Compared spot (~5,250) to a BS call price (~30) and always shorted.
#       Net PnL was +1,358 across these 3 days but pure noise: -4,406 / -6,443 / +12,207.
#       Removing eliminates ~10k+ of single-day tail risk.
#   • find_arbitrage_opportunities: REMOVED.
#       Threshold (0.001) fires on rounding noise; order-side direction is inverted
#       (sells at best ask, buys at best bid — neither crosses).  Effectively ~0 PnL.
#   • BS cache: BOUNDED at 20k entries (was unbounded; would leak on long live runs).
#   • Logger.truncate: proper binary search (the original could exceed the 3750 cap
#       when JSON-encoding inflated the payload).
#
# WHAT IS PRESERVED VERBATIM:
#   • HYDROGEL_PACK: Bollinger threshold takes + microprice MM with inventory skew.
#   • VOUCHER MM (vev_voucher_orders): 1-tick spread (int(theo) / int(theo)+1) at
#       FULL position-headroom size, across ALL 10 strikes (4000–6500).
#       This is what made Nick's voucher PnL ~21k–42k/day; do not retune.
#   • Rolling 30-tick mean of implied vol per strike for theo input.
# ──────────────────────────────────────────────────────────────────────────
class Trader:
    # ── Hydrogel constants
    HYDROGEL_BOLL_WINDOW = 10000
    HYDROGEL_Z_THRESHOLD = 1.5
    HYDROGEL_MM_SPREAD = 5
    HYDROGEL_INVENTORY_SKEW = 0.05
    HYDROGEL_BOLL_WARMUP = 100

    # ── Voucher constants (Nick's parameters, do not retune lightly)
    VOUCHER_VOL_WINDOW = 30
    VOUCHER_MEAN_VOL = 0.18
    VOUCHER_RISK_FREE = 0.0
    VOUCHER_DAYS_TO_EXPIRY = 3

    # All 10 strikes are traded — VEV_4000/4500 (deep ITM) account for the
    # majority of voucher PnL in backtest; VEV_6000/6500 are tiny but positive.
    ALL_VOUCHERS = {
        "VEV_4000": 4000,
        "VEV_4500": 4500,
        "VEV_5000": 5000,
        "VEV_5100": 5100,
        "VEV_5200": 5200,
        "VEV_5300": 5300,
        "VEV_5400": 5400,
        "VEV_5500": 5500,
        "VEV_6000": 6000,
        "VEV_6500": 6500,
    }

    POSITION_LIMITS = {
        "HYDROGEL_PACK":       200,
        "VELVETFRUIT_EXTRACT": 200,
        "VEV_4000": 300, "VEV_4500": 300, "VEV_5000": 300,
        "VEV_5100": 300, "VEV_5200": 300, "VEV_5300": 300,
        "VEV_5400": 300, "VEV_5500": 300, "VEV_6000": 300,
        "VEV_6500": 300,
    }

    BS_CACHE_LIMIT = 20000  # bounded — flushes when exceeded

    def __init__(self):
        self.past_volatilities: Dict[str, List[float]] = {}
        self.current_day = 0
        self.cache: Dict[str, float] = {}

        # Per-tick state (reset every run() call)
        self.orders: Dict[str, List[Order]] = {}
        self.hydrogel_buy_volume = 0
        self.hydrogel_sell_volume = 0

    # ──────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────
    def calculate_fair_value(self, order_depth: OrderDepth):
        if not order_depth.buy_orders or not order_depth.sell_orders:
            return None
        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        return (best_bid + best_ask) / 2

    def _cache_check(self):
        # Simple bound: clear when over limit. Acceptable since cache rebuild
        # is fast (one BS evaluation per (S, K, T, sigma) tuple).
        if len(self.cache) > self.BS_CACHE_LIMIT:
            self.cache.clear()

    # ──────────────────────────────────────────────────────────────────
    # Black-Scholes block
    # ──────────────────────────────────────────────────────────────────
    def norm_cdf(self, x: float) -> float:
        # Abramowitz–Stegun 7.1.26
        a1, a2, a3 = 0.254829592, -0.284496736, 1.421413741
        a4, a5, p = -1.453152027, 1.061405429, 0.3275911
        sign = -1 if x < 0 else 1
        x = abs(x) / math.sqrt(2.0)
        t = 1.0 / (1.0 + p * x)
        y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * math.exp(-x * x)
        return 0.5 * (1.0 + sign * y)

    def norm_pdf(self, x: float) -> float:
        return (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-0.5 * x * x)

    def black_scholes_call(self, S, K, T, r, sigma):
        if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
            return max(S - K, 0.0)
        cache_key = f"bs_{S}_{K}_{T}_{r}_{sigma}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        d1 = (math.log(S / K) + (r + sigma ** 2 / 2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        result = S * self.norm_cdf(d1) - K * math.exp(-r * T) * self.norm_cdf(d2)
        self.cache[cache_key] = result
        return result

    def black_scholes_vega(self, S, K, T, r, sigma):
        if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
            return 0.0
        d1 = (math.log(S / K) + (r + sigma ** 2 / 2) * T) / (sigma * math.sqrt(T))
        return S * math.sqrt(T) * self.norm_pdf(d1)

    def implied_volatility(self, option_price, S, K, T, r):
        if option_price <= 0 or S <= 0 or K <= 0 or T <= 0:
            return self.VOUCHER_MEAN_VOL
        sigma = 0.5
        for _ in range(50):
            price = self.black_scholes_call(S, K, T, r, sigma)
            vega  = self.black_scholes_vega(S, K, T, r, sigma)
            if vega == 0:
                # Deep-ITM/OTM — solver bails, theo will be ≈ intrinsic.
                # This is fine: aggressive crosses against the resting book
                # still get filled at market prices via price improvement.
                return self.VOUCHER_MEAN_VOL
            diff = option_price - price
            if abs(diff) < 1e-5:
                break
            sigma = sigma + diff / vega
            sigma = max(0.01, min(sigma, 2.0))
        return sigma

    def get_time_to_expiry(self, timestamp: int) -> float:
        # Round 4 spans 3 in-game days (1, 2, 3 in CSV `day` column).
        # Backtester runs each day separately so timestamp resets to 0 each
        # day → current_day = 0 throughout a single-day backtest.
        # TTE is therefore effectively constant; this is fine because IV is
        # calibrated against the same TTE.
        current_day = timestamp // 1_000_000
        days_remaining = max(0, self.VOUCHER_DAYS_TO_EXPIRY - current_day)
        return days_remaining / 365.0

    # ──────────────────────────────────────────────────────────────────
    # HYDROGEL_PACK — Bollinger passive opportunism + microprice MM
    # ──────────────────────────────────────────────────────────────────
    def trade_hydrogel(self, state: TradingState, td: dict) -> None:
        order_depth = state.order_depths.get("HYDROGEL_PACK")
        if order_depth is None or not order_depth.buy_orders or not order_depth.sell_orders:
            return

        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        mid = (best_bid + best_ask) / 2

        prices = td.get("hg_prices", [])
        prices.append(mid)
        if len(prices) > self.HYDROGEL_BOLL_WINDOW:
            prices = prices[-self.HYDROGEL_BOLL_WINDOW:]
        td["hg_prices"] = prices

        if len(prices) < self.HYDROGEL_BOLL_WARMUP:
            return

        mean = float(np.mean(prices))
        std  = float(np.std(prices))
        if std == 0:
            return

        buy_threshold  = mean - self.HYDROGEL_Z_THRESHOLD * std
        sell_threshold = mean + self.HYDROGEL_Z_THRESHOLD * std

        position = state.position.get("HYDROGEL_PACK", 0)
        limit = self.POSITION_LIMITS["HYDROGEL_PACK"]

        # Take asks already at extreme low prices (passive opportunism — don't cross)
        for ask, vol in sorted(order_depth.sell_orders.items()):
            if ask > buy_threshold:
                break
            capacity = limit - position - self.hydrogel_buy_volume
            if capacity <= 0:
                break
            size = min(capacity, -vol)
            if size > 0:
                self.hydrogel_buy_volume += size
                self.orders.setdefault("HYDROGEL_PACK", []).append(
                    Order("HYDROGEL_PACK", ask, size))

        # Sell bids at extreme high prices
        for bid, vol in sorted(order_depth.buy_orders.items(), reverse=True):
            if bid < sell_threshold:
                break
            capacity = limit + position - self.hydrogel_sell_volume
            if capacity <= 0:
                break
            size = min(capacity, vol)
            if size > 0:
                self.hydrogel_sell_volume += size
                self.orders.setdefault("HYDROGEL_PACK", []).append(
                    Order("HYDROGEL_PACK", bid, -size))

    def make_hydrogel_market(self, state: TradingState) -> None:
        order_depth = state.order_depths.get("HYDROGEL_PACK")
        if order_depth is None or not order_depth.buy_orders or not order_depth.sell_orders:
            return

        position = state.position.get("HYDROGEL_PACK", 0)
        limit = self.POSITION_LIMITS["HYDROGEL_PACK"]

        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        bid_vol  = order_depth.buy_orders[best_bid]
        ask_vol  = -order_depth.sell_orders[best_ask]

        microprice = (best_bid * ask_vol + best_ask * bid_vol) / (bid_vol + ask_vol)

        skew = round(position * self.HYDROGEL_INVENTORY_SKEW)
        our_bid = round(microprice) - self.HYDROGEL_MM_SPREAD - skew
        our_ask = round(microprice) + self.HYDROGEL_MM_SPREAD - skew
        if our_bid >= our_ask:
            our_bid = round(microprice) - 1 - skew
            our_ask = round(microprice) + 1 - skew

        max_buy  = max(0, limit - position - self.hydrogel_buy_volume)
        max_sell = max(0, limit + position - self.hydrogel_sell_volume)

        if max_buy > 0:
            self.hydrogel_buy_volume += max_buy
            self.orders.setdefault("HYDROGEL_PACK", []).append(
                Order("HYDROGEL_PACK", our_bid, max_buy))
        if max_sell > 0:
            self.hydrogel_sell_volume += max_sell
            self.orders.setdefault("HYDROGEL_PACK", []).append(
                Order("HYDROGEL_PACK", our_ask, -max_sell))

    # ──────────────────────────────────────────────────────────────────
    # Voucher MM — RESTORED from Nick's verbatim logic.
    # 1-tick spread at int(theo) / int(theo)+1, sized at full position
    # headroom. The MM works because BS theo (with smoothed-vol IV) often
    # lies just inside the market quote: the order at int(theo) crosses the
    # opposite side of the book, and Prosperity's matching engine fills the
    # crossing aggressor at the resting limit price (price improvement).
    # Result: aggressive fills at top-of-book prices on whichever side the
    # market mid drifts away from theo — captures MM edge even though the
    # "quote" looks like a 1-tick spread.
    # ──────────────────────────────────────────────────────────────────
    def vev_voucher_orders(self, state, rock_mid, voucher_symbol, voucher_order_depth, voucher_position):
        try:
            voucher_mid = self.calculate_fair_value(voucher_order_depth)
            if voucher_mid is None:
                return []

            tte    = self.get_time_to_expiry(state.timestamp)
            strike = self.ALL_VOUCHERS[voucher_symbol]
            if tte <= 0:
                return []

            # IV from voucher mid + rolling smoothing
            current_iv = self.implied_volatility(
                voucher_mid, rock_mid, strike, tte, self.VOUCHER_RISK_FREE
            )
            self.past_volatilities.setdefault(voucher_symbol, []).append(current_iv)
            if len(self.past_volatilities[voucher_symbol]) > self.VOUCHER_VOL_WINDOW:
                self.past_volatilities[voucher_symbol].pop(0)
            volatility = statistics.mean(self.past_volatilities[voucher_symbol])

            theo = self.black_scholes_call(
                rock_mid, strike, tte, self.VOUCHER_RISK_FREE, volatility
            )

            limit  = self.POSITION_LIMITS[voucher_symbol]
            orders = []

            # Buy at int(theo), full long-side headroom
            if voucher_position < limit:
                buy_price = int(theo)
                buy_size  = limit - voucher_position
                if buy_size > 0:
                    orders.append(Order(voucher_symbol, buy_price, buy_size))

            # Sell at int(theo)+1, full short-side headroom (negative qty)
            if voucher_position > -limit:
                sell_price = int(theo + 1)
                sell_qty   = -limit - voucher_position  # negative number
                if sell_qty < 0:
                    orders.append(Order(voucher_symbol, sell_price, sell_qty))

            return orders
        except Exception as e:
            logger.print(f"Error in vev_voucher_orders[{voucher_symbol}]: {e}")
            return []

    # ──────────────────────────────────────────────────────────────────
    # Main dispatcher
    # ──────────────────────────────────────────────────────────────────
    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}
        conversions = 0
        trader_data: Dict[str, Any] = {}

        # Decode persistent state
        if state.traderData and state.traderData != "SAMPLE":
            try:
                trader_data = json.loads(state.traderData)
                if "past_volatilities" in trader_data:
                    self.past_volatilities = trader_data["past_volatilities"]
                if "current_day" in trader_data:
                    self.current_day = trader_data["current_day"]
            except Exception as e:
                logger.print(f"Could not parse trader data: {e}")
                trader_data = {}

        # Day rollover (no-op in single-day backtests)
        current_day = state.timestamp // 1_000_000
        if current_day != self.current_day:
            self.current_day = current_day

        # Reset per-tick state
        self.orders = {}
        self.hydrogel_buy_volume = 0
        self.hydrogel_sell_volume = 0

        # Bound BS cache so live runs don't accumulate state
        self._cache_check()

        # ── HYDROGEL_PACK ───────────────────────────────────────────────
        try:
            self.trade_hydrogel(state, trader_data)
            self.make_hydrogel_market(state)
        except Exception as e:
            logger.print(f"Error in HYDROGEL strategies: {e}")

        # ── Vouchers (all 10 strikes, MM around BS theo) ────────────────
        if "VELVETFRUIT_EXTRACT" in state.order_depths:
            ve_od = state.order_depths["VELVETFRUIT_EXTRACT"]
            ve_mid = self.calculate_fair_value(ve_od)
            if ve_mid is not None:
                for vsym in self.ALL_VOUCHERS:
                    if vsym not in state.order_depths:
                        continue
                    vpos = state.position.get(vsym, 0)
                    try:
                        vorders = self.vev_voucher_orders(
                            state, ve_mid, vsym, state.order_depths[vsym], vpos
                        )
                        if vorders:
                            self.orders.setdefault(vsym, []).extend(vorders)
                    except Exception as e:
                        logger.print(f"Error in voucher {vsym}: {e}")

        # NOTE: VELVETFRUIT_EXTRACT directional trade was REMOVED.
        #   The original logic compared spot (~5,250) to a BS call price
        #   (~30) and always shorted. Net was +1,358 over 3 days but
        #   purely path-dependent on VE moving down. Removing trades a
        #   small expected return for substantially less tail variance.
        # NOTE: find_arbitrage_opportunities was REMOVED.
        #   Threshold 0.001 fired on rounding noise; orders were placed at
        #   inverted price levels (sell at best-ask, buy at best-bid) so
        #   they didn't cross. Effectively dead code.

        # Persist state
        trader_data["past_volatilities"] = self.past_volatilities
        trader_data["current_day"] = self.current_day
        try:
            final_trader_data = json.dumps(trader_data)
        except Exception:
            final_trader_data = ""

        result = {p: o for p, o in self.orders.items() if o}

        logger.flush(state, result, conversions, final_trader_data)
        return result, conversions, final_trader_data