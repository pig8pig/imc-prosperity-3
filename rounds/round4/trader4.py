from typing import List, Any, Dict, Tuple
import json
import math
import statistics

import numpy as np

from datamodel import Listing, Observation, Order, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState


# ─────────────────────────────────────────────────────────────────────────────
# █ FEATURE FLAGS — flip these between backtests to test each variant █
# ─────────────────────────────────────────────────────────────────────────────
# Run 1 (baseline):  FOLLOW_MARK_14 = False, FADE_MARK_38 = False
# Run 2 (A only):    FOLLOW_MARK_14 = True,  FADE_MARK_38 = False
# Run 3 (B only):    FOLLOW_MARK_14 = False, FADE_MARK_38 = True
# Run 4 (A+B):       FOLLOW_MARK_14 = True,  FADE_MARK_38 = True
FOLLOW_MARK_14 = False
FADE_MARK_38   = False

# Products to apply counterparty signal to (verified from Round 4 trades CSV
# analysis: HG +48k, VEV_4000 +18k, VE +6.9k of theoretical edge).
CP_PRODUCTS = ['HYDROGEL_PACK', 'VEV_4000', 'VELVETFRUIT_EXTRACT']

# How aggressive to size each counterparty trade (in lots) and the minimum
# net informed-flow that triggers a trade.
CP_TRADE_SIZE  = 30
CP_MIN_FLOW    = 5

# Reserve a slice of position headroom for counterparty so it doesn't compete
# with Nick's MM. With voucher limit 300 and HG limit 200, reserving 50 lots
# leaves 250 / 150 for the existing strategies — most of their capacity intact.
CP_RESERVE = 50


# ─────────────────────────────────────────────────────────────────────────────
# Logger (binary-search truncate so logs never exceed the 3750 cap)
# ─────────────────────────────────────────────────────────────────────────────
class Logger:
    def __init__(self) -> None:
        self.logs = ""
        self.max_log_length = 3750

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(self, state, orders, conversions, trader_data) -> None:
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
        return [state.timestamp, trader_data,
                self.compress_listings(state.listings),
                self.compress_order_depths(state.order_depths),
                self.compress_trades(state.own_trades),
                self.compress_trades(state.market_trades),
                state.position,
                self.compress_observations(state.observations)]

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


