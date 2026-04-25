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
# Strategy: sophisticated blend of MM, MT, mean reversion, and drift tracking.
#
#   Fair value: EWM of (best_bid + best_ask) / 2 — robust to rogue outer orders,
#               tracks slow drift, stored in trader_data across ticks.
#
#   1. Mean Reversion — when z-score exceeds ±2σ, take aggressively in the
#      reverting direction (high-confidence signal).
#   2. Taking — edge-proportional: full size for ≥2 tick mispricing,
#      1/3 capacity for ≥1 tick, inventory-reducing fill at fair value.
#   3. Making — passive quotes with:
#       • Top-of-book base case (not outer wall) for queue priority
#       • Overbid/undercut loop to beat thick orders
#       • Book imbalance drift skew (±1 tick toward excess pressure)
#       • Inventory skew (±3 ticks) to manage position risk
#       • Layered sizing: 60% primary + 40% backup 1 tick worse
#       • Near-limit shut-off (≥85%) on the accumulating side
# ─────────────────────────────────────────────────────────────────────────────
class StaticTrader(ProductTrader):

    EMA_ALPHA     = 0.1   # EWM decay for fair value (half-life ≈ 6.6 ticks)
    EMA_VAR_ALPHA = 0.1   # EWM decay for variance (same timescale)
    Z_REVERSION   = 2.0   # sigma threshold to trigger mean-reversion takes
    INV_SKEW      = 3     # max ticks of inventory skew at position limit
    NEAR_LIMIT    = 0.85  # fraction of limit at which we stop posting one side

    def __init__(self, state, prints, new_trader_data):
        super().__init__(STATIC_SYMBOL, state, prints, new_trader_data)

    def get_orders(self):
        if self.best_bid is None or self.best_ask is None:
            return {self.name: self.orders}

        # ── FAIR VALUE: EWM of best-bid/ask mid ──────────────────────────────
        raw_mid   = (self.best_bid + self.best_ask) / 2
        last_data = self.last_traderData.get(STATIC_SYMBOL, {})
        last_ema  = last_data.get('ema', raw_mid)
        last_var  = last_data.get('ema_var', 25.0)  # default: std=5 → var=25

        # Z-score uses the PREVIOUS ema so it measures current deviation from history
        residual = raw_mid - last_ema
        z_score  = residual / (last_var ** 0.5 + 1e-6)

        # Update and persist EWM fair value and variance for next tick
        fair_value = self.EMA_ALPHA * raw_mid + (1 - self.EMA_ALPHA) * last_ema
        ema_var    = self.EMA_VAR_ALPHA * residual ** 2 + (1 - self.EMA_VAR_ALPHA) * last_var
        self.new_trader_data[STATIC_SYMBOL] = {'ema': fair_value, 'ema_var': ema_var}

        ##########################################################
        ####### 1. MEAN REVERSION — high-confidence extreme takes
        ##########################################################
        # Price spiked 2+σ above EWM → expect downward reversion → sell into bids
        if z_score > self.Z_REVERSION and self.initial_position > -0.5 * self.position_limit:
            for bp, bv in self.mkt_buy_orders.items():
                if bp >= fair_value:
                    self.ask(bp, bv, logging=False)

        # Price dropped 2+σ below EWM → expect upward reversion → buy asks
        if z_score < -self.Z_REVERSION and self.initial_position < 0.5 * self.position_limit:
            for sp, sv in self.mkt_sell_orders.items():
                if sp <= fair_value:
                    self.bid(sp, sv, logging=False)

        ##########################################################
        ####### 2. TAKING — edge-proportional mispricing takes
        ##########################################################
        # mkt_sell_orders sorted cheapest first → highest edge first
        for sp, sv in self.mkt_sell_orders.items():
            edge = fair_value - sp
            if edge >= 2:
                # Clear mispricing — take full available size
                self.bid(sp, sv, logging=False)
            elif edge >= 1:
                # Moderate mispricing — partial take to avoid blowing the limit
                volume = min(sv, max(1, self.max_allowed_buy_volume // 3))
                self.bid(sp, volume, logging=False)
            elif sp <= fair_value and self.initial_position < 0:
                # At fair value while short — reduce inventory risk
                volume = min(sv, abs(self.initial_position))
                self.bid(sp, volume, logging=False)

        # mkt_buy_orders sorted highest first → highest edge first
        for bp, bv in self.mkt_buy_orders.items():
            edge = bp - fair_value
            if edge >= 2:
                self.ask(bp, bv, logging=False)
            elif edge >= 1:
                volume = min(bv, max(1, self.max_allowed_sell_volume // 3))
                self.ask(bp, volume, logging=False)
            elif bp >= fair_value and self.initial_position > 0:
                volume = min(bv, self.initial_position)
                self.ask(bp, volume, logging=False)

        ###########################################################
        ####### 3. MAKING — passive limit orders inside the spread
        ###########################################################
        # Base case: top of book, capped at fair_value ±1 (not outer wall)
        bid_price = min(int(self.best_bid), int(fair_value) - 1)
        ask_price = max(int(self.best_ask), int(fair_value) + 1)

        # OVERBIDDING: find the best thick bid below fair value and beat it by 1
        for bp, bv in self.mkt_buy_orders.items():
            overbidding_price = bp + 1
            if bv > 1 and overbidding_price < fair_value:
                bid_price = max(bid_price, overbidding_price)
                break
            elif bp < fair_value:
                bid_price = max(bid_price, bp)
                break

        # UNDERCUTTING: find the best thick ask above fair value and undercut it by 1
        for sp, sv in self.mkt_sell_orders.items():
            undercutting_price = sp - 1
            if sv > 1 and undercutting_price > fair_value:
                ask_price = min(ask_price, undercutting_price)
                break
            elif sp > fair_value:
                ask_price = min(ask_price, sp)
                break

        # Book imbalance drift signal: shift both quotes toward excess pressure (±1 tick)
        total_vol = self.total_mkt_buy_volume + self.total_mkt_sell_volume
        if total_vol > 0:
            imbalance  = (self.total_mkt_buy_volume - self.total_mkt_sell_volume) / total_vol
            drift_skew = int(imbalance * 1)
            bid_price += drift_skew
            ask_price += drift_skew

        # Inventory skew: shift both quotes down when long, up when short
        inv_skew   = int((self.initial_position / self.position_limit) * self.INV_SKEW)
        bid_price -= inv_skew
        ask_price -= inv_skew

        # Guard: crossed quotes can occur in a 1-tick-wide book after skewing
        if bid_price >= ask_price:
            bid_price = ask_price - 1

        # POST ORDERS — layered: 60% at primary price, 40% one tick worse as backup
        near_limit = self.NEAR_LIMIT * self.position_limit

        if self.initial_position < near_limit:
            v_primary = int(self.max_allowed_buy_volume * 0.6)
            v_backup  = self.max_allowed_buy_volume - v_primary
            self.bid(bid_price, v_primary)
            if v_backup > 0:
                self.bid(bid_price - 1, v_backup)

        if self.initial_position > -near_limit:
            v_primary = int(self.max_allowed_sell_volume * 0.6)
            v_backup  = self.max_allowed_sell_volume - v_primary
            self.ask(ask_price, v_primary)
            if v_backup > 0:
                self.ask(ask_price + 1, v_backup)

        return {self.name: self.orders}
    

    # ─────────────────────────────────────────────────────────────────────────────
# DynamicTrader - INTARIAN_PEPPER_ROOT
# Strategy: predict price using a linear trend and follow it:
# Normal: post passive bid/ask just inside the walls (like StaticTrader).
# ─────────────────────────────────────────────────────────────────────────────
class DynamicTrader(ProductTrader):
    def __init__(self, state, prints, new_trader_data):
        super().__init__(DYNAMIC_SYMBOL, state, prints, new_trader_data)

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
        
