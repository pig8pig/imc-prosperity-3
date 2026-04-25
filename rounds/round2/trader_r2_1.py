from datamodel import Listing, Observation, Order, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState
import json
import numpy as np
import math
from statistics import NormalDist
from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
# Logger
# ─────────────────────────────────────────────────────────────────────────────
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
                compressed.append(
                    [trade.symbol, trade.price, trade.quantity, trade.buyer, trade.seller, trade.timestamp]
                )
        return compressed

    def compress_observations(self, observations: Observation) -> list[Any]:
        conversion_observations = {}
        for product, observation in observations.conversionObservations.items():
            conversion_observations[product] = [
                observation.bidPrice, observation.askPrice, observation.transportFees,
                observation.exportTariff, observation.importTariff,
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

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────
STATIC_SYMBOL  = 'ASH_COATED_OSMIUM'
DYNAMIC_SYMBOL = 'INTARIAN_PEPPER_ROOT'

POS_LIMITS = {
    STATIC_SYMBOL:  80,
    DYNAMIC_SYMBOL: 80,
}

SLOPE = 0.001  # PEPPER ROOT linear trend per timestamp

# When |position| exceeds this fraction of the limit, stop posting
# orders that would accumulate the position further.
# Reasoning: if we're at +73/80 and post more bids, we'll hit the ceiling
# and lose the ability to earn the spread on the buy side at all.
# Copied from DynamicTrader v1 which had this already.
NEAR_LIMIT_FRACTION = 0.9


# ─────────────────────────────────────────────────────────────────────────────
# ProductTrader — base class (unchanged from v1)
# ─────────────────────────────────────────────────────────────────────────────
class ProductTrader:

    def __init__(self, name, state, prints, new_trader_data, product_group=None):
        self.orders = []
        self.name = name
        self.state = state
        self.prints = prints
        self.new_trader_data = new_trader_data
        self.product_group = name if product_group is None else product_group

        self.last_traderData = self.get_last_traderData()

        self.position_limit = POS_LIMITS.get(self.name, 0)
        self.initial_position = self.state.position.get(self.name, 0)
        self.expected_position = self.initial_position

        self.mkt_buy_orders, self.mkt_sell_orders = self.get_order_depth()
        self.bid_wall, self.wall_mid, self.ask_wall = self.get_walls()
        self.best_bid, self.best_ask = self.get_best_bid_ask()

        self.max_allowed_buy_volume, self.max_allowed_sell_volume = self.get_max_allowed_volume()
        self.total_mkt_buy_volume, self.total_mkt_sell_volume = self.get_total_market_buy_sell_volume()

    def get_last_traderData(self):
        last_traderData = {}
        try:
            if self.state.traderData != '':
                last_traderData = json.loads(self.state.traderData)
        except:
            pass
        return last_traderData

    def get_best_bid_ask(self):
        best_bid = best_ask = None
        try:
            if len(self.mkt_buy_orders) > 0:
                best_bid = max(self.mkt_buy_orders.keys())
            if len(self.mkt_sell_orders) > 0:
                best_ask = min(self.mkt_sell_orders.keys())
        except:
            pass
        return best_bid, best_ask

    def get_walls(self):
        bid_wall = wall_mid = ask_wall = None
        try: bid_wall = min([x for x, _ in self.mkt_buy_orders.items()])
        except: pass
        try: ask_wall = max([x for x, _ in self.mkt_sell_orders.items()])
        except: pass
        try: wall_mid = (bid_wall + ask_wall) / 2
        except: pass
        return bid_wall, wall_mid, ask_wall

    def get_total_market_buy_sell_volume(self):
        market_bid_volume = market_ask_volume = 0
        try:
            market_bid_volume  = sum([v for p, v in self.mkt_buy_orders.items()])
            market_ask_volume  = sum([v for p, v in self.mkt_sell_orders.items()])
        except:
            pass
        return market_bid_volume, market_ask_volume

    def get_max_allowed_volume(self):
        max_allowed_buy_volume  = self.position_limit - self.initial_position
        max_allowed_sell_volume = self.position_limit + self.initial_position
        return max_allowed_buy_volume, max_allowed_sell_volume

    def get_order_depth(self):
        order_depth, buy_orders, sell_orders = {}, {}, {}
        try: order_depth: OrderDepth = self.state.order_depths[self.name]
        except: pass
        try: buy_orders  = {bp: abs(bv) for bp, bv in sorted(order_depth.buy_orders.items(),  key=lambda x: x[0], reverse=True)}
        except: pass
        try: sell_orders = {sp: abs(sv) for sp, sv in sorted(order_depth.sell_orders.items(), key=lambda x: x[0])}
        except: pass
        return buy_orders, sell_orders

    def bid(self, price, volume, logging=True):
        abs_volume = min(abs(int(volume)), self.max_allowed_buy_volume)
        order = Order(self.name, int(price), abs_volume)
        if logging: self.log("BUYO", {"p": price, "s": self.name, "v": int(volume)}, product_group='ORDERS')
        self.max_allowed_buy_volume -= abs_volume
        self.orders.append(order)

    def ask(self, price, volume, logging=True):
        abs_volume = min(abs(int(volume)), self.max_allowed_sell_volume)
        order = Order(self.name, int(price), -abs_volume)
        if logging: self.log("SELLO", {"p": price, "s": self.name, "v": int(volume)}, product_group='ORDERS')
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
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# StaticTrader — ASH_COATED_OSMIUM
#
# Strategy: market-making around wall_mid.
# Identical to v1 EXCEPT for one addition:
#
#   NEAR-LIMIT SUPPRESSION (new):
#   When position is within 10% of the limit on one side, we stop posting
#   orders that would push us further toward that limit.
#
#   Why: if we're at +73, posting more bids will pin us at +80, and then the
#   buy side of our market-making stops earning entirely. By suppressing bids
#   near the long limit (and asks near the short limit) we stay closer to
#   neutral and earn the spread on both sides more consistently.
#
#   This is the ONLY change from v1.
# ─────────────────────────────────────────────────────────────────────────────
class StaticTrader(ProductTrader):
    def __init__(self, state, prints, new_trader_data):
        super().__init__(STATIC_SYMBOL, state, prints, new_trader_data)

    def get_orders(self):

        if self.wall_mid is not None:

            ##########################################################
            ####### 1. TAKING — unchanged from v1
            ##########################################################
            for sp, sv in self.mkt_sell_orders.items():
                if sp <= self.wall_mid - 1:
                    self.bid(sp, sv, logging=False)
                elif sp <= self.wall_mid and self.initial_position < 0:
                    volume = min(sv, abs(self.initial_position))
                    self.bid(sp, volume, logging=False)

            for bp, bv in self.mkt_buy_orders.items():
                if bp >= self.wall_mid + 1:
                    self.ask(bp, bv, logging=False)
                elif bp >= self.wall_mid and self.initial_position > 0:
                    volume = min(bv, self.initial_position)
                    self.ask(bp, volume, logging=False)

            ##########################################################
            ####### 2. MAKING — unchanged from v1, prices identical
            ##########################################################
            bid_price = min(int(self.best_bid), int(self.wall_mid) - 1)
            ask_price = max(int(self.best_ask), int(self.wall_mid) + 1)

            for bp, bv in self.mkt_buy_orders.items():
                overbidding_price = bp + 1
                if bv > 1 and overbidding_price < self.wall_mid:
                    bid_price = max(bid_price, overbidding_price)
                    break
                elif bp < self.wall_mid:
                    bid_price = max(bid_price, bp)
                    break

            for sp, sv in self.mkt_sell_orders.items():
                underbidding_price = sp - 1
                if sv > 1 and underbidding_price > self.wall_mid:
                    ask_price = min(ask_price, underbidding_price)
                    break
                elif sp > self.wall_mid:
                    ask_price = min(ask_price, sp)
                    break

            # ── NEW: near-limit suppression ──
            # NEAR_LIMIT_FRACTION = 0.9 → threshold = 72 out of 80
            # If we're already very long, don't post more bids.
            # If we're already very short, don't post more asks.
            # This keeps the position from getting pinned at the extremes,
            # ensuring both sides of the book remain active.
            near_limit = NEAR_LIMIT_FRACTION * self.position_limit  # = 72

            if self.initial_position < near_limit:
                self.bid(bid_price, self.max_allowed_buy_volume)
            if self.initial_position > -near_limit:
                self.ask(ask_price, self.max_allowed_sell_volume)

        return {self.name: self.orders}


# ─────────────────────────────────────────────────────────────────────────────
# DynamicTrader — INTARIAN_PEPPER_ROOT
#
# Exact v1 code. Buy everything as fast as possible to accumulate max long
# and ride the +0.001/tick trend. No changes.
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
# Trader — main entry point
# ─────────────────────────────────────────────────────────────────────────────
class Trader:

    def bid(self):
        """
        Market Access Fee bid for Round 2.
        Top 50% of bids across all participants get 25% more order book flow.
        The bid is deducted from PnL only if accepted.

        300 is a conservative estimate that likely clears the median.
        The expected value is positive if extra flow adds >300 to OSMIUM MM PnL.
        With ~1800/day from MM and 25% more flow, expected gain is ~450/day,
        so even a 1-day edge justifies this bid.
        """
        return 300

    def run(self, state: TradingState):
        result: dict[str, list[Order]] = {}
        new_trader_data = {}
        prints = {
            "GENERAL": {
                "TIMESTAMP": state.timestamp,
                "POSITIONS": state.position,
            },
        }

        product_traders = {
            STATIC_SYMBOL:  StaticTrader,
            DYNAMIC_SYMBOL: DynamicTrader,
        }

        result, conversions = {}, 0
        for symbol, product_trader in product_traders.items():
            if symbol in state.order_depths:
                try:
                    trader = product_trader(state, prints, new_trader_data)
                    result.update(trader.get_orders())
                except Exception as e:
                    logger.print(f"ERROR in {symbol}: {e}")

        try:    final_trader_data = json.dumps(new_trader_data)
        except: final_trader_data = ''

        try:    logger.print(json.dumps(prints))
        except: pass

        logger.flush(state, result, conversions, final_trader_data)
        return result, conversions, final_trader_data