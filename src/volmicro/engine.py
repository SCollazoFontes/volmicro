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
        # MTM con el close de la barra
        portfolio.mark_to_market(bar.close)

        # Log previo
        logger.info(
            "[%s] %s i=%d close=%.2f cash=%.2f qty=%.6f equity=%.2f",
            str(bar.ts), bar.symbol, i, bar.close, portfolio.cash, portfolio.qty, portfolio.equity()
        )

        # Ejecutar la estrategia
        strategy.on_bar(bar, portfolio)

        # Log posterior (solo en DEBUG para no saturar)
        logger.debug(
            "POST on_bar -> cash=%.2f qty=%.6f equity=%.2f avg_price=%.2f realized=%.2f",
            portfolio.cash, portfolio.qty, portfolio.equity(), portfolio.avg_price, portfolio.realized_pnl
        )

    if hasattr(strategy, "on_finish"):
        strategy.on_finish(portfolio)

    return portfolio
