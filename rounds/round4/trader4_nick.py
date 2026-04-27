from typing import List, Any, Dict, Tuple
import json
import math
import statistics

import numpy as np

from datamodel import *
from datamodel import Listing, Observation, Order, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState


# ──────────────────────────────────────────────────────────────────────────
# Logger (unchanged from the original file)
# ──────────────────────────────────────────────────────────────────────────
class Logger:
    def __init__(self) -> None:
        self.logs = ""
        self.max_log_length = 3750

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(self, state: TradingState, orders: dict[Symbol, list[Order]], conversions: int, trader_data: str) -> None:
        base_length = len(
            self.to_json(
                [
                    self.compress_state(state, ""),
                    self.compress_orders(orders),
                    conversions,
                    "",
                    "",
                ]
            )
        )

        max_item_length = (self.max_log_length - base_length) // 3

        print(
            self.to_json(
                [
                    self.compress_state(state, self.truncate(state.traderData, max_item_length)),
                    self.compress_orders(orders),
                    conversions,
                    self.truncate(trader_data, max_item_length),
                    self.truncate(self.logs, max_item_length),
                ]
            )
        )
        self.logs = ""

    def compress_state(self, state: TradingState, trader_data: str) -> list[Any]:
        return [
            state.timestamp,
            trader_data,
            self.compress_listings(state.listings),
            self.compress_order_depths(state.order_depths),
            self.compress_trades(state.own_trades),
            self.compress_trades(state.market_trades),
            state.position,
            self.compress_observations(state.observations),
        ]

    def compress_listings(self, listings: dict[Symbol, Listing]) -> list[list[Any]]:
        compressed = []
        for listing in listings.values():
            compressed.append([listing.symbol, listing.product, listing.denomination])
        return compressed

    def compress_order_depths(self, order_depths: dict[Symbol, OrderDepth]) -> dict[Symbol, list[Any]]:
        compressed = {}
        for symbol, order_depth in order_depths.items():
            compressed[symbol] = [order_depth.buy_orders, order_depth.sell_orders]
        return compressed

    def compress_trades(self, trades: dict[Symbol, list[Trade]]) -> list[list[Any]]:
        compressed = []
        for arr in trades.values():
            for trade in arr:
                compressed.append([trade.symbol, trade.price, trade.quantity,
                                   trade.buyer, trade.seller, trade.timestamp])
        return compressed

    def compress_observations(self, observations: Observation) -> list[Any]:
        conversion_observations = {}
        for product, observation in observations.conversionObservations.items():
            conversion_observations[product] = [
                observation.bidPrice, observation.askPrice,
                observation.transportFees, observation.exportTariff, observation.importTariff,
                observation.sugarPrice, observation.sunlightIndex,
            ]
        return [observations.plainValueObservations, conversion_observations]

    def compress_orders(self, orders: dict[Symbol, list[Order]]) -> list[list[Any]]:
        compressed = []
        for arr in orders.values():
            for order in arr:
                compressed.append([order.symbol, order.price, order.quantity])
        return compressed

    def to_json(self, value: Any) -> str:
        return json.dumps(value, cls=ProsperityEncoder, separators=(",", ":"))

    def truncate(self, value: str, max_length: int) -> str:
        if len(value) <= max_length:
            return value
        return value[: max_length - 3] + "..."


logger = Logger()


