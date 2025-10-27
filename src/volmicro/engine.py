# src/volmicro/engine.py
import logging
from typing import Iterable, Protocol
from .core import Bar
from .portfolio import Portfolio

logger = logging.getLogger(__name__)

class Strategy(Protocol):
    def on_bar(self, bar: Bar, portfolio: Portfolio) -> None: ...

def run_engine(bars: Iterable[Bar], portfolio: Portfolio, strategy: Strategy) -> Portfolio:
    for i, bar in enumerate(bars, start=1):
        # MTM con el close de la barra actual
        portfolio.mark_to_market(bar.close)

        # Logging por barra (antes de ejecutar la estrategia)
        logger.info(
            "[%s] %s i=%d close=%.2f cash=%.2f qty=%.6f equity=%.2f",
            str(bar.ts), bar.symbol, i, bar.close, portfolio.cash, portfolio.qty, portfolio.equity()
        )

        # Ejecutar la estrategia en esta barra
        strategy.on_bar(bar, portfolio)

        # (opcional) Logging después por si la estrategia movió algo
        logger.debug(
            "POST on_bar -> cash=%.2f qty=%.6f equity=%.2f",
            portfolio.cash, portfolio.qty, portfolio.equity()
        )

    return portfolio
