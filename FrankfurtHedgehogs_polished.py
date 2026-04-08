from datamodel import Listing, Observation, Order, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState
import json
import numpy as np
import math
from statistics import NormalDist
from typing import Any

# Standard normal distribution used for Black-Scholes option pricing
_N = NormalDist()


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
ETF_BASKET_SYMBOLS = ['PICNIC_BASKET1', 'PICNIC_BASKET2']
ETF_CONSTITUENT_SYMBOLS = ['CROISSANTS', 'JAMS', 'DJEMBES']

STATIC_SYMBOL = 'RAINFOREST_RESIN'   # stable fair-value product → pure market-making
DYNAMIC_SYMBOL = 'KELP'              # trending product → follow informed trader
INK_SYMBOL = 'SQUID_INK'            # informed-trader-only signal

OPTION_UNDERLYING_SYMBOL = 'VOLCANIC_ROCK'

COMMODITY_SYMBOL = 'MAGNIFICENT_MACARONS'  # cross-venue arbitrage product

OPTION_SYMBOLS = [
    'VOLCANIC_ROCK_VOUCHER_9500',
    'VOLCANIC_ROCK_VOUCHER_9750',
    'VOLCANIC_ROCK_VOUCHER_10000',
    'VOLCANIC_ROCK_VOUCHER_10250',
    'VOLCANIC_ROCK_VOUCHER_10500'
    ]

# Maximum number of units we are allowed to hold (long or short) per product
POS_LIMITS = {
    STATIC_SYMBOL: 50,
    DYNAMIC_SYMBOL: 50,
    INK_SYMBOL: 50,
    ETF_BASKET_SYMBOLS[0]: 60,
    ETF_BASKET_SYMBOLS[1]: 100,
    ETF_CONSTITUENT_SYMBOLS[0]: 250,
    ETF_CONSTITUENT_SYMBOLS[1]: 350,
    ETF_CONSTITUENT_SYMBOLS[2]: 60,

    OPTION_UNDERLYING_SYMBOL: 400,
    **{os: 200 for os in OPTION_SYMBOLS},

    COMMODITY_SYMBOL: 75,
}

# Max units that can be converted to/from the external exchange per round
CONVERSION_LIMIT = 10

# Direction constants used throughout
LONG, NEUTRAL, SHORT = 1, 0, -1

# The known informed (alpha) trader whose trades we shadow
INFORMED_TRADER_ID = 'Olivia'


####### ETF ####### ETF ####### ETF ####### ETF ####### ETF ####### ETF ####### ETF ####### ETF ####### ETF ####### ETF ####### ETF

# How many units of each constituent make up one basket
# BASKET1 = 6 CROISSANTS + 3 JAMS + 1 DJEMBE
# BASKET2 = 4 CROISSANTS + 2 JAMS + 0 DJEMBES
ETF_CONSTITUENT_FACTORS = [[6, 3, 1], [4, 2, 0]]

# How far the basket must deviate from its NAV (in absolute price units) before
# we trade it. Wider threshold for BASKET1 because it has a noisier spread.
BASKET_THRESHOLDS = [80, 50]

# Seed the running-mean with this many "ghost" samples so it doesn't react to
# the very first few data points.
n_hist_samples = 60_000
# Historical average premium (basket price above NAV) used as the starting value
INITIAL_ETF_PREMIUMS = [5, 53]

# The constituent whose market trades we watch for Olivia's signal
ETF_INFORMED_CONSTITUENT = ETF_CONSTITUENT_SYMBOLS[0]   # CROISSANTS
# When Olivia is in the market, shift the open threshold by this many units
# (makes us more reluctant to trade against her direction)
ETF_THR_INFORMED_ADJS = [90, 90]

# If True, close our basket position whenever spread crosses zero
ETF_CLOSE_AT_ZERO = True
# If True, maintain a running mean of the premium rather than using the fixed initial value
CALCULATE_RUNNING_ETF_PREMIUM = True

# Fraction of expected basket position to hedge with constituent products
# (0.5 = hedge half the delta risk)
ETF_HEDGE_FACTOR = 0.5



####### OPTIONS ####### OPTIONS ####### OPTIONS ####### OPTIONS ####### OPTIONS ####### OPTIONS ####### OPTIONS ####### OPTIONS

# Current competition day (used to compute time-to-expiry for options)
DAY = 5

DAYS_PER_YEAR = 365

# IV-scalping: open a position when |market price − theo| > THR_OPEN,
# close it when the gap drops back below THR_CLOSE
THR_OPEN, THR_CLOSE = 0.5, 0
# Extra threshold buffer for options with very low vega (near expiry / deep OTM)
# because pricing is noisy there
LOW_VEGA_THR_ADJ = 0.5

# EMA window (in ticks) for normalising the option's theoretical-price deviation
THEO_NORM_WINDOW = 20

# Only engage IV scalping if the rolling volatility of the theo-diff is large
# enough (> IV_SCALPING_THR). Window controls the EMA length.
IV_SCALPING_THR = 0.7
IV_SCALPING_WINDOW = 100

# UNDERLYING mean-reversion parameters
underlying_mean_reversion_thr = 15    # price deviation (units) to trigger a trade
underlying_mean_reversion_window = 10 # EMA window (ticks)

# OPTIONS mean-reversion parameters (applied to combined IV + price signal)
options_mean_reversion_thr = 5
options_mean_reversion_window = 30


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

    def check_for_informed(self):
        # Detect whether our informed trader (Olivia) has recently bought or
        # sold this product. We keep track of her last buy/sell timestamp in
        # traderData so the signal persists across ticks.
        # Returns: direction (LONG/SHORT/NEUTRAL), last buy ts, last sell ts
        informed_direction, informed_bought_ts, informed_sold_ts = NEUTRAL, None, None

        # Load Olivia's last known timestamps from persistent state
        informed_bought_ts, informed_sold_ts = self.last_traderData.get(self.name, [None, None])

        # Scan this tick's trades for Olivia's activity
        trades = self.state.market_trades.get(self.name, []) + self.state.own_trades.get(self.name, [])

        for trade in trades:
            if trade.buyer == INFORMED_TRADER_ID:
                informed_bought_ts = trade.timestamp
            if trade.seller == INFORMED_TRADER_ID:
                informed_sold_ts = trade.timestamp

        self.new_trader_data[self.name] = [informed_bought_ts, informed_sold_ts]

        informed_sold = informed_sold_ts is not None
        informed_bought = informed_bought_ts is not None

        # Determine direction from the most recent of her buy vs. sell timestamp
        if not informed_bought and not informed_sold:
            informed_direction = NEUTRAL

        elif not informed_bought and informed_sold:
            informed_direction = SHORT

        elif informed_bought and not informed_sold:
            informed_direction = LONG

        elif informed_bought and informed_sold:
            if informed_sold_ts > informed_bought_ts:
                informed_direction = SHORT
            elif informed_sold_ts < informed_bought_ts:
                informed_direction = LONG
            else:
                informed_direction = NEUTRAL

        self.log('TD', self.new_trader_data[self.name])
        self.log('ID', informed_direction)

        return informed_direction, informed_bought_ts, informed_sold_ts


    def get_orders(self):
        # overwrite this in each trader
        return {}



# ─────────────────────────────────────────────────────────────────────────────
# StaticTrader — RAINFOREST_RESIN
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
            bid_price = int(self.bid_wall + 1) # base case: just inside the outer bid wall
            ask_price = int(self.ask_wall - 1) # base case: just inside the outer ask wall

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
# DynamicTrader — KELP
# Strategy: market-making that adjusts aggressively when Olivia is active.
# • Normal: post passive bid/ask just inside the walls (like StaticTrader).
# • Olivia recently bought: immediately buy up to 40 units at the ask wall.
# • Olivia is known LONG and spread is thin: widen our ask to avoid selling cheap.
# • Mirror logic applies on the sell side.
# ─────────────────────────────────────────────────────────────────────────────
class DynamicTrader(ProductTrader):
    def __init__(self, state, prints, new_trader_data):
        super().__init__(DYNAMIC_SYMBOL, state, prints, new_trader_data)

        self.informed_direction, self.informed_bought_ts, self.informed_sold_ts = self.check_for_informed()


    def get_orders(self):

        if self.wall_mid is not None:

            bid_price = self.bid_wall + 1  # default passive bid
            bid_volume = self.max_allowed_buy_volume

            # Olivia bought within the last 500ms: chase her — buy aggressively at ask_wall
            if self.informed_bought_ts is not None and self.informed_bought_ts + 5_00 >= self.state.timestamp:
                if self.initial_position < 40:
                    bid_price = self.ask_wall
                    bid_volume = 40 - self.initial_position

            else:
                # Spread is thin AND Olivia is SHORT: pull bid back to avoid
                # taking on inventory against an informed short signal
                if self.wall_mid - bid_price < 1 and (self.informed_direction == SHORT and self.initial_position > -40):
                    bid_price = self.bid_wall

            self.bid(bid_price, bid_volume)


            ask_price = self.ask_wall - 1  # default passive ask
            ask_volume = self.max_allowed_sell_volume

            # Olivia sold within the last 500ms: chase her — sell aggressively at bid_wall
            if self.informed_sold_ts is not None and self.informed_sold_ts + 5_00 >= self.state.timestamp:

                if self.initial_position > -40:
                    ask_price = self.bid_wall
                    ask_volume = 40 + self.initial_position

            # Spread is thin AND Olivia is LONG: pull ask back to avoid selling into strength
            if ask_price - self.wall_mid < 1 and (self.informed_direction == LONG and self.initial_position < 40):
                ask_price = self.ask_wall

            self.ask(ask_price, ask_volume)


        return {self.name: self.orders}



