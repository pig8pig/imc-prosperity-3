"""Backtest harness that runs StaticTrader + StaticArbScanner + OptionTrader.

Phase 5 gate: prosperity4btest cli combined_trader.py 3-0 3-1 3-2
"""

import json

from datamodel import Order, TradingState
from trader_r3 import (
    Logger,
    ProductTrader,
    StaticTrader,
    StaticArbScanner,
    HYDROGEL_SYMBOL,
    VELVET_SYMBOL,
    VOUCHER_SYMBOLS,
    logger,
)
from phase5_smile_trader import OptionTrader


class Trader:

    def run(self, state: TradingState):
        result: dict[str, list[Order]] = {}
        new_trader_data: dict = {}
        prints: dict = {
            "GENERAL": {
                "TIMESTAMP": state.timestamp,
                "POSITIONS": state.position,
            },
        }
        conversions = 0

        # 1. Static market making (HYDROGEL_PACK + VELVETFRUIT_EXTRACT)
        for sym in (HYDROGEL_SYMBOL, VELVET_SYMBOL):
            if sym in state.order_depths:
                try:
                    t = StaticTrader(sym, state, prints, new_trader_data)
                    result.update(t.get_orders())
                except Exception as e:
                    logger.print(f"err static {sym}: {e}")

        # 2. Static arb scanner — runs first to claim model-free edges
        try:
            arb = StaticArbScanner(state, prints)
            for sym, ords in arb.get_orders().items():
                if ords:
                    result.setdefault(sym, []).extend(ords)
        except Exception as e:
            logger.print(f"err arb: {e}")

        # 3. Smile-deviation OptionTrader (primary alpha source)
        try:
            opt = OptionTrader(state, prints, new_trader_data)
            for sym, ords in opt.get_orders().items():
                if ords:
                    result.setdefault(sym, []).extend(ords)
        except Exception as e:
            logger.print(f"err opt: {e}")

        try:
            final_trader_data = json.dumps(new_trader_data)
        except Exception:
            final_trader_data = ''

        try:
            logger.print(json.dumps(prints))
        except Exception:
            pass

        logger.flush(state, result, conversions, final_trader_data)
        return result, conversions, final_trader_data
