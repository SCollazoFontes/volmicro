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
    """
    Ejecuta el loop de backtesting barra a barra.

    - Marca a mercado con el close de cada barra.
    - Llama a la estrategia con on_bar(bar, portfolio).
    - Registra puntos de la curva de equity.
    - Al finalizar, ejecuta on_finish(portfolio) si existe y añade el último punto de equity.
    """
    equity_curve = []
    last_bar: Bar | None = None

    # Prefijo de logging con run_id si está disponible
    run_id = getattr(portfolio, "run_id", None)
    log_prefix = f"[run:{run_id}] " if run_id else ""

    for i, bar in enumerate(bars, start=1):
        last_bar = bar

        # mark-to-market con el close de la barra
        portfolio.mark_to_market(bar.close)

        # guardar punto en la curva de equity
        equity_curve.append((bar.ts, portfolio.equity()))

        # logging controlado
        msg = (
            f"{log_prefix}[{bar.ts}] {bar.symbol} i={i} "
            f"close={bar.close:.2f} cash={portfolio.cash:.2f} "
            f"qty={portfolio.qty:.6f} equity={portfolio.equity():.2f}"
        )
        if i == 1 or (log_every and i % log_every == 0):
            logger.info(msg)
        else:
            logger.debug(msg)

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

    # asegura que el último punto de equity figure en la curva
    if last_bar is not None:
        last_equity = portfolio.equity()
        if not equity_curve or equity_curve[-1][1] != last_equity:
            equity_curve.append((last_bar.ts, last_equity))

    return portfolio