# ──────────────────────────────────────────────────────────────────────────
# Trader — replicates the other team's volcanic-rock-voucher strategy,
# adapted for VELVETFRUIT_EXTRACT (underlying) and the 10 VEV_* vouchers.
# All previously-disabled trades (rock + 3 vouchers) are now ENABLED, which
# in our adaptation means underlying trading + every voucher strike is on.
# ──────────────────────────────────────────────────────────────────────────
class Trader:
    def __init__(self):
        # Map each voucher symbol → strike price
        self.voucher_strikes = {
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

        # All vouchers + the underlying are ACTIVE (the team had rock + 3 strikes off;
        # we re-enable them all).
        self.active_products = {
            "VELVETFRUIT_EXTRACT": True,
            "HYDROGEL_PACK":       True,
            "VEV_4000":            True,
            "VEV_4500":            True,
            "VEV_5000":            True,
            "VEV_5100":            True,
            "VEV_5200":            True,
            "VEV_5300":            True,
            "VEV_5400":            True,
            "VEV_5500":            True,
            "VEV_6000":            True,
            "VEV_6500":            True,
        }

        # Position limits (matches user's existing limits)
        self.position_limits = {
            "HYDROGEL_PACK":       200,
            "VELVETFRUIT_EXTRACT": 200,
            "VEV_4000": 300, "VEV_4500": 300, "VEV_5000": 300,
            "VEV_5100": 300, "VEV_5200": 300, "VEV_5300": 300,
            "VEV_5400": 300, "VEV_5500": 300, "VEV_6000": 300,
            "VEV_6500": 300,
        }

        # ── The other team's voucher-strategy parameters (verbatim) ───────
        # Round runs for 3 days, so we adapt days_to_expiry from 7 → 3.
        self.days_to_expiry = 3
        self.mean_volatility = 0.18
        self.volatility_window = 30
        self.zscore_threshold = 1.8           # legacy / unused (kept for parity)
        self.past_volatilities: Dict[str, List[float]] = {}
        self.arbitrage_threshold = 0.001
        self.max_arbitrage_size = 50
        self.risk_free_rate = 0.0
        self.stop_loss_multiplier = 1.2       # legacy / unused
        self.profit_target_multiplier = 2.5   # legacy / unused
        self.max_stop_loss_hits = 1           # legacy / unused
        self.stop_loss_hits = 0               # legacy / unused
        self.positions: Dict[str, dict] = {}
        self.daily_pnl = 0
        self.current_day = 0
        self.max_daily_loss = 50000           # legacy / unused
        self.profit_target = 20000            # legacy / unused
        self.position_scale = 1.0
        self.max_volatility_history = 30
        self.cache: Dict[str, float] = {}

        # HYDROGEL bookkeeping (kept from the original file)
        self.Hydrogel_buy_orders = 0
        self.Hydrogel_sell_orders = 0
        self.Hydrogel_position = 0

        # Per-tick output state
        self.orders: Dict[str, List[Order]] = {}
        self.conversions = 0
        self.traderData = "SAMPLE"

    # ──────────────────────────────────────────────────────────────────
    # General helpers (mid-price, position closing)
    # ──────────────────────────────────────────────────────────────────
    def calculate_fair_value(self, order_depth: OrderDepth):
        try:
            if not order_depth.buy_orders or not order_depth.sell_orders:
                return None
            best_bid = max(order_depth.buy_orders.keys())
            best_ask = min(order_depth.sell_orders.keys())
            return (best_bid + best_ask) / 2
        except Exception as e:
            logger.print(f"Error calculating fair value: {e}")
            return None

    def close_position(self, product: str, order_depth: OrderDepth, position: int) -> List[Order]:
        orders = []
        if position == 0:
            return orders
        if position > 0:
            if order_depth.buy_orders:
                best_bid = max(order_depth.buy_orders.keys())
                sell_quantity = min(position, order_depth.buy_orders[best_bid])
                if sell_quantity > 0:
                    orders.append(Order(product, best_bid, -sell_quantity))
        else:
            if order_depth.sell_orders:
                best_ask = min(order_depth.sell_orders.keys())
                buy_quantity = min(-position, -order_depth.sell_orders[best_ask])
                if buy_quantity > 0:
                    orders.append(Order(product, best_ask, buy_quantity))
        return orders

    # ──────────────────────────────────────────────────────────────────
    # Black-Scholes block — verbatim from the source team
    # ──────────────────────────────────────────────────────────────────
    def norm_cdf(self, x: float) -> float:
        # Abramowitz–Stegun 7.1.26
        a1 =  0.254829592
        a2 = -0.284496736
        a3 =  1.421413741
        a4 = -1.453152027
        a5 =  1.061405429
        p  =  0.3275911
        sign = 1
        if x < 0:
            sign = -1
        x = abs(x) / math.sqrt(2.0)
        t = 1.0 / (1.0 + p * x)
        y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * math.exp(-x * x)
        return 0.5 * (1.0 + sign * y)

    def norm_pdf(self, x: float) -> float:
        return (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-0.5 * x * x)

    def black_scholes_call(self, S: float, K: float, T: float, r: float, sigma: float) -> float:
        cache_key = f"bs_call_{S}_{K}_{T}_{r}_{sigma}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        try:
            if S <= 0 or K <= 0 or T <= 0:
                return 0.0
            d1 = (math.log(S / K) + (r + sigma ** 2 / 2) * T) / (sigma * math.sqrt(T))
            d2 = d1 - sigma * math.sqrt(T)
            result = S * self.norm_cdf(d1) - K * math.exp(-r * T) * self.norm_cdf(d2)
            self.cache[cache_key] = result
            return result
        except Exception as e:
            logger.print(f"Error in black_scholes_call: {e}")
            return 0.0

    def black_scholes_delta(self, S: float, K: float, T: float, r: float, sigma: float) -> float:
        if S <= 0 or K <= 0 or T <= 0:
            return 0.0
        d1 = (math.log(S / K) + (r + sigma ** 2 / 2) * T) / (sigma * math.sqrt(T))
        return self.norm_cdf(d1)

    def black_scholes_vega(self, S: float, K: float, T: float, r: float, sigma: float) -> float:
        if S <= 0 or K <= 0 or T <= 0:
            return 0.0
        d1 = (math.log(S / K) + (r + sigma ** 2 / 2) * T) / (sigma * math.sqrt(T))
        return S * math.sqrt(T) * self.norm_pdf(d1)

    def implied_volatility(self, option_price: float, S: float, K: float, T: float, r: float) -> float:
        cache_key = f"iv_{option_price}_{S}_{K}_{T}_{r}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        try:
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
            self.cache[cache_key] = sigma
            return sigma
        except Exception as e:
            logger.print(f"Error in implied_volatility: {e}")
            return self.mean_volatility

    def get_time_to_expiry(self, timestamp: int) -> float:
        # Round 4 spans 3 in-game days. timestamp//1_000_000 maps to days 0,1,2.
        # Mirrors the other team's `max(0, 6 - current_day)` / 365 with their 7-day expiry,
        # adapted to: `max(0, 3 - current_day)` so T > 0 throughout the last trading day.
        current_day = timestamp // 1_000_000
        days_remaining = max(0, 3 - current_day)
        return days_remaining / 365.0

    # ──────────────────────────────────────────────────────────────────
    # Vertical-spread arbitrage scanner (verbatim adaptation)
    # ──────────────────────────────────────────────────────────────────
    def find_arbitrage_opportunities(
        self,
        state: TradingState,
        rock_order_depth: OrderDepth,
        rock_mid: float,
    ) -> List[Order]:
        orders: List[Order] = []
        voucher_prices: Dict[str, float] = {}
        for voucher_symbol in self.voucher_strikes.keys():
            if voucher_symbol in state.order_depths:
                voucher_mid = self.calculate_fair_value(state.order_depths[voucher_symbol])
                if voucher_mid is not None:
                    voucher_prices[voucher_symbol] = voucher_mid

        symbols = list(self.voucher_strikes.keys())
        strikes = list(self.voucher_strikes.values())

        for i in range(len(symbols)):
            for j in range(i + 1, len(symbols)):
                symbol1, symbol2 = symbols[i], symbols[j]
                strike1, strike2 = strikes[i], strikes[j]
                if symbol1 not in voucher_prices or symbol2 not in voucher_prices:
                    continue
                price1 = voucher_prices[symbol1]
                price2 = voucher_prices[symbol2]
                spread      = abs(price1 - price2)
                strike_diff = abs(strike1 - strike2)
                if abs(spread - strike_diff) > self.arbitrage_threshold * strike_diff:
                    if spread > strike_diff * (1 + self.arbitrage_threshold):
                        if price1 > price2:
                            orders.append(Order(
                                symbol1,
                                int(min(state.order_depths[symbol1].sell_orders.keys())),
                                -self.max_arbitrage_size,
                            ))
                            orders.append(Order(
                                symbol2,
                                int(max(state.order_depths[symbol2].buy_orders.keys())),
                                self.max_arbitrage_size,
                            ))
                        else:
                            orders.append(Order(
                                symbol2,
                                int(min(state.order_depths[symbol2].sell_orders.keys())),
                                -self.max_arbitrage_size,
                            ))
                            orders.append(Order(
                                symbol1,
                                int(max(state.order_depths[symbol1].buy_orders.keys())),
                                self.max_arbitrage_size,
                            ))
        return orders

    # ──────────────────────────────────────────────────────────────────
    # Voucher Black-Scholes market-maker (verbatim adaptation)
    # ──────────────────────────────────────────────────────────────────
    def vev_voucher_orders(
        self,
        state: TradingState,
        rock_order_depth: OrderDepth,
        rock_position: int,
        voucher_symbol: str,
        voucher_order_depth: OrderDepth,
        voucher_position: int,
        trader_data: dict,
    ) -> Tuple[List[Order], List[Order]]:
        try:
            rock_mid    = self.calculate_fair_value(rock_order_depth)
            voucher_mid = self.calculate_fair_value(voucher_order_depth)
            if rock_mid is None or voucher_mid is None:
                return [], []

            tte    = self.get_time_to_expiry(state.timestamp)
            strike = self.voucher_strikes[voucher_symbol]

            # IV from voucher mid
            current_implied_vol = self.implied_volatility(
                voucher_mid, rock_mid, strike, tte, self.risk_free_rate
            )

            # Rolling-window storage of IVs per strike
            if voucher_symbol not in self.past_volatilities:
                self.past_volatilities[voucher_symbol] = []
            self.past_volatilities[voucher_symbol].append(current_implied_vol)
            if len(self.past_volatilities[voucher_symbol]) > self.volatility_window:
                self.past_volatilities[voucher_symbol].pop(0)

            if len(self.past_volatilities[voucher_symbol]) > 0:
                volatility = statistics.mean(self.past_volatilities[voucher_symbol])
            else:
                volatility = current_implied_vol

            # Theoretical price using rolling-window IV
            theoretical_price = self.black_scholes_call(
                rock_mid, strike, tte, self.risk_free_rate, volatility
            )

            limit       = self.position_limits[voucher_symbol]
            make_orders: List[Order] = []

            # Buy at floor(theoretical), max remaining long capacity
            if voucher_position < limit:
                buy_price = int(theoretical_price)
                make_orders.append(Order(
                    voucher_symbol,
                    buy_price,
                    limit - voucher_position,
                ))

            # Sell at ceil(theoretical) + 1, max remaining short capacity
            if voucher_position > -limit:
                sell_price = int(theoretical_price + 1)
                make_orders.append(Order(
                    voucher_symbol,
                    sell_price,
                    -limit - voucher_position,
                ))

            logger.print(
                f"VOUCHER {voucher_symbol} K={strike} S={rock_mid:.1f} "
                f"mid={voucher_mid:.2f} iv={current_implied_vol:.3f} "
                f"vol={volatility:.3f} theo={theoretical_price:.2f} "
                f"pos={voucher_position}"
            )
            return [], make_orders
        except Exception as e:
            logger.print(f"Error in vev_voucher_orders: {e}")
            return [], []

    # ──────────────────────────────────────────────────────────────────
    # Underlying directional trade based on inverted-BS theoretical
    # ──────────────────────────────────────────────────────────────────
    def velvetfruit_orders(
        self,
        rock_order_depth: OrderDepth,
        rock_position: int,
        state: TradingState,
    ) -> List[Order]:
        orders: List[Order] = []
        rock_mid = self.calculate_fair_value(rock_order_depth)
        if rock_mid is None:
            return orders

        # Average rolling-window IV across strikes
        rolling_vols: List[float] = []
        tte = self.get_time_to_expiry(state.timestamp)

        for voucher_symbol in self.voucher_strikes.keys():
            if voucher_symbol in self.past_volatilities and len(self.past_volatilities[voucher_symbol]) > 0:
                rolling_vols.append(statistics.mean(self.past_volatilities[voucher_symbol]))
            elif voucher_symbol in state.order_depths:
                voucher_order_depth = state.order_depths[voucher_symbol]
                voucher_mid = self.calculate_fair_value(voucher_order_depth)
                if voucher_mid is not None:
                    strike = self.voucher_strikes[voucher_symbol]
                    current_vol = self.implied_volatility(
                        voucher_mid, rock_mid, strike, tte, self.risk_free_rate
                    )
                    rolling_vols.append(current_vol)

        vol = statistics.mean(rolling_vols) if rolling_vols else self.mean_volatility

        avg_strike = sum(self.voucher_strikes.values()) / len(self.voucher_strikes)
        theoretical_price = self.black_scholes_call(
            rock_mid, avg_strike, tte, self.risk_free_rate, vol
        )

        threshold      = 0.5
        position_limit = self.position_limits["VELVETFRUIT_EXTRACT"]

        if rock_mid < theoretical_price - threshold:
            if len(rock_order_depth.sell_orders) > 0:
                best_ask = min(rock_order_depth.sell_orders.keys())
                quantity = min(
                    position_limit - rock_position,
                    -rock_order_depth.sell_orders[best_ask],
                )
                if quantity > 0:
                    orders.append(Order("VELVETFRUIT_EXTRACT", best_ask, quantity))
        elif rock_mid > theoretical_price + threshold:
            if len(rock_order_depth.buy_orders) > 0:
                best_bid = max(rock_order_depth.buy_orders.keys())
                quantity = min(
                    position_limit + rock_position,
                    rock_order_depth.buy_orders[best_bid],
                )
                if quantity > 0:
                    orders.append(Order("VELVETFRUIT_EXTRACT", best_bid, -quantity))

        logger.print(
            f"VEX UND mid={rock_mid:.2f} theo={theoretical_price:.2f} "
            f"vol={vol:.3f} avg_K={avg_strike:.0f} pos={rock_position} "
            f"orders={len(orders)}"
        )
        return orders

    # ──────────────────────────────────────────────────────────────────
    # HYDROGEL_PACK strategy (kept from the original file)
    # ──────────────────────────────────────────────────────────────────
    def trade_hydrogel(self, state: TradingState, td: dict) -> None:
        WINDOW         = 10000
        Z_THRESHOLD    = 1.5
        POSITION_LIMIT = self.position_limits["HYDROGEL_PACK"]

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
        SPREAD         = 5
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

        # ── Decode persistent state (rolling IV history etc.) ───────────
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

        # Day rollover (resets daily counters and refreshes days_to_expiry)
        current_day = state.timestamp // 1_000_000
        if current_day != self.current_day:
            self.daily_pnl = 0
            self.current_day = current_day
        self.days_to_expiry = max(0, 3 - current_day)

        # Reset per-tick counters
        self.orders = {}
        self.conversions = 0
        for product in state.order_depths:
            self.orders[product] = []
        self.Hydrogel_buy_orders  = 0
        self.Hydrogel_sell_orders = 0

        # ── HYDROGEL_PACK (kept from original) ──────────────────────────
        self.trade_hydrogel(state, trader_data)
        self.make_hydrogel_market(state)

        # ── VELVETFRUIT_EXTRACT + VEV_* vouchers ────────────────────────
        if "VELVETFRUIT_EXTRACT" in state.order_depths:
            rock_position    = state.position.get("VELVETFRUIT_EXTRACT", 0)
            rock_order_depth = state.order_depths["VELVETFRUIT_EXTRACT"]
            rock_mid         = self.calculate_fair_value(rock_order_depth)

            if rock_mid is not None:
                # 1) Voucher market-making for every active strike
                for voucher_symbol in self.voucher_strikes.keys():
                    if voucher_symbol not in state.order_depths:
                        continue
                    voucher_position = state.position.get(voucher_symbol, 0)

                    if self.active_products.get(voucher_symbol, False):
                        take_orders, make_orders = self.vev_voucher_orders(
                            state, rock_order_depth, rock_position,
                            voucher_symbol, state.order_depths[voucher_symbol],
                            voucher_position, trader_data,
                        )
                        if take_orders or make_orders:
                            self.orders.setdefault(voucher_symbol, []).extend(
                                take_orders + make_orders
                            )
                    elif voucher_position != 0:
                        close_orders = self.close_position(
                            voucher_symbol,
                            state.order_depths[voucher_symbol],
                            voucher_position,
                        )
                        if close_orders:
                            self.orders.setdefault(voucher_symbol, []).extend(close_orders)

                # 2) Underlying — vertical-spread arb scan + directional trade
                if self.active_products.get("VELVETFRUIT_EXTRACT", False):
                    arbitrage_orders = self.find_arbitrage_opportunities(
                        state, rock_order_depth, rock_mid
                    )
                    for order in arbitrage_orders:
                        self.orders.setdefault(order.symbol, []).append(order)

                    vol_orders = self.velvetfruit_orders(
                        rock_order_depth, rock_position, state
                    )
                    if vol_orders:
                        self.orders.setdefault("VELVETFRUIT_EXTRACT", []).extend(vol_orders)
                elif rock_position != 0:
                    close_orders = self.close_position(
                        "VELVETFRUIT_EXTRACT", rock_order_depth, rock_position
                    )
                    if close_orders:
                        self.orders.setdefault("VELVETFRUIT_EXTRACT", []).extend(close_orders)

        # ── Persist state for next tick ─────────────────────────────────
        trader_data["past_volatilities"] = self.past_volatilities
        trader_data["current_day"]       = self.current_day
        # hg_prices is updated in-place inside trade_hydrogel
        self.traderData = json.dumps(trader_data)

        # Drop empty order lists for cleanliness
        result = {p: o for p, o in self.orders.items() if o}

        logger.flush(state, result, self.conversions, self.traderData)
        return result, self.conversions, self.traderData