from datamodel import Listing, Observation, Order, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState
import json
import math
import numpy as np
from statistics import NormalDist
from typing import Any


_N = NormalDist()
_SQRT_2PI = math.sqrt(2.0 * math.pi)


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


# ═════════════════════════════════════════════════════════════════════════════
# Black-Scholes pricer + implied-vol solver (inlined from bs_pricer.py)
# Stdlib + numpy only. T is in years; caller converts days/365.
# ═════════════════════════════════════════════════════════════════════════════

def _d1_d2(S, K, T, sigma, r):
    sst = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / sst
    return d1, d1 - sst


def bs_call(S, K, T, sigma, r=0.0):
    if T <= 0.0 or sigma <= 0.0:
        return max(S - K, 0.0)
    d1, d2 = _d1_d2(S, K, T, sigma, r)
    return S * _N.cdf(d1) - K * math.exp(-r * T) * _N.cdf(d2)


def bs_delta(S, K, T, sigma, r=0.0):
    if T <= 0.0 or sigma <= 0.0:
        if S > K:
            return 1.0
        if S < K:
            return 0.0
        return 0.5
    d1, _ = _d1_d2(S, K, T, sigma, r)
    return _N.cdf(d1)


def bs_vega(S, K, T, sigma, r=0.0):
    if T <= 0.0 or sigma <= 0.0:
        return 0.0
    d1, _ = _d1_d2(S, K, T, sigma, r)
    return S * _N.pdf(d1) * math.sqrt(T)


def bs_gamma(S, K, T, sigma, r=0.0):
    if T <= 0.0 or sigma <= 0.0:
        return 0.0
    d1, _ = _d1_d2(S, K, T, sigma, r)
    return _N.pdf(d1) / (S * sigma * math.sqrt(T))


def _iv_bisect(market_price, S, K, T, r, lo=1e-4, hi=5.0, tol=1e-8, max_iter=200):
    flo = bs_call(S, K, T, lo, r) - market_price
    fhi = bs_call(S, K, T, hi, r) - market_price
    if flo * fhi > 0.0:
        return float("nan")
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        fmid = bs_call(S, K, T, mid, r) - market_price
        if abs(fmid) < tol:
            return mid
        if flo * fmid <= 0.0:
            hi, fhi = mid, fmid
        else:
            lo, flo = mid, fmid
    return 0.5 * (lo + hi)


def implied_vol(market_price, S, K, T, r=0.0):
    if T <= 0.0:
        return float("nan")
    intrinsic = max(S - K * math.exp(-r * T), 0.0)
    if market_price < intrinsic - 1e-10:
        return float("nan")
    if market_price >= S:
        return float("nan")

    sigma = _SQRT_2PI / math.sqrt(T) * (market_price / S)
    sigma = min(5.0, max(0.001, sigma))

    for _ in range(50):
        price = bs_call(S, K, T, sigma, r)
        diff = price - market_price
        if abs(diff) < 1e-8:
            return sigma
        v = bs_vega(S, K, T, sigma, r)
        if v < 1e-10:
            return _iv_bisect(market_price, S, K, T, r)
        step = diff / v
        new_sigma = sigma - step
        if new_sigma <= 0.0 or new_sigma > 5.0:
            return _iv_bisect(market_price, S, K, T, r)
        sigma = new_sigma
    return _iv_bisect(market_price, S, K, T, r)


def bs_call_vec(S, K_arr, T, sigma_arr, r=0.0):
    K_arr = np.asarray(K_arr, dtype=float)
    sigma_arr = np.asarray(sigma_arr, dtype=float)
    if sigma_arr.ndim == 0:
        sigma_arr = np.broadcast_to(sigma_arr, K_arr.shape)
    out = np.empty(K_arr.shape, dtype=float)
    for i in range(K_arr.size):
        out.flat[i] = bs_call(S, float(K_arr.flat[i]), T, float(sigma_arr.flat[i]), r)
    return out


def implied_vol_vec(market_prices, S, K_arr, T, r=0.0):
    market_prices = np.asarray(market_prices, dtype=float)
    K_arr = np.asarray(K_arr, dtype=float)
    out = np.empty(K_arr.shape, dtype=float)
    for i in range(K_arr.size):
        out.flat[i] = implied_vol(
            float(market_prices.flat[i]), S, float(K_arr.flat[i]), T, r
        )
    return out


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


# ═════════════════════════════════════════════════════════════════════════════
# OptionTrader — Phase 5 smile-deviation alpha (inlined from
# phase5_smile_trader.py). Trades the 6 active VE vouchers off deviations
# from the live IV smile. Self-contained: state lives in new_trader_data.
# ═════════════════════════════════════════════════════════════════════════════

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


# ─────────────────────────────────────────────────────────────────────────────
# Trader — main entry point called by the Prosperity platform each tick
# Per Phase 6 spec: runs StaticTrader for HYDROGEL_PACK + VELVETFRUIT_EXTRACT,
# then OptionTrader for the 6 active vouchers. Each in its own try/except so
# one failure doesn't kill the others.
# ─────────────────────────────────────────────────────────────────────────────
class Trader:

    def run(self, state: TradingState):
        result: dict[str, list[Order]] = {}
        new_trader_data: dict = {}
        conversions = 0

        # Shared logging dict — all sub-traders write into this, keyed by group
        prints = {
            "GENERAL": {
                "TIMESTAMP": state.timestamp,
                "POSITIONS": state.position,
            },
        }

        # 1. StaticTrader for HYDROGEL_PACK
        if HYDROGEL_SYMBOL in state.order_depths:
            try:
                t = StaticTrader(HYDROGEL_SYMBOL, state, prints, new_trader_data)
                for sym, ords in t.get_orders().items():
                    if ords:
                        result.setdefault(sym, []).extend(ords)
            except Exception as e:
                logger.print(f"ERROR in StaticTrader[{HYDROGEL_SYMBOL}]: {e}")

        # 2. StaticTrader for VELVETFRUIT_EXTRACT
        if VELVET_SYMBOL in state.order_depths:
            try:
                t = StaticTrader(VELVET_SYMBOL, state, prints, new_trader_data)
                for sym, ords in t.get_orders().items():
                    if ords:
                        result.setdefault(sym, []).extend(ords)
            except Exception as e:
                logger.print(f"ERROR in StaticTrader[{VELVET_SYMBOL}]: {e}")

        # 3. OptionTrader — handles all 6 active vouchers internally
        try:
            opt = OptionTrader(state, prints, new_trader_data)
            for sym, ords in opt.get_orders().items():
                if ords:
                    result.setdefault(sym, []).extend(ords)
        except Exception as e:
            logger.print(f"ERROR in OptionTrader: {e}")

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