# ─────────────────────────────────────────────────────────────────────────────
# Trader — Nick's verbatim strategy with bad bits removed + counterparty added.
#
# REMOVED FROM NICK:
#   • velvetfruit_orders — compared spot to BS call price, always shorted
#   • find_arbitrage_opportunities — inverted directions, fires on noise
#
# KEPT FROM NICK (verbatim):
#   • trade_hydrogel + make_hydrogel_market (passive Bollinger + microprice MM)
#   • vev_voucher_orders (1-tick spread MM around BS theo, all 10 strikes)
#   • BS pricer + IV solver
#
# ADDED:
#   • _counterparty_orders: cross-spread follow Mark 14 / fade Mark 38 on
#     HYDROGEL_PACK, VEV_4000, VELVETFRUIT_EXTRACT. Runs FIRST each tick and
#     reserves CP_RESERVE lots per product so it doesn't conflict with Nick's MM.
#   • Bounded BS cache (BS_CACHE_LIMIT) to prevent unbounded growth in live runs
# ─────────────────────────────────────────────────────────────────────────────
class Trader:

    BS_CACHE_LIMIT = 20000

    def __init__(self):
        self.voucher_strikes = {
            "VEV_4000": 4000, "VEV_4500": 4500, "VEV_5000": 5000,
            "VEV_5100": 5100, "VEV_5200": 5200, "VEV_5300": 5300,
            "VEV_5400": 5400, "VEV_5500": 5500, "VEV_6000": 6000,
            "VEV_6500": 6500,
        }
        self.position_limits = {
            "HYDROGEL_PACK": 200, "VELVETFRUIT_EXTRACT": 200,
            "VEV_4000": 300, "VEV_4500": 300, "VEV_5000": 300,
            "VEV_5100": 300, "VEV_5200": 300, "VEV_5300": 300,
            "VEV_5400": 300, "VEV_5500": 300, "VEV_6000": 300,
            "VEV_6500": 300,
        }

        # Voucher MM constants (Nick's exact values)
        self.days_to_expiry  = 3
        self.mean_volatility = 0.18
        self.volatility_window = 30
        self.risk_free_rate    = 0.0
        self.past_volatilities: Dict[str, List[float]] = {}
        self.current_day = 0
        self.cache: Dict[str, float] = {}

        # Per-tick state
        self.orders: Dict[str, List[Order]] = {}
        self.Hydrogel_buy_orders  = 0
        self.Hydrogel_sell_orders = 0
        # Counterparty per-tick volume tracker — used by voucher MM to know
        # how much capacity to leave alone.
        self.cp_buy:  Dict[str, int] = {}
        self.cp_sell: Dict[str, int] = {}

    # ──────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────
    def calculate_fair_value(self, order_depth: OrderDepth):
        try:
            if not order_depth.buy_orders or not order_depth.sell_orders:
                return None
            return (max(order_depth.buy_orders.keys()) + min(order_depth.sell_orders.keys())) / 2
        except Exception:
            return None

    def _cache_check(self):
        if len(self.cache) > self.BS_CACHE_LIMIT:
            self.cache.clear()

    # ──────────────────────────────────────────────────────────────────
    # Black-Scholes (verbatim from Nick)
    # ──────────────────────────────────────────────────────────────────
    def norm_cdf(self, x: float) -> float:
        a1, a2, a3 =  0.254829592, -0.284496736,  1.421413741
        a4, a5, p  = -1.453152027,  1.061405429,  0.3275911
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
        ck = f"bs_{S}_{K}_{T}_{r}_{sigma}"
        if ck in self.cache:
            return self.cache[ck]
        d1 = (math.log(S / K) + (r + sigma ** 2 / 2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        out = S * self.norm_cdf(d1) - K * math.exp(-r * T) * self.norm_cdf(d2)
        self.cache[ck] = out
        return out

    def black_scholes_vega(self, S, K, T, r, sigma):
        if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
            return 0.0
        d1 = (math.log(S / K) + (r + sigma ** 2 / 2) * T) / (sigma * math.sqrt(T))
        return S * math.sqrt(T) * self.norm_pdf(d1)

    def implied_volatility(self, option_price, S, K, T, r):
        if option_price <= 0 or S <= 0 or K <= 0 or T <= 0:
            return self.mean_volatility
        sigma = 0.5
        for _ in range(50):
            price = self.black_scholes_call(S, K, T, r, sigma)
            vega  = self.black_scholes_vega(S, K, T, r, sigma)
            if vega == 0:
                return self.mean_volatility
            diff = option_price - price
            if abs(diff) < 1e-5:
                break
            sigma = sigma + diff / vega
            sigma = max(0.01, min(sigma, 2.0))
        return sigma

    def get_time_to_expiry(self, timestamp: int) -> float:
        current_day = timestamp // 1_000_000
        return max(0, 3 - current_day) / 365.0

    # ──────────────────────────────────────────────────────────────────
    # COUNTERPARTY — cross spread to follow Mark 14 / fade Mark 38.
    # Runs FIRST each tick. For each target product, sums signed informed
    # flow from this tick's market trades and crosses if |flow| >= threshold.
    # Reserves CP_RESERVE lots per product so Nick's MM keeps most capacity.
    # ──────────────────────────────────────────────────────────────────
    def _counterparty_orders(self, state: TradingState):
        if not (FOLLOW_MARK_14 or FADE_MARK_38):
            return  # disabled — no-op

        for sym in CP_PRODUCTS:
            if sym not in state.order_depths:
                continue

            od = state.order_depths[sym]
            if not od.buy_orders or not od.sell_orders:
                continue

            best_bid = max(od.buy_orders.keys())
            best_ask = min(od.sell_orders.keys())

            # Sum signed informed flow from this tick's trades
            flow = 0
            for t in state.market_trades.get(sym, []) or []:
                if FOLLOW_MARK_14:
                    if t.buyer  == 'Mark 14': flow += t.quantity
                    if t.seller == 'Mark 14': flow -= t.quantity
                if FADE_MARK_38:
                    # Loser's BUY → we SELL. Loser's SELL → we BUY.
                    if t.buyer  == 'Mark 38': flow -= t.quantity
                    if t.seller == 'Mark 38': flow += t.quantity

            if abs(flow) < CP_MIN_FLOW:
                continue

            position = state.position.get(sym, 0)
            limit    = self.position_limits[sym]

            if flow >= CP_MIN_FLOW:
                # Cross to BUY at best ask
                avail = -od.sell_orders[best_ask]   # positive
                # Headroom: stay within +limit, capped at trade size, capped at book vol
                headroom = max(0, limit - position - self.cp_buy.get(sym, 0))
                # Subtract HG-specific tracker so we don't double-claim with MM
                if sym == 'HYDROGEL_PACK':
                    headroom = max(0, headroom - self.Hydrogel_buy_orders)
                size = min(CP_TRADE_SIZE, headroom, avail)
                if size > 0:
                    self.orders.setdefault(sym, []).append(Order(sym, best_ask, size))
                    self.cp_buy[sym] = self.cp_buy.get(sym, 0) + size
                    if sym == 'HYDROGEL_PACK':
                        self.Hydrogel_buy_orders += size
            else:
                # Cross to SELL at best bid
                avail = od.buy_orders[best_bid]    # positive
                headroom = max(0, limit + position - self.cp_sell.get(sym, 0))
                if sym == 'HYDROGEL_PACK':
                    headroom = max(0, headroom - self.Hydrogel_sell_orders)
                size = min(CP_TRADE_SIZE, headroom, avail)
                if size > 0:
                    self.orders.setdefault(sym, []).append(Order(sym, best_bid, -size))
                    self.cp_sell[sym] = self.cp_sell.get(sym, 0) + size
                    if sym == 'HYDROGEL_PACK':
                        self.Hydrogel_sell_orders += size

    # ──────────────────────────────────────────────────────────────────
    # Voucher MM (Nick's verbatim) — but with effective limit reduced
    # by CP_RESERVE for VEV_4000 so counterparty has reserved capacity.
    # ──────────────────────────────────────────────────────────────────
    def vev_voucher_orders(self, state, rock_mid, voucher_symbol,
                           voucher_order_depth, voucher_position):
        try:
            voucher_mid = self.calculate_fair_value(voucher_order_depth)
            if voucher_mid is None:
                return []

            tte    = self.get_time_to_expiry(state.timestamp)
            strike = self.voucher_strikes[voucher_symbol]
            if tte <= 0:
                return []

            current_iv = self.implied_volatility(voucher_mid, rock_mid, strike,
                                                  tte, self.risk_free_rate)
            self.past_volatilities.setdefault(voucher_symbol, []).append(current_iv)
            if len(self.past_volatilities[voucher_symbol]) > self.volatility_window:
                self.past_volatilities[voucher_symbol].pop(0)
            volatility = statistics.mean(self.past_volatilities[voucher_symbol])

            theo = self.black_scholes_call(rock_mid, strike, tte,
                                           self.risk_free_rate, volatility)

            limit = self.position_limits[voucher_symbol]
            # Reserve CP slice for VEV_4000 so MM doesn't blow our combined limit
            if voucher_symbol == 'VEV_4000' and (FOLLOW_MARK_14 or FADE_MARK_38):
                limit = max(0, limit - CP_RESERVE)

            orders = []

            # Buy at int(theo), full long-side headroom
            cp_buy_used = self.cp_buy.get(voucher_symbol, 0)
            buy_room = limit - voucher_position - cp_buy_used
            if buy_room > 0:
                orders.append(Order(voucher_symbol, int(theo), buy_room))

            # Sell at int(theo)+1, full short-side headroom
            cp_sell_used = self.cp_sell.get(voucher_symbol, 0)
            sell_room = limit + voucher_position - cp_sell_used
            if sell_room > 0:
                orders.append(Order(voucher_symbol, int(theo + 1), -sell_room))

            return orders
        except Exception as e:
            logger.print(f"Error vev_voucher_orders[{voucher_symbol}]: {e}")
            return []

    # ──────────────────────────────────────────────────────────────────
    # HYDROGEL_PACK — Nick's verbatim trade_hydrogel + make_hydrogel_market.
    # Effective limit reduced by CP_RESERVE so counterparty has room.
    # ──────────────────────────────────────────────────────────────────
    def trade_hydrogel(self, state: TradingState, td: dict) -> None:
        WINDOW         = 10000
        Z_THRESHOLD    = 1.5
        POSITION_LIMIT = self.position_limits["HYDROGEL_PACK"]
        if FOLLOW_MARK_14 or FADE_MARK_38:
            POSITION_LIMIT = max(0, POSITION_LIMIT - CP_RESERVE)

        order_depth = state.order_depths.get("HYDROGEL_PACK")
        if order_depth is None or not order_depth.buy_orders or not order_depth.sell_orders:
            return

        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        mid = (best_bid + best_ask) / 2

        prices = td.get("hg_prices", [])
        prices.append(mid)
        if len(prices) > WINDOW:
            prices = prices[-WINDOW:]
        td["hg_prices"] = prices

        if len(prices) < 100:
            return

        mean = float(np.mean(prices))
        std  = float(np.std(prices))
        if std == 0:
            return

        buy_threshold  = mean - Z_THRESHOLD * std
        sell_threshold = mean + Z_THRESHOLD * std
        position = state.position.get("HYDROGEL_PACK", 0)

        # Take asks below buy_threshold (passive opportunism)
        for ask, vol in sorted(order_depth.sell_orders.items()):
            if ask > buy_threshold:
                break
            capacity = POSITION_LIMIT - position - self.Hydrogel_buy_orders
            if capacity <= 0:
                break
            size = min(capacity, -vol)
            self.Hydrogel_buy_orders += size
            self.orders.setdefault("HYDROGEL_PACK", []).append(
                Order("HYDROGEL_PACK", ask, size))

        # Sell into bids above sell_threshold
        for bid, vol in sorted(order_depth.buy_orders.items(), reverse=True):
            if bid < sell_threshold:
                break
            capacity = POSITION_LIMIT + position - self.Hydrogel_sell_orders
            if capacity <= 0:
                break
            size = min(capacity, vol)
            self.Hydrogel_sell_orders += size
            self.orders.setdefault("HYDROGEL_PACK", []).append(
                Order("HYDROGEL_PACK", bid, -size))

    def make_hydrogel_market(self, state: TradingState) -> None:
        POSITION_LIMIT = self.position_limits["HYDROGEL_PACK"]
        if FOLLOW_MARK_14 or FADE_MARK_38:
            POSITION_LIMIT = max(0, POSITION_LIMIT - CP_RESERVE)
        SPREAD = 5
        INVENTORY_SKEW = 0.05

        order_depth = state.order_depths.get("HYDROGEL_PACK")
        if order_depth is None or not order_depth.buy_orders or not order_depth.sell_orders:
            return

        position = state.position.get("HYDROGEL_PACK", 0)
        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        bid_vol  =  order_depth.buy_orders[best_bid]
        ask_vol  = -order_depth.sell_orders[best_ask]

        microprice = (best_bid * ask_vol + best_ask * bid_vol) / (bid_vol + ask_vol)
        skew    = round(position * INVENTORY_SKEW)
        our_bid = round(microprice) - SPREAD - skew
        our_ask = round(microprice) + SPREAD - skew
        if our_bid >= our_ask:
            our_bid = round(microprice) - 1 - skew
            our_ask = round(microprice) + 1 - skew

        max_buy  = max(0, POSITION_LIMIT - position - self.Hydrogel_buy_orders)
        max_sell = max(0, POSITION_LIMIT + position - self.Hydrogel_sell_orders)

        if max_buy > 0:
            self.Hydrogel_buy_orders += max_buy
            self.orders.setdefault("HYDROGEL_PACK", []).append(
                Order("HYDROGEL_PACK", our_bid, max_buy))
        if max_sell > 0:
            self.Hydrogel_sell_orders += max_sell
            self.orders.setdefault("HYDROGEL_PACK", []).append(
                Order("HYDROGEL_PACK", our_ask, -max_sell))

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

        current_day = state.timestamp // 1_000_000
        if current_day != self.current_day:
            self.current_day = current_day
        self.days_to_expiry = max(0, 3 - current_day)

        # Reset per-tick state
        self.orders = {}
        self.Hydrogel_buy_orders  = 0
        self.Hydrogel_sell_orders = 0
        self.cp_buy  = {}
        self.cp_sell = {}
        self._cache_check()

        # 1. COUNTERPARTY — runs FIRST so MM knows what capacity to leave
        try:
            self._counterparty_orders(state)
        except Exception as e:
            logger.print(f"Error counterparty: {e}")

        # 2. HYDROGEL_PACK
        try:
            self.trade_hydrogel(state, trader_data)
            self.make_hydrogel_market(state)
        except Exception as e:
            logger.print(f"Error HG: {e}")

        # 3. VOUCHER MM (all 10 strikes)
        if "VELVETFRUIT_EXTRACT" in state.order_depths:
            ve_od = state.order_depths["VELVETFRUIT_EXTRACT"]
            ve_mid = self.calculate_fair_value(ve_od)
            if ve_mid is not None:
                for vsym in self.voucher_strikes.keys():
                    if vsym not in state.order_depths:
                        continue
                    vpos = state.position.get(vsym, 0)
                    try:
                        vorders = self.vev_voucher_orders(
                            state, ve_mid, vsym,
                            state.order_depths[vsym], vpos
                        )
                        if vorders:
                            self.orders.setdefault(vsym, []).extend(vorders)
                    except Exception as e:
                        logger.print(f"Error voucher {vsym}: {e}")

        # NO velvetfruit_orders (compared spot to call price — bug)
        # NO find_arbitrage_opportunities (inverted directions — bug)

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