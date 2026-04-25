from datamodel import Listing, Observation, Order, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState
import json
import numpy as np
import math
from statistics import NormalDist
from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
# Logger
# Serialises all orders, state, and debug prints into a single JSON line that
# the Prosperity platform can ingest. Truncates content via binary-search so
# the output never exceeds the platform's 3750-character log limit.
# ─────────────────────────────────────────────────────────────────────────────
class Logger:
    def __init__(self) -> None:
        self.logs = ""
        self.max_log_length = 3750

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(self, state: TradingState, orders: dict[Symbol, list[Order]], conversions: int, trader_data: str) -> None:
        # Compute how many characters the fixed-size fields already consume so
        # we know how much space is left to distribute across the three variable
        # fields (traderData, trader_data output, logs).
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
                compressed.append(
                    [
                        trade.symbol,
                        trade.price,
                        trade.quantity,
                        trade.buyer,
                        trade.seller,
                        trade.timestamp,
                    ]
                )
        return compressed

    def compress_observations(self, observations: Observation) -> list[Any]:
        conversion_observations = {}
        for product, observation in observations.conversionObservations.items():
            conversion_observations[product] = [
                observation.bidPrice,
                observation.askPrice,
                observation.transportFees,
                observation.exportTariff,
                observation.importTariff,
                observation.sugarPrice,
                observation.sunlightIndex,
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
        # Binary-search for the longest prefix that fits within max_length when
        # JSON-encoded (adding "..." if truncated).
        lo, hi = 0, min(len(value), max_length)
        out = ""
        while lo <= hi:
            mid = (lo + hi) // 2
            candidate = value[:mid]
            if len(candidate) < len(value):
                candidate += "..."
            encoded_candidate = json.dumps(candidate)
            if len(encoded_candidate) <= max_length:
                out = candidate
                lo = mid + 1
            else:
                hi = mid - 1
        return out


logger = Logger()

####### GENERAL ####### GENERAL ####### GENERAL ####### GENERAL ####### GENERAL ####### GENERAL ####### GENERAL ####### GENERAL

# ─────────────────────────────────────────────────────────────────────────────
# Symbol constants — one place to rename products if the exchange changes them
# ─────────────────────────────────────────────────────────────────────────────
STATIC_SYMBOL = 'ASH_COATED_OSMIUM'   # stable fair-value product → pure market-making (more or less random walk)
DYNAMIC_SYMBOL = 'INTARIAN_PEPPER_ROOT'              # trending product → follow trend

# Maximum number of units we are allowed to hold (long or short) per product
POS_LIMITS = {
    STATIC_SYMBOL: 80,
    DYNAMIC_SYMBOL: 80,
}

# SLOPE: estimated from historical data for the trending product (DynamicTrader uses this to estimate fair value)
SLOPE = 0.001

# Direction constants used throughout
LONG, NEUTRAL, SHORT = 1, 0, -1

# ─────────────────────────────────────────────────────────────────────────────
# ProductTrader — base class
# Wraps one product symbol and provides:
#   • Parsed order book (buy/sell sides, walls, best bid/ask)
#   • Helpers to place bids/asks while respecting position limits
#   • Informed-trader detection (checks if Olivia has traded this product)
# Each specific strategy class inherits from this and overrides get_orders().
# ─────────────────────────────────────────────────────────────────────────────

class ProductTrader:

    def __init__(self, name, state, prints, new_trader_data, product_group=None):

        self.orders = []

        self.name = name
        self.state = state
        self.prints = prints
        self.new_trader_data = new_trader_data
        # product_group controls which logging bucket this trader writes to
        self.product_group = name if product_group is None else product_group

        self.last_traderData = self.get_last_traderData()

        self.position_limit = POS_LIMITS.get(self.name, 0)
        self.initial_position = self.state.position.get(self.name, 0) # position at beginning of round

        # Tracks what position we expect to end up with after our orders fill,
        # used by the ETF hedger to size constituent hedge orders.
        self.expected_position = self.initial_position


        self.mkt_buy_orders, self.mkt_sell_orders = self.get_order_depth()
        # "walls" = outermost bid/ask prices in the book (the price extremes)
        self.bid_wall, self.wall_mid, self.ask_wall = self.get_walls()
        self.best_bid, self.best_ask = self.get_best_bid_ask()

        # Remaining capacity for new buy/sell orders this tick
        self.max_allowed_buy_volume, self.max_allowed_sell_volume = self.get_max_allowed_volume() # gets updated when order created
        self.total_mkt_buy_volume, self.total_mkt_sell_volume = self.get_total_market_buy_sell_volume()

    def get_last_traderData(self):
        # Deserialise the persistent state string passed in from the previous tick
        last_traderData = {}
        try:
            if self.state.traderData != '':
                last_traderData = json.loads(self.state.traderData)
        except: self.log("ERROR", 'td')

        return last_traderData


    def get_best_bid_ask(self):
        # Best bid = highest price someone is willing to buy at (we can sell there)
        # Best ask = lowest price someone is willing to sell at (we can buy there)
        best_bid = best_ask = None

        try:
            if len(self.mkt_buy_orders) > 0:
                best_bid = max(self.mkt_buy_orders.keys())
            if len(self.mkt_sell_orders) > 0:
                best_ask = min(self.mkt_sell_orders.keys())
        except: pass

        return best_bid, best_ask


    def get_walls(self):
        # The "walls" are the outermost (worst) prices in the book — used as
        # anchors for passive market-making orders.
        bid_wall = wall_mid = ask_wall = None

        try: bid_wall = min([x for x,_ in self.mkt_buy_orders.items()])
        except: pass

        try: ask_wall = max([x for x,_ in self.mkt_sell_orders.items()])
        except: pass

        # Mid-point between the two extreme prices — our proxy for fair value
        try: wall_mid = (bid_wall + ask_wall) / 2
        except: pass

        return bid_wall, wall_mid, ask_wall

    def get_total_market_buy_sell_volume(self):
        # Sum of all volume on each side of the book
        market_bid_volume = market_ask_volume = 0

        try:
            market_bid_volume = sum([v for p, v in self.mkt_buy_orders.items()])
            market_ask_volume = sum([v for p, v in self.mkt_sell_orders.items()])
        except: pass

        return market_bid_volume, market_ask_volume


    def get_max_allowed_volume(self):
        # How much more we can buy/sell before hitting the position limit
        max_allowed_buy_volume = self.position_limit - self.initial_position
        max_allowed_sell_volume = self.position_limit + self.initial_position
        return max_allowed_buy_volume, max_allowed_sell_volume

    def get_order_depth(self):
        # Returns two sorted dicts: buy side (descending by price) and
        # sell side (ascending by price). Volumes are always positive here.
        order_depth, buy_orders, sell_orders = {}, {}, {}

        try: order_depth: OrderDepth = self.state.order_depths[self.name]
        except: pass
        try: buy_orders = {bp: abs(bv) for bp, bv in sorted(order_depth.buy_orders.items(), key=lambda x: x[0], reverse=True)}
        except: pass
        try: sell_orders = {sp: abs(sv) for sp, sv in sorted(order_depth.sell_orders.items(), key=lambda x: x[0])}
        except: pass

        return buy_orders, sell_orders


    def bid(self, price, volume, logging=True):
        # Place a buy order, capped at our remaining buy capacity
        abs_volume = min(abs(int(volume)), self.max_allowed_buy_volume)
        order = Order(self.name, int(price), abs_volume)
        if logging: self.log("BUYO", {"p":price, "s":self.name, "v":int(volume)}, product_group='ORDERS')
        self.max_allowed_buy_volume -= abs_volume  # reduce remaining capacity
        self.orders.append(order)

    def ask(self, price, volume, logging=True):
        # Place a sell order (negative quantity), capped at remaining sell capacity
        abs_volume = min(abs(int(volume)), self.max_allowed_sell_volume)
        order = Order(self.name, int(price), -abs_volume)
        if logging: self.log("SELLO", {"p":price, "s":self.name, "v":int(volume)}, product_group='ORDERS')
        self.max_allowed_sell_volume -= abs_volume
        self.orders.append(order)

    def log(self, kind, message, product_group=None):
        if product_group is None: product_group = self.product_group

        if product_group == 'ORDERS':
            group = self.prints.get(product_group, [])
            group.append({kind: message})
        else:
            group = self.prints.get(product_group, {})
            group[kind] = message

        self.prints[product_group] = group


    def get_orders(self):
        # overwrite this in each trader
        return {}



# ─────────────────────────────────────────────────────────────────────────────
# StaticTrader — ASH_COATED_OSMIUM
# Strategy: pure market-making around a stable fair value.
# The product's fair value is effectively the midpoint of the outermost
# bid/ask prices (wall_mid). We:
#   1. Take any mispriced orders (crossing the mid)
#   2. Post passive bids/asks just inside the spread, trying to overbid/underask
#      existing orders to get queue priority.
# ─────────────────────────────────────────────────────────────────────────────
class StaticTrader(ProductTrader):
    def __init__(self, state, prints, new_trader_data):
        super().__init__(STATIC_SYMBOL, state, prints, new_trader_data)

    def get_orders(self):

        if self.wall_mid is not None:

            ##########################################################
            ####### 1. TAKING — aggressive orders that cross mid
            ##########################################################
            # Buy any asks that are clearly below fair value
            for sp, sv in self.mkt_sell_orders.items():
                if sp <= self.wall_mid - 1:
                    self.bid(sp, sv, logging=False)
                # If we're short, also buy asks right at mid to reduce risk
                elif sp <= self.wall_mid and self.initial_position < 0:
                        volume = min(sv,  abs(self.initial_position))
                        self.bid(sp, volume, logging=False)

            # Sell any bids that are clearly above fair value
            for bp, bv in self.mkt_buy_orders.items():
                if bp >= self.wall_mid + 1:
                    self.ask(bp, bv, logging=False)
                # If we're long, also sell bids right at mid to reduce risk
                elif bp >= self.wall_mid and self.initial_position > 0:
                        volume = min(bv,  self.initial_position)
                        self.ask(bp, volume, logging=False)

            ###########################################################
            ####### 2. MAKING — passive limit orders inside the spread
            ###########################################################
            # Base case: match current best bid/ask (top of book), capped at wall_mid.
            # Fallback is top-of-book rather than the outer wall so we stay competitive.
            bid_price = min(int(self.best_bid), int(self.wall_mid) - 1)
            ask_price = max(int(self.best_ask), int(self.wall_mid) + 1)

            # OVERBIDDING: find the best existing bid below mid and beat it by 1
            # (skip thin 1-lot orders to avoid pennying noise)
            for bp, bv in self.mkt_buy_orders.items():
                overbidding_price = bp + 1
                if bv > 1 and overbidding_price < self.wall_mid:
                    bid_price = max(bid_price, overbidding_price)
                    break
                elif bp < self.wall_mid:
                    bid_price = max(bid_price, bp)
                    break

            # UNDERBIDDING: find the best existing ask above mid and undercut it by 1
            for sp, sv in self.mkt_sell_orders.items():
                underbidding_price = sp - 1
                if sv > 1 and underbidding_price > self.wall_mid:
                    ask_price = min(ask_price, underbidding_price)
                    break
                elif sp > self.wall_mid:
                    ask_price = min(ask_price, sp)
                    break

            # POST ORDERS — use all remaining capacity
            self.bid(bid_price, self.max_allowed_buy_volume)
            self.ask(ask_price, self.max_allowed_sell_volume)


        return {self.name: self.orders}
    

    # ─────────────────────────────────────────────────────────────────────────────
# DynamicTrader - INTARIAN_PEPPER_ROOT
# Strategy: predict price using a linear trend and follow it:
# Normal: post passive bid/ask just inside the walls (like StaticTrader).
# ─────────────────────────────────────────────────────────────────────────────
class DynamicTrader(ProductTrader):
    def __init__(self, state, prints, new_trader_data):
        super().__init__(DYNAMIC_SYMBOL, state, prints, new_trader_data)

    # def get_orders(self):
    #     if self.best_bid is None or self.best_ask is None:
    #         return {self.name: self.orders}
        
    #     if self.bid_wall is None or self.ask_wall is None:
    #         return {self.name: self.orders}
        
    #     # In Dynamic Trader, use trader data to persist the intercept
    #     intercept = self.last_traderData.get(DYNAMIC_SYMBOL, {}).get('intercept', None)

    #     current_mid = (self.best_bid + self.best_ask) / 2
    #     # correct for data where mid price is zero
    #     if current_mid <= 0:
    #         return {self.name: self.orders}
        
    #     # Sanity check — if walls are corrupted by rogue orders, skip this tick
    #     if intercept is not None:
    #         expected =  SLOPE * self.state.timestamp + intercept
    #         if abs(expected - current_mid) > 500:
    #             return {self.name: self.orders}
        
    #     current_intercept = current_mid - SLOPE * self.state.timestamp

    #     if intercept is None:
    #         # First tick, estimate intercept from current mid price
    #         intercept = current_intercept
    #     else:
    #         # check for abrupt changes in the intercept, which would indicate a change of day
    #         if abs(current_intercept - intercept) > 950:
    #             intercept = current_intercept
        
    #     self.new_trader_data[DYNAMIC_SYMBOL] = {'intercept': intercept}
    #     # Calculate fair value using the linear trend (slope * time + intercept)
    #     fair_value = SLOPE * self.state.timestamp + intercept

    #     # logger.print(f"t={self.state.timestamp}, mid={current_mid:.1f}, fair={fair_value:.1f}, intercept={intercept:.1f}, pos={self.initial_position}")
        
    #     ##########################################################
    #     ####### 1. TAKING — aggressive orders that cross mid
    #     ##########################################################
    #     # Buy any asks that are clearly below fair value
    #     for sp, sv in self.mkt_sell_orders.items():
    #         if sp <= fair_value - 1:
    #             self.bid(sp, sv, logging=False)
    #         # If we're short, also buy asks right at mid to reduce risk
    #         elif sp <= fair_value and self.initial_position < 0:
    #             volume = min(sv,  abs(self.initial_position))
    #             self.bid(sp, volume, logging=False)

    #     # Sell any bids that are clearly above fair value
    #     for bp, bv in self.mkt_buy_orders.items():
    #         if bp >= fair_value + 1:
    #             self.ask(bp, bv, logging=False)
    #         # If we're long, also sell bids right at mid to reduce risk
    #         elif bp >= fair_value and self.initial_position > 0:
    #             volume = min(bv,  self.initial_position)
    #             self.ask(bp, volume, logging=False)

    #     ###########################################################
    #     ####### 2. MAKING — passive limit orders inside the spread
    #     ###########################################################
    #     # Base case: match current best bid/ask (top of book), capped at fair_value.
    #     # Fallback is top-of-book rather than the outer wall so we stay competitive.
    #     bid_price = min(int(self.best_bid), int(fair_value) - 1)
    #     ask_price = max(int(self.best_ask), int(fair_value) + 1)

    #     # OVERBIDDING: find the best existing bid below fair value and beat it by 1
    #     # (skip thin 1-lot orders to avoid pennying noise)
    #     for bp, bv in self.mkt_buy_orders.items():
    #         overbidding_price = bp + 1
    #         if bv > 1 and overbidding_price < fair_value:
    #             bid_price = max(bid_price, overbidding_price)
    #             break
    #         # If the best bid is a 1-lot order, just match it
    #         elif bp < fair_value:
    #             bid_price = max(bid_price, bp)
    #             break

    #     # UNDERCUTTING: find the best existing ask above fair value and undercut it by 1
    #     for sp, sv in self.mkt_sell_orders.items():
    #         underbidding_price = sp - 1
    #         if sv > 1 and underbidding_price > fair_value:
    #             ask_price = min(ask_price, underbidding_price)
    #             break
    #         elif sp > fair_value:
    #             ask_price = min(ask_price, sp)
    #             break

    #     # Inventory skew - shift quotes based on position
    #     skew = int((self.initial_position / self.position_limit) * 4)
    #     bid_price -= skew
    #     ask_price -= skew

    #     # Guard against crossed quotes (can happen in a 1-tick-wide book)
    #     if bid_price >= ask_price:
    #         bid_price = ask_price - 1

    #     # POST ORDERS — skip the accumulating side when near position limits
    #     near_limit = 0.9 * self.position_limit
    #     if self.initial_position < near_limit:
    #         self.bid(bid_price, self.max_allowed_buy_volume)
    #     if self.initial_position > -near_limit:
    #         self.ask(ask_price, self.max_allowed_sell_volume)


    #     return {self.name: self.orders}
    def get_orders(self):
        # INTARIAN_PEPPER_ROOT always trends up — hold max long
        for sp, sv in self.mkt_sell_orders.items():
            if self.max_allowed_buy_volume > 0:
                self.bid(sp, sv)
        return {self.name: self.orders}

# ─────────────────────────────────────────────────────────────────────────────
# Trader — main entry point called by the Prosperity platform each tick
# Instantiates one sub-trader per active product and merges all their orders.
# ─────────────────────────────────────────────────────────────────────────────
class Trader:

    def run(self, state: TradingState):
        result:dict[str,list[Order]] = {}
        new_trader_data = {}
        # Shared logging dict — all sub-traders write into this, keyed by group
        prints = {
            "GENERAL": {
                "TIMESTAMP": state.timestamp,
                "POSITIONS": state.position
            },
        }

        # Map each "representative" symbol to its trader class.
        # ETF and Option traders handle multiple symbols internally.
        product_traders = {
            STATIC_SYMBOL: StaticTrader,
            DYNAMIC_SYMBOL: DynamicTrader,
        }

        result, conversions = {}, 0
        for symbol, product_trader in product_traders.items():
            # Only run a trader if market data exists for its symbol this tick
            if symbol in state.order_depths:

                try:
                    trader = product_trader(state, prints, new_trader_data)
                    result.update(trader.get_orders())
                # except: pass
                except Exception as e:
                    logger.print(f"ERROR in {symbol}: {e}")


        # Serialise persistent state for next tick
        try: final_trader_data = json.dumps(new_trader_data)
        except: final_trader_data = ''

        try: logger.print(json.dumps(prints))
        except: pass

        logger.flush(state, result, conversions, final_trader_data)
        return result, conversions, final_trader_data
        