# ─────────────────────────────────────────────────────────────────────────────
# InkTrader — SQUID_INK
# Strategy: pure informed-trader following.
# No market-making at all — we only act on Olivia's signal.
# LONG signal  → target max long position, buy the gap at ask_wall
# SHORT signal → target max short position, sell the gap at bid_wall
# NEUTRAL      → do nothing (no orders placed)
# ─────────────────────────────────────────────────────────────────────────────
class InkTrader(ProductTrader):
    def __init__(self, state, prints, new_trader_data):
        super().__init__(INK_SYMBOL, state, prints, new_trader_data)

        self.informed_direction, _, _ = self.check_for_informed()


    def get_orders(self):

        # Target position based purely on Olivia's direction
        expected_position = 0
        if self.informed_direction == LONG:
            expected_position = self.position_limit
        elif self.informed_direction == SHORT:
            expected_position = -self.position_limit

        # Calculate how many units we still need to buy/sell to reach target
        remaining_volume = expected_position - self.initial_position

        if remaining_volume > 0 and self.ask_wall is not None:
            self.bid(self.ask_wall, remaining_volume)

        elif remaining_volume < 0 and self.bid_wall is not None:
            self.ask(self.bid_wall, -remaining_volume)

        return {self.name: self.orders}



# ─────────────────────────────────────────────────────────────────────────────
# EtfTrader — PICNIC_BASKET1 & PICNIC_BASKET2
# Strategy: ETF arbitrage between basket price and NAV of constituents.
#
# The spread = basket_price − (weighted sum of constituent prices)
# We track a running mean of this spread (the "premium") and trade when
# spread deviates more than BASKET_THRESHOLDS from its mean.
#
# Olivia's signal on CROISSANTS shifts the threshold so we don't fight her.
#
# Hedging: after taking a basket position, we partially hedge the delta by
# trading the non-informed constituents (JAMS, DJEMBES).
# ─────────────────────────────────────────────────────────────────────────────
class EtfTrader:
    def __init__(self, state, prints, new_trader_data):

        # One ProductTrader per basket and per constituent for order/book access
        self.baskets = [ProductTrader(s, state, prints, new_trader_data, product_group='ETF') for s in ETF_BASKET_SYMBOLS]
        self.informed_constituent = ProductTrader(ETF_INFORMED_CONSTITUENT, state, prints, new_trader_data, product_group='ETF')
        self.hedging_constituents = [ProductTrader(s, state, prints, new_trader_data, product_group='ETF') for s in ETF_CONSTITUENT_SYMBOLS if s != ETF_INFORMED_CONSTITUENT]

        self.state = state
        self.last_traderData = self.informed_constituent.last_traderData
        self.new_trader_data = new_trader_data

        # Compute current normalised spread for each basket
        self.spreads = self.calculate_spreads()
        # Check if Olivia is active on CROISSANTS (our sentiment indicator)
        self.informed_direction, _, _ = self.informed_constituent.check_for_informed()

    def calculate_spreads(self):
        return [self.calculate_spread(basket) for basket in self.baskets]

    def calculate_spread(self, basket):
        # Returns the basket's spread above/below its running mean premium.
        # Positive → basket is expensive relative to NAV → sell opportunity.
        # Negative → basket is cheap relative to NAV → buy opportunity.
        spread = None

        b_idx = ETF_BASKET_SYMBOLS.index(basket.name)

        try:

            constituents = [self.informed_constituent] + self.hedging_constituents
            # Sort constituents into the canonical order defined by ETF_CONSTITUENT_SYMBOLS
            const_prices = [const.wall_mid for const in constituents.sort(key=lambda c: {s: i for i, s in enumerate(ETF_CONSTITUENT_SYMBOLS)}[c.name])]

            # NAV = dot product of constituent mid-prices and their basket weights
            index_price = np.asarray(const_prices) @ np.asarray(ETF_CONSTITUENT_FACTORS[b_idx])
            etf_price = basket.wall_mid

            raw_spread = etf_price - index_price

            if CALCULATE_RUNNING_ETF_PREMIUM:
                # Online Welford-style mean update: tracks the historical average premium
                old_etf_mean_premium = self.last_traderData.get(f'ETF_{b_idx}_P', [INITIAL_ETF_PREMIUMS[b_idx], n_hist_samples])
                mean_premium, n = old_etf_mean_premium

                n += 1
                mean_premium += (raw_spread - mean_premium) / n  # incremental mean

                self.new_trader_data[f'ETF_{b_idx}_P'] = [mean_premium, n]

                try:
                    basket.log(f'ETF_{b_idx}_IDX', round(index_price, 2))
                    basket.log(f'ETF_{b_idx}_IDXP', round(index_price + mean_premium, 2))
                    basket.log(f'ETF_{b_idx}_SP', round(spread, 2))
                except: pass

            else:
                mean_premium = INITIAL_ETF_PREMIUMS[b_idx]

            # Normalised spread: how far current spread is from historical average
            spread = raw_spread - mean_premium

        except:
            old_etf_mean_premium = self.last_traderData.get(f'{basket.name[-1]}_P', [INITIAL_ETF_PREMIUMS[b_idx], n_hist_samples])
            self.new_trader_data[f'{basket.name[-1]}_P'] = old_etf_mean_premium


        return spread



    def get_basket_orders(self):

        out = {}

        for b_idx, basket in enumerate(self.baskets):

            if self.spreads[b_idx] is None: continue

            # Shift the threshold in Olivia's direction: if she's LONG on CROISSANTS,
            # constituents are likely rising so we require a bigger premium before
            # shorting the basket (and vice versa).
            informed_thr_adj = {
                LONG: ETF_THR_INFORMED_ADJS[b_idx],
                SHORT: -ETF_THR_INFORMED_ADJS[b_idx]
            }.get(self.informed_direction, 0)

            # Basket is expensive → sell it (short arb)
            if self.spreads[basket.name] > (BASKET_THRESHOLDS[b_idx] + informed_thr_adj) and basket.max_allowed_sell_volume > 0:
                basket.ask(basket.bid_wall, basket.max_allowed_sell_volume)
                basket.expected_position -= min(basket.total_mkt_sell_volume, basket.max_allowed_sell_volume)

            # Basket is cheap → buy it (long arb)
            elif self.spreads[basket.name] < (-BASKET_THRESHOLDS[b_idx] + informed_thr_adj) and basket.max_allowed_buy_volume > 0:
                basket.bid(basket.ask_wall, basket.max_allowed_buy_volume)
                basket.expected_position += min(basket.total_mkt_buy_volume, basket.max_allowed_buy_volume)

            # Spread has normalised — close any open position early
            elif ETF_CLOSE_AT_ZERO:

                if self.spreads[b_idx] > informed_thr_adj and basket.initial_position > 0:
                    basket.ask(basket.bid_wall, basket.initial_position)
                    basket.expected_position -= min(basket.total_mkt_sell_volume, basket.initial_position)

                elif self.spreads[b_idx] < informed_thr_adj and basket.initial_position < 0:
                    basket.bid(basket.ask_wall, -basket.initial_position)
                    basket.expected_position += min(basket.total_mkt_buy_volume, -basket.initial_position)

            out.update({basket.name: basket.orders})

        return out


    def get_constituent_orders(self):

        # ── INFORMED CONSTITUENT (CROISSANTS) ──
        # Follow Olivia's signal directly on CROISSANTS as well
        expected_position = {
            LONG: self.informed_constituent.position_limit,
            SHORT: -self.informed_constituent.position_limit
        }.get(self.informed_direction, 0)

        remaining_volume = expected_position - self.informed_constituent.initial_position

        if remaining_volume > 0:
            self.informed_constituent.bid(self.informed_constituent.ask_wall, remaining_volume)

        elif remaining_volume < 0:
            self.informed_constituent.ask(self.informed_constituent.bid_wall, -remaining_volume)

        out = {self.informed_constituent.name: self.informed_constituent.orders}

        # ── HEDGING CONSTITUENTS (JAMS, DJEMBES) ──
        # Partially neutralise the delta from our basket positions.
        # For each constituent: hedge_pos = −(sum over baskets of basket_pos × weight × hedge_factor)
        for hedging_constituent in self.hedging_constituents:

            expected_hedge_position = 0
            for b_idx, basket in enumerate(self.baskets):
                etf_const_factor = ETF_CONSTITUENT_FACTORS[b_idx][ETF_CONSTITUENT_SYMBOLS.index(hedging_constituent.name)]
                expected_hedge_position += -basket.expected_position * etf_const_factor * ETF_HEDGE_FACTOR

            remaining_volume = round(expected_hedge_position - hedging_constituent.initial_position)

            if remaining_volume > 0:
                hedging_constituent.bid(hedging_constituent.ask_wall, remaining_volume)

            elif remaining_volume < 0:
                hedging_constituent.ask(hedging_constituent.bid_wall, -remaining_volume)

            out[hedging_constituent.name] = hedging_constituent.orders


        return out


    def get_orders(self):

        orders = {
             # Basket orders first so expected_position is updated before hedging
            **self.get_basket_orders(),
            **self.get_constituent_orders()
        }

        return orders


