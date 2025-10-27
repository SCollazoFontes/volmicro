# src/volmicro/engine.py
from typing import Callable, Iterable
from .core import Bar

# src/volmicro/engine.py
from .portfolio import Portfolio

def run(iter_bars, strategy, cash_init: float = 10_000.0):
    """
    iter_bars: iterable/generador de Bar (tu iter_bars() actual o similar)
    strategy:  objeto con on_start(portfolio) y on_bar(bar, portfolio)
    """
    portfolio = Portfolio(cash=cash_init)

    # hook opcional al inicio
    if hasattr(strategy, "on_start"):
        strategy.on_start(portfolio)

    for bar in iter_bars:
        # marcamos precio para tener equity actualizado
        portfolio.mark(bar.close)

        # pasamos el control a la estrategia
        strategy.on_bar(bar, portfolio)

        # (opcional) imprime un rastro muy corto
        # print(f"{bar.ts}  price={bar.close:.2f} cash={portfolio.cash:.2f} qty={portfolio.qty:.6f} equity={portfolio.equity:.2f}")

    return portfolio  # por si quieres inspeccionar al final
