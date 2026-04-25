"""Baseline = StaticTrader only (no arb, no options). For PnL attribution."""

import json

from datamodel import Order, TradingState
from trader_r3 import (
    Logger,
    StaticTrader,
    HYDROGEL_SYMBOL,
    VELVET_SYMBOL,
    logger,
)


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

        for sym in (HYDROGEL_SYMBOL, VELVET_SYMBOL):
            if sym in state.order_depths:
                try:
                    t = StaticTrader(sym, state, prints, new_trader_data)
                    result.update(t.get_orders())
                except Exception as e:
                    logger.print(f"err static {sym}: {e}")

        try:
            final_trader_data = json.dumps(new_trader_data)
        except Exception:
            final_trader_data = ''

        try:
            logger.print(json.dumps(prints))
        except Exception:
            pass

        logger.flush(state, result, 0, final_trader_data)
        return result, 0, final_trader_data