# ─────────────────────────────────────────────────────────────────────────────
# OptionTrader — VOLCANIC_ROCK options (5 strikes: 9500–10500)
# Strategy: Black-Scholes theoretical pricing with two sub-strategies:
#
#   1. IV Scalping (strikes 9750–10500):
#      Track a running EMA of each option's deviation from its BS theo price.
#      When the current deviation diverges from its mean beyond THR_OPEN, trade.
#      When the market regime is low-vol (switch_mean < IV_SCALPING_THR), flatten.
#
#   2. Mean Reversion (strike 9500 only):
#      Combine the underlying's EMA deviation with the IV deviation.
#      Trade when the combined signal exceeds options_mean_reversion_thr.
#
#   Underlying (VOLCANIC_ROCK):
#      Trade when price deviates from its short-term EMA by more than
#      underlying_mean_reversion_thr. Acts as a delta hedge.
# ─────────────────────────────────────────────────────────────────────────────
class OptionTrader:
    def __init__(self, state, prints, new_trader_data):

        self.options = [ProductTrader(os, state, prints, new_trader_data, product_group='OPTION') for os in OPTION_SYMBOLS]
        self.underlying = ProductTrader(OPTION_UNDERLYING_SYMBOL, state, prints, new_trader_data, product_group='OPTION')

        self.state = state
        self.last_traderData = self.underlying.last_traderData
        self.new_trader_data = new_trader_data

        # Pre-compute all signals used by the two sub-strategies
        self.indicators = self.calculate_indicators()


    def get_option_values(self, S, K, TTE):
        # Black-Scholes call price, delta, and vega for a given:
        #   S   = underlying spot price
        #   K   = strike price
        #   TTE = time to expiry in years

        def bs_call(S, K, TTE, s, r=0):
            # Standard BS call formula; returns (price, delta)
            d1 = (math.log(S/K) + (r + 0.5 * s**2) * TTE) / (s * TTE**0.5)
            d2 = d1 - s * TTE**0.5
            return S * _N.cdf(d1) - K * math.exp(-r * TTE) * _N.cdf(d2), _N.cdf(d1)

        def bs_vega(S, K, TTE, s, r=0):
            # Vega = sensitivity of option price to a change in implied volatility
            d1 = d1 = (math.log(S/K) + (r + 0.5*s**2) * TTE) / (s * TTE**0.5)
            return S * _N.pdf(d1) * TTE**0.5

        def get_iv(St, K, TTE):
            # Implied volatility from a pre-fitted quadratic "vol smile" as a
            # function of log-moneyness scaled by sqrt(TTE).
            # Coefficients were fit to historical data offline.
            m_t_k = np.log(K/St) / TTE**0.5
            coeffs = [0.27362531, 0.01007566, 0.14876677] # from the fitted vol smile
            iv = np.poly1d(coeffs)(m_t_k)
            return iv

        iv = get_iv(S, K, TTE)
        bs_call_value, delta = bs_call(S, K, TTE, iv)
        vega = bs_vega(S, K, TTE, iv)
        return bs_call_value, delta, vega


    def calculate_ema(self, td_key, window, value):
        # Exponential moving average stored in traderData across ticks.
        # alpha = 2/(window+1) is the standard EMA smoothing factor.
        old_mean = self.last_traderData.get(td_key, 0)
        alpha = 2/(window+1)
        new_mean = alpha * value + (1 - alpha) * old_mean
        self.new_trader_data[td_key] = new_mean

        return new_mean



    def calculate_indicators(self):
        # Compute all signals needed for trading decisions this tick.
        # Results stored in a dict so each sub-strategy can read what it needs.
        indicators = {
            'ema_u_dev': None,           # underlying deviation from short EMA (for MR on underlying)
            'ema_o_dev': None,           # underlying deviation from long EMA (for MR on options)
            'mean_theo_diffs': {},       # per-option EMA of (market_mid − BS_theo)
            'current_theo_diffs': {},    # per-option current (market_mid − BS_theo)
            'switch_means': {},          # per-option EMA of |theo_diff − mean_theo_diff| (regime detector)
            'deltas': {},                # per-option BS delta
            'vegas': {},                 # per-option BS vega
        }


        if self.underlying.wall_mid is not None:

            # Short EMA of underlying price → used for underlying MR signal
            new_mean_price = self.calculate_ema('ema_u', underlying_mean_reversion_window, self.underlying.wall_mid)
            indicators['ema_u_dev'] = self.underlying.wall_mid - new_mean_price

            # Long EMA of underlying price → used for options MR signal (slower)
            new_mean_price = self.calculate_ema('ema_o', options_mean_reversion_window, self.underlying.wall_mid)
            indicators['ema_o_dev'] = self.underlying.wall_mid - new_mean_price


            for option in self.options:

                k = int(option.name.split('_')[-1])  # extract strike from symbol name

                # If only one side of the book exists, synthesise a midpoint
                if option.wall_mid is None:
                    if option.ask_wall is not None:
                        option.wall_mid = option.ask_wall - 0.5
                        option.bid_wall = option.ask_wall - 1
                        option.best_bid = option.ask_wall - 1
                    elif option.bid_wall is not None:
                        option.wall_mid = option.bid_wall + 0.5
                        option.ask_wall = option.bid_wall + 1
                        option.best_ask = option.bid_wall + 1


                if option.wall_mid is not None:

                    # Time to expiry: DAY + fractional day from timestamp, converted to years
                    tte = 1 - (DAYS_PER_YEAR - 8 + DAY + self.state.timestamp // 100 / 10_000) / DAYS_PER_YEAR
                    underlying = self.underlying.best_bid * 0.5 + self.underlying.best_ask * 0.5
                    option_theo, option_delta, option_vega = self.get_option_values(underlying, k, tte)
                    # Positive diff → market is pricing this option above theo (expensive)
                    option_theo_diff = option.wall_mid - option_theo

                    indicators['current_theo_diffs'][option.name] = option_theo_diff
                    indicators['deltas'][option.name] = option_delta
                    indicators['vegas'][option.name] = option_vega

                    # EMA of the theo diff: tracks the option's persistent mispricing level
                    new_mean_diff = self.calculate_ema(f'{option.name}_theo_diff', THEO_NORM_WINDOW, option_theo_diff)
                    indicators['mean_theo_diffs'][option.name] = new_mean_diff

                    # EMA of absolute deviation from mean: measures how volatile the spread is.
                    # High value → big swings → IV scalping is profitable here.
                    new_mean_avg_dev = self.calculate_ema(f'{option.name}_avg_devs', IV_SCALPING_WINDOW, abs(option_theo_diff - new_mean_diff))
                    indicators['switch_means'][option.name] = new_mean_avg_dev

        return indicators


    def get_iv_scalping_orders(self, options):
        # For each option: if the market is spread-volatile enough (switch_mean ≥ IV_SCALPING_THR),
        # sell when the option is expensive vs. its mean theo level, buy when cheap.
        # If regime switches to low-vol, flatten any open positions immediately.
        out = {}

        for option in options:

            if option.name in self.indicators['mean_theo_diffs'] and option.name in self.indicators['current_theo_diffs'] and option.name in self.new_switch_mean:

                if self.new_switch_mean[option.name] >= IV_SCALPING_THR:

                    current_theo_diff = self.indicators['current_theo_diffs'][option.name]
                    mean_theo_diff = self.indicators['mean_theo_diffs'][option.name]

                    # Low-vega options are harder to price accurately → widen threshold
                    low_vega_adj = 0
                    if self.vegas.get(option.name, 0) <= 1:
                        low_vega_adj = LOW_VEGA_THR_ADJ

                    # Option is rich (above mean): sell to open or sell to close a long
                    if current_theo_diff - option.wall_mid + option.best_bid - mean_theo_diff >= (THR_OPEN + low_vega_adj) and option.max_allowed_sell_volume > 0:
                        option.ask(option.best_bid, option.max_allowed_sell_volume)

                    if current_theo_diff - option.wall_mid + option.best_bid - mean_theo_diff >= THR_CLOSE and option.initial_position > 0:
                        option.ask(option.best_bid, option.initial_position)

                    # Option is cheap (below mean): buy to open or buy to close a short
                    elif current_theo_diff - option.wall_mid + option.best_ask - mean_theo_diff <= -(THR_OPEN + low_vega_adj) and option.max_allowed_buy_volume > 0:
                        option.bid(option.best_ask, option.max_allowed_buy_volume)

                    if current_theo_diff - option.wall_mid + option.best_ask - mean_theo_diff <= -THR_CLOSE and option.initial_position < 0:
                        option.bid(option.best_ask, -option.initial_position)

                else:
                    # Low-vol regime: no new positions, flatten existing ones
                    if option.initial_position > 0:
                        option.ask(option.best_bid, option.initial_position)
                    elif option.initial_position < 0:
                        option.bid(option.best_ask, -option.initial_position)


            out[option.name] = option.orders

        return out

    def get_mr_orders(self, options):
        # Mean-reversion sub-strategy (used for the deep-OTM 9500 strike).
        # Combined signal = underlying EMA deviation + option's IV deviation.
        # Trade when combined signal is large enough to suggest overextension.
        out = {}

        for option in options:

            if option.name in self.indicators['current_theo_diffs'] and option.name in self.indicators['mean_theo_diffs'] and self.indicators.get('ema_o_dev') is not None:

                # Start from underlying price deviation
                current_deviation = self.indicators['ema_o_dev']

                # Add IV component: how much the option's spread has moved vs. its own mean
                iv_deviation = self.indicators['current_theo_diffs'][option.name] - self.indicators['mean_theo_diffs'][option.name]
                current_deviation += iv_deviation

                # Sell when combined signal says market has moved too far up
                if current_deviation > options_mean_reversion_thr and option.max_allowed_sell_volume > 0:
                    option.ask(option.best_bid, option.max_allowed_sell_volume)

                # Buy when combined signal says market has moved too far down
                elif current_deviation < -options_mean_reversion_thr and option.max_allowed_buy_volume > 0:
                    option.bid(option.best_ask, option.max_allowed_buy_volume)

                out[option.name] = option.orders

        return out


    def get_option_orders(self):
        # Skip the first few ticks until EMAs have had time to warm up
        if self.state.timestamp / 100 < min([THEO_NORM_WINDOW, underlying_mean_reversion_window, options_mean_reversion_window]): return {}

        # Apply different strategies to different strikes
        iv_scalping_options = [o for o in self.options if int(o.name.split('_')[-1]) >= 9750]  # ATM/OTM
        mr_options = [o for o in self.options if o.name.endswith('9500')]                        # deep ITM/OTM

        out = {
            **self.get_iv_scalping_orders(iv_scalping_options),
            **self.get_mr_orders(mr_options)
        }

        return out


    def get_underlying_orders(self):
        # Trade VOLCANIC_ROCK as a mean-reversion strategy and delta hedge.
        # Sell when price is too far above its short EMA, buy when too far below.
        if self.state.timestamp / 100 < underlying_mean_reversion_window: return {}

        if self.indicators.get('ema_u_dev') is not None:

            current_deviation = self.indicators['ema_o_dev']

            if current_deviation > underlying_mean_reversion_thr and self.underlying.max_allowed_sell_volume > 0:
                self.underlying.ask(self.underlying.bid_wall + 1, self.underlying.max_allowed_sell_volume)

            elif current_deviation < -underlying_mean_reversion_thr and self.underlying.max_allowed_buy_volume > 0:
                self.underlying.bid(self.underlying.ask_wall - 1, self.underlying.max_allowed_buy_volume)


        return {self.underlying.name: self.underlying.orders}


    def get_orders(self):

        orders = {
            **self.get_option_orders(),   # options first so delta exposure is known
            **self.get_underlying_orders()  # then hedge with underlying
        }

        return orders


# ─────────────────────────────────────────────────────────────────────────────
# CommodityTrader — MAGNIFICENT_MACARONS
# Strategy: cross-venue arbitrage using the platform's conversion mechanism.
#
# There is a local exchange (order book) and an external exchange (observations).
# We can convert between venues subject to import/export tariffs + transport fees.
#
# Two arb directions:
#   Short arb: sell locally at a high price, convert position to external (import)
#              Profit = local_sell_price − (ex_ask + import_tariff + transport)
#
#   Long arb:  buy externally via conversion (export), sell at local ask
#              Profit = (ex_bid − export_tariff − transport) − local_buy_price
#
# We only trade when both the current AND historical average arb are positive
# (avoids acting on one-tick spikes).
# At end of tick: always convert our full position back to flatten inventory.
# ─────────────────────────────────────────────────────────────────────────────
class CommodityTrader(ProductTrader):
    def __init__(self, state, prints, new_trader_data):
        super().__init__(COMMODITY_SYMBOL, state, prints, new_trader_data)

        self.conversions = 0


    def get_orders(self):

        conv_obs = self.state.observations.conversionObservations[self.name]

        # Raw external prices and friction costs
        ex_raw_bid, ex_raw_ask = conv_obs.bidPrice, conv_obs.askPrice
        transport_fees = conv_obs.transportFees
        export_tariff = conv_obs.exportTariff
        import_tariff = conv_obs.importTariff
        sunlight = conv_obs.sunlightIndex
        sugarPrice = conv_obs.sugarPrice

        # Effective local prices we'd quote (rounded to integer ticks)
        local_sell_price = math.floor(ex_raw_bid + 0.5)
        local_buy_price = math.ceil(ex_raw_ask - 0.5)

        # All-in external costs: what we'd actually pay/receive after fees
        ex_ask = (ex_raw_ask + import_tariff + transport_fees)   # cost to import (buy externally)
        ex_bid = (ex_raw_bid - export_tariff - transport_fees)   # proceeds from export (sell externally)

        # Arb profit per unit in each direction
        short_arbitrage = round(local_sell_price - ex_ask, 1)   # sell local, convert out
        long_arbitrage = round(ex_bid - local_buy_price - 0.1, 1)  # convert in, sell local

        # Rolling history (last 10 ticks) to filter noisy one-off arb readings
        short_arbs_hist = self.last_traderData.get('SA', [])
        long_arbs_hist = self.last_traderData.get('LA', [])

        if len(short_arbs_hist) > 10:
            short_arbs_hist.pop(0)
            long_arbs_hist.pop(0)

        short_arbs_hist.append(short_arbitrage)
        long_arbs_hist.append(long_arbitrage)

        self.new_trader_data['SA'] = short_arbs_hist
        self.new_trader_data['LA'] = long_arbs_hist

        mean_short_arb_hist = np.mean(short_arbs_hist)
        mean_long_arb_hist = np.mean(long_arbs_hist)

        # Only trade when the better arb is positive AND historically stable
        if short_arbitrage > long_arbitrage:

            if short_arbitrage >= 0 and mean_short_arb_hist > 0:

                remaining_volume = CONVERSION_LIMIT

                # Walk through local buy orders and take any that still leave us
                # with at least 58% of the full arb profit (price-walks the book)
                for bp, bv in self.mkt_buy_orders.items():

                    if (short_arbitrage - (local_sell_price - bp)) > (0.58 * short_arbitrage):
                        v = min(remaining_volume, bv)
                        self.ask(bp, v)
                        remaining_volume -= v
                    else:
                        break

                # Any remaining capacity: post at the target sell price
                if remaining_volume > 0:
                    self.ask(local_sell_price, remaining_volume)

        else:

            if long_arbitrage >= 0 and mean_long_arb_hist > 0:

                remaining_volume = CONVERSION_LIMIT

                # Walk through local sell orders and lift any that still leave ≥58% profit
                for ap, av in self.mkt_sell_orders.items():

                    if (long_arbitrage - (ap - local_buy_price)) > (0.58 * long_arbitrage):
                        v = min(remaining_volume, av)
                        self.bid(ap, v)
                        remaining_volume -= v
                    else:
                        break

                if remaining_volume > 0:
                    self.bid(local_buy_price, remaining_volume)


        # Convert our entire position back to neutral via the external venue.
        # Positive initial_position → we're long → convert out (negative conversion).
        # The platform then settles these as external trades next tick.
        self.conversions = max(min(-self.initial_position, CONVERSION_LIMIT), -CONVERSION_LIMIT)


        self.log('BID', ex_raw_bid)
        self.log('ASK', ex_raw_ask)
        self.log('IMEXT', [import_tariff, export_tariff, transport_fees])
        self.log('SUN_S', [sunlight, sugarPrice])

        self.log('ARBS', [long_arbitrage, short_arbitrage])
        self.log('M_ARBS', [round(mean_long_arb_hist, 2), round(mean_short_arb_hist, 2)])

        self.log('MKT_BPs', list(self.mkt_buy_orders.keys()))
        self.log('MKT_BVs', list(self.mkt_buy_orders.values()))
        self.log('MKT_APs', list(self.mkt_sell_orders.keys()))
        self.log('MKT_AVs', list(self.mkt_sell_orders.values()))

        return {self.name: self.orders}

    def get_conversions(self):
        self.log('CONVERTING', self.conversions)
        return self.conversions



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
            INK_SYMBOL: InkTrader,
            ETF_BASKET_SYMBOLS[0]: EtfTrader,
            OPTION_UNDERLYING_SYMBOL: OptionTrader,
            COMMODITY_SYMBOL: CommodityTrader,
        }

        result, conversions = {}, 0
        for symbol, product_trader in product_traders.items():
            # Only run a trader if market data exists for its symbol this tick
            if symbol in state.order_depths:

                try:
                    trader = product_trader(state, prints, new_trader_data)
                    result.update(trader.get_orders())

                    if symbol == COMMODITY_SYMBOL:
                        conversions = trader.get_conversions()
                except: pass


        # Serialise persistent state for next tick
        try: final_trader_data = json.dumps(new_trader_data)
        except: final_trader_data = ''

        try: logger.print(json.dumps(prints))
        except: pass

        logger.flush(state, result, conversions, final_trader_data)
        return result, conversions, final_trader_data
