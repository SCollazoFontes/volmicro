# src/volmicro/engine.py
from __future__ import annotations
import logging
from typing import Iterable
from .core import Bar
from .portfolio import Portfolio

logger = logging.getLogger(__name__)

def run_engine(
    bars: Iterable[Bar],
    portfolio: Portfolio,
    strategy,
    log_every: int = 10
) -> Portfolio:
    equity_curve = []
    last_bar: Bar | None = None

    for i, bar in enumerate(bars, start=1):
        last_bar = bar

        # mark-to-market con el close de la barra
        portfolio.mark_to_market(bar.close)

        # guardar punto en la curva de equity
        equity_curve.append((bar.ts, portfolio.equity()))

        # logging controlado
        if i == 1 or (log_every and i % log_every == 0):
            logger.info("[%s] %s i=%d close=%.2f cash=%.2f qty=%.6f equity=%.2f",
                        str(bar.ts), bar.symbol, i, bar.close, portfolio.cash, portfolio.qty, portfolio.equity())
        else:
            logger.debug("[%s] %s i=%d close=%.2f cash=%.2f qty=%.6f equity=%.2f",
                         str(bar.ts), bar.symbol, i, bar.close, portfolio.cash, portfolio.qty, portfolio.equity())

        # estrategia
        strategy.on_bar(bar, portfolio)

    # hook de cierre
    if hasattr(strategy, "on_finish"):
        strategy.on_finish(portfolio)

        # si la estrategia cerró en on_finish, reflejamos el equity final
        if last_bar is not None:
            equity_curve.append((last_bar.ts, portfolio.equity()))

    # deja la curva disponible en el portfolio
    portfolio._equity_curve = equity_curve

    if last_bar is not None:
        last_equity = portfolio.equity()
        if not equity_curve or equity_curve[-1][1] != last_equity:
            equity_curve.append((last_bar.ts, last_equity))

    return portfolio
