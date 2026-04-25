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
HYDROGEL_SYMBOL  = 'HYDROGEL_PACK'
VELVET_SYMBOL    = 'VELVETFRUIT_EXTRACT'

# Voucher chain — Round 3 European calls on VELVETFRUIT_EXTRACT.
# Skipped strikes (4000, 4500, 6000, 6500) have unreliable IV / near-zero vega
# and contribute nothing to the static-arb scan even at the chain edges.
ACTIVE_STRIKES = [5000, 5100, 5200, 5300, 5400, 5500]
VOUCHER_SYMBOLS = [f"VEV_{k}" for k in ACTIVE_STRIKES]
VOUCHER_LIMIT = 300
ARB_PER_VOUCHER_SLICE = 50  # capacity reserved for StaticArbScanner

# Position limits
POS_LIMITS = {
    HYDROGEL_SYMBOL: 200,
    VELVET_SYMBOL:   200,
    **{sym: VOUCHER_LIMIT for sym in VOUCHER_SYMBOLS},
}
 
# Direction constants
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
# StaticTrader — HYDROGEL_PACK, VELVETFRUIT_EXTRACT
# Strategy: pure market-making around a stable fair value.
# The product's fair value is effectively the midpoint of the outermost
# bid/ask prices (wall_mid). We:
#   1. Take any mispriced orders (crossing the mid)
#   2. Post passive bids/asks just inside the spread, trying to overbid/underask
#      existing orders to get queue priority.
# ─────────────────────────────────────────────────────────────────────────────
class StaticTrader(ProductTrader):
 
    def __init__(self, symbol, state, prints, new_trader_data):
        super().__init__(symbol, state, prints, new_trader_data)
 
    def get_orders(self):
 
        if self.wall_mid is None:
            return {self.name: self.orders}
 
        ##########################################################
        ####### 1. TAKING — aggressive orders that cross mid
        ##########################################################
 
        # Buy any asks clearly below fair value
        for sp, sv in self.mkt_sell_orders.items():
            if sp <= self.wall_mid - 1:
                self.bid(sp, sv, logging=False)
            # If short, also buy asks right at mid to reduce inventory risk
            elif sp <= self.wall_mid and self.initial_position < 0:
                volume = min(sv, abs(self.initial_position))
                self.bid(sp, volume, logging=False)
 
        # Sell any bids clearly above fair value
        for bp, bv in self.mkt_buy_orders.items():
            if bp >= self.wall_mid + 1:
                self.ask(bp, bv, logging=False)
            # If long, also sell bids right at mid to reduce inventory risk
            elif bp >= self.wall_mid and self.initial_position > 0:
                volume = min(bv, self.initial_position)
                self.ask(bp, volume, logging=False)
 
        ###########################################################
        ####### 2. MAKING — passive limit orders inside the spread
        ###########################################################
 
        # Base case: top of book, capped at wall_mid
        bid_price = min(int(self.best_bid), int(self.wall_mid) - 1)
        ask_price = max(int(self.best_ask), int(self.wall_mid) + 1)
 
        # OVERBIDDING: beat the best existing bid below mid by 1
        # (skip 1-lot orders to avoid pennying noise)
        for bp, bv in self.mkt_buy_orders.items():
            overbidding_price = bp + 1
            if bv > 1 and overbidding_price < self.wall_mid:
                bid_price = max(bid_price, overbidding_price)
                break
            elif bp < self.wall_mid:
                bid_price = max(bid_price, bp)
                break
 
        # UNDERCUTTING: undercut the best existing ask above mid by 1
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
# StaticArbScanner — model-free arbitrage on the voucher chain
# Scans 15 vertical pairs + 4 butterflies for no-arb violations using
# executable bid/ask quotes (NOT mids). Sizes each leg by min(book volume,
# position-limit headroom) and caps any single arb at ARB_PER_VOUCHER_SLICE
# units. Designed to run BEFORE the volatility-based OptionTrader so it gets
# first dibs on rare opportunities. Wraps everything in try/except so a bad
# book never crashes the trader.
# ─────────────────────────────────────────────────────────────────────────────
class StaticArbScanner:

    MIN_PROFIT_PER_UNIT = 0.5  # below this, treat as noise
    MAX_SIZE_PER_ARB = 50       # avoid eating multiple price levels at once

    def __init__(self, state, prints, position_overrides=None):
        self.state = state
        self.prints = prints
        # External callers (e.g. an OptionTrader running first) can pre-claim
        # voucher capacity by passing overrides; default to the live position.
        self.position_overrides = position_overrides or {}
        self.orders: dict[str, list[Order]] = {sym: [] for sym in VOUCHER_SYMBOLS}
        self.violations_logged = []

    def _log(self, kind, payload):
        group = self.prints.get("ARB", [])
        group.append({kind: payload})
        self.prints["ARB"] = group

    def _book(self, symbol):
        """Return (sorted_bids_desc, sorted_asks_asc) with positive volumes."""
        depth = self.state.order_depths.get(symbol)
        if depth is None:
            return [], []
        bids = sorted(((p, abs(v)) for p, v in depth.buy_orders.items()),
                      key=lambda x: -x[0])
        asks = sorted(((p, abs(v)) for p, v in depth.sell_orders.items()),
                      key=lambda x: x[0])
        return bids, asks

    def _best(self, bids, asks):
        best_bid = (bids[0][0], bids[0][1]) if bids else (None, 0)
        best_ask = (asks[0][0], asks[0][1]) if asks else (None, 0)
        return best_bid, best_ask

    def _initial_position(self, symbol):
        if symbol in self.position_overrides:
            return self.position_overrides[symbol]
        return self.state.position.get(symbol, 0)

    def _buy_headroom(self, symbol, claimed_buy):
        """Remaining BUY capacity given the arb-only slice and prior claims."""
        pos = self._initial_position(symbol)
        # Buys reserved to the arb scanner: ARB_PER_VOUCHER_SLICE on top of pos
        cap = min(VOUCHER_LIMIT, pos + ARB_PER_VOUCHER_SLICE)
        return max(0, cap - pos - claimed_buy)

    def _sell_headroom(self, symbol, claimed_sell):
        pos = self._initial_position(symbol)
        cap = max(-VOUCHER_LIMIT, pos - ARB_PER_VOUCHER_SLICE)
        return max(0, pos - cap - claimed_sell)

    def get_orders(self):
        try:
            return self._scan()
        except Exception as e:
            self._log("ERROR", str(e))
            return {}

    def _scan(self):
        # Snapshot best bid/ask + top-of-book volume per voucher. If a side
        # is missing we just record None and skip arbs that need it.
        quotes = {}
        for sym in VOUCHER_SYMBOLS:
            bids, asks = self._book(sym)
            (bp, bv), (ap, av) = self._best(bids, asks)
            quotes[sym] = {"bid": bp, "bid_v": bv, "ask": ap, "ask_v": av}

        # claimed_buy/sell tracks how many units of each voucher we've already
        # promised this tick — used to update headroom across multiple arbs.
        claimed_buy = {sym: 0 for sym in VOUCHER_SYMBOLS}
        claimed_sell = {sym: 0 for sym in VOUCHER_SYMBOLS}
        # taken_ask_v / taken_bid_v: track book volume already spoken-for so a
        # later arb doesn't double-count the same lifted level.
        taken_ask_v = {sym: 0 for sym in VOUCHER_SYMBOLS}
        taken_bid_v = {sym: 0 for sym in VOUCHER_SYMBOLS}

        candidates = []  # list of (profit_total, executor_callable, descriptor)

        # ─── 1. Vertical pairs (15) ─────────────────────────────────────────
        n = len(ACTIVE_STRIKES)
        for i in range(n):
            for j in range(i + 1, n):
                k1, k2 = ACTIVE_STRIKES[i], ACTIVE_STRIKES[j]
                s1, s2 = VOUCHER_SYMBOLS[i], VOUCHER_SYMBOLS[j]
                q1, q2 = quotes[s1], quotes[s2]

                # 1A. Monotonicity: C(K1) >= C(K2). Violation -> buy K1, sell K2.
                if q1["ask"] is not None and q2["bid"] is not None:
                    edge = q2["bid"] - q1["ask"]
                    if edge >= self.MIN_PROFIT_PER_UNIT:
                        candidates.append({
                            "type": "MONO",
                            "edge": edge,
                            "buy": [(s1, q1["ask"], q1["ask_v"])],
                            "sell": [(s2, q2["bid"], q2["bid_v"])],
                            "detail": f"buy {s1}@{q1['ask']} sell {s2}@{q2['bid']} edge={edge:.2f}",
                        })

                # 1B. Spread upper bound: C(K1) - C(K2) <= K2 - K1.
                # Violation -> sell K1, buy K2.
                if q1["bid"] is not None and q2["ask"] is not None:
                    edge = q1["bid"] - q2["ask"] - (k2 - k1)
                    if edge >= self.MIN_PROFIT_PER_UNIT:
                        candidates.append({
                            "type": "VSPREAD",
                            "edge": edge,
                            "buy": [(s2, q2["ask"], q2["ask_v"])],
                            "sell": [(s1, q1["bid"], q1["bid_v"])],
                            "detail": f"sell {s1}@{q1['bid']} buy {s2}@{q2['ask']} "
                                      f"width={k2-k1} edge={edge:.2f}",
                        })

        # ─── 2. Butterflies (4): K2 = (K1+K3)/2 ─────────────────────────────
        for i in range(n - 2):
            s1, s2, s3 = VOUCHER_SYMBOLS[i], VOUCHER_SYMBOLS[i + 1], VOUCHER_SYMBOLS[i + 2]
            q1, q2, q3 = quotes[s1], quotes[s2], quotes[s3]
            if (q1["ask"] is None or q3["ask"] is None or q2["bid"] is None):
                continue
            butterfly = q1["ask"] - 2 * q2["bid"] + q3["ask"]
            edge = -butterfly
            if edge >= self.MIN_PROFIT_PER_UNIT:
                candidates.append({
                    "type": "BFLY",
                    "edge": edge,
                    "buy": [(s1, q1["ask"], q1["ask_v"]),
                            (s3, q3["ask"], q3["ask_v"])],
                    "sell": [(s2, q2["bid"], q2["bid_v"] // 2)],
                    "sell_mult": {s2: 2},  # 2× units of K2 per butterfly
                    "detail": f"buy {s1}@{q1['ask']} sell 2x {s2}@{q2['bid']} "
                              f"buy {s3}@{q3['ask']} edge={edge:.4f}",
                })

        if not candidates:
            return self.orders

        # ─── 3. Rank by per-unit edge (we'll size each individually) ────────
        candidates.sort(key=lambda c: -c["edge"])

        for cand in candidates:
            buy_legs = cand["buy"]
            sell_legs = cand["sell"]
            sell_mult = cand.get("sell_mult", {})

            # Compute max executable size = min over legs of headroom & remaining vol
            sizes = [self.MAX_SIZE_PER_ARB]
            for sym, _, vol in buy_legs:
                avail_vol = vol - taken_ask_v[sym]
                head = self._buy_headroom(sym, claimed_buy[sym])
                sizes.append(max(0, min(avail_vol, head)))
            for sym, _, vol in sell_legs:
                mult = sell_mult.get(sym, 1)
                avail_vol = (vol - taken_bid_v[sym]) // max(1, mult)
                head = self._sell_headroom(sym, claimed_sell[sym]) // max(1, mult)
                sizes.append(max(0, min(avail_vol, head)))
            size = min(sizes)
            if size < 1:
                continue
            unit_profit = cand["edge"]
            total_profit = size * unit_profit
            if unit_profit < self.MIN_PROFIT_PER_UNIT:
                continue

            # Place legs and update accounting
            for sym, price, _ in buy_legs:
                self.orders.setdefault(sym, []).append(Order(sym, int(price), int(size)))
                claimed_buy[sym] += size
                taken_ask_v[sym] += size
            for sym, price, _ in sell_legs:
                mult = sell_mult.get(sym, 1)
                qty = int(size) * mult
                self.orders.setdefault(sym, []).append(Order(sym, int(price), -qty))
                claimed_sell[sym] += qty
                taken_bid_v[sym] += qty

            self.violations_logged.append({
                "type": cand["type"],
                "size": int(size),
                "unit_edge": round(unit_profit, 4),
                "total": round(total_profit, 2),
                "detail": cand["detail"],
            })

        if self.violations_logged:
            self._log("EXEC", self.violations_logged)
        return self.orders


# ─────────────────────────────────────────────────────────────────────────────
# Trader — main entry point called by the Prosperity platform each tick
# Instantiates one sub-trader per active product and merges all their orders.
# ─────────────────────────────────────────────────────────────────────────────
class Trader:

    def run(self, state: TradingState):
        result: dict[str, list[Order]] = {}
        new_trader_data = {}

        # Shared logging dict — all sub-traders write into this, keyed by group
        prints = {
            "GENERAL": {
                "TIMESTAMP": state.timestamp,
                "POSITIONS": state.position,
            },
        }

        # Both delta-1 products use StaticTrader with identical logic
        static_symbols = [HYDROGEL_SYMBOL, VELVET_SYMBOL]

        result, conversions = {}, 0

        for symbol in static_symbols:
            # Only run a trader if market data exists for its symbol this tick
            if symbol in state.order_depths:
                try:
                    trader = StaticTrader(symbol, state, prints, new_trader_data)
                    result.update(trader.get_orders())
                except Exception as e:
                    logger.print(f"ERROR in {symbol}: {e}")

        # Static arbitrage scan on the voucher chain — runs BEFORE any future
        # vol-based OptionTrader so it claims rare model-free edges first.
        try:
            arb = StaticArbScanner(state, prints)
            arb_orders = arb.get_orders()
            for sym, ords in arb_orders.items():
                if not ords:
                    continue
                result.setdefault(sym, []).extend(ords)
        except Exception as e:
            logger.print(f"ERROR in StaticArbScanner: {e}")

        # Serialise persistent state for next tick
        try:
            final_trader_data = json.dumps(new_trader_data)
        except:
            final_trader_data = ''

        try:
            logger.print(json.dumps(prints))
        except:
            pass

        logger.flush(state, result, conversions, final_trader_data)
        return result, conversions, final_trader_data