# src/volmicro/engine.py
"""
Motor (engine) del backtest.

Responsabilidad
---------------
Recorrer una secuencia de barras (iterable de `Bar`) y, para cada una:
1) Marcar a mercado la cartera con el precio de cierre de la barra (mark-to-market).
2) Registrar un punto de la **equity curve** (timestamp, equity).
3) Invocar la lógica de la **estrategia**: `strategy.on_bar(bar, portfolio)`,
   la cual puede decidir comprar o vender usando la API del `Portfolio`.

Al finalizar:
- Si la estrategia implementa `on_finish(portfolio)`, se llama una vez.
- Se asegura que la equity curve termina con un punto actualizado al **equity final**.

Interfaz
--------
run_engine(
    bars: Iterable[Bar],
    portfolio: Portfolio,
    strategy: Any,          # cualquier objeto con .on_bar(bar, portfolio) y opcional .on_finish(portfolio)
    log_every: int = 10     # cada cuántas barras se loguea una línea en nivel INFO (0 = sólo la primera)
) -> Portfolio

Notas de implementación
-----------------------
- No acopla la obtención de datos: recibe `bars` ya listos (p.ej. desde binance_feed.iter_bars).
- No acopla la estrategia: sólo exige la presencia de `on_bar`. `on_finish` es opcional.
- Deja la equity curve accesible dentro de `Portfolio` vía el atributo `_equity_curve`
  para posteriores exportaciones (`portfolio.equity_curve_dataframe()`).

Detalles de logging
-------------------
- Si `portfolio` tiene un atributo `run_id`, se usa como prefijo para facilitar la trazabilidad.
- Se loguea la primera barra siempre, y luego cada `log_every` (si `log_every > 0`).
- El nivel DEBUG incluye todos los mensajes si el logger está configurado a DEBUG.
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional, List, Tuple

from .core import Bar
from .portfolio import Portfolio

logger = logging.getLogger(__name__)


def run_engine(
    bars: Iterable[Bar],
    portfolio: Portfolio,
    strategy,
    log_every: int = 10,
) -> Portfolio:
    """
    Ejecuta el loop principal del backtest barra a barra.

    Parámetros
    ----------
    bars : Iterable[Bar]
        Secuencia de barras (ordenadas temporalmente) a procesar.
    portfolio : Portfolio
        Cartera sobre la que se marcará a mercado y se ejecutarán órdenes.
    strategy : Any
        Objeto con método `on_bar(bar, portfolio)` y opcional `on_finish(portfolio)`.
    log_every : int, default 10
        Frecuencia de logging en INFO (0 => sólo primera barra; DEBUG muestra todo).

    Devuelve
    --------
    Portfolio
        La misma instancia `portfolio`, mutada, con:
          - trades registrados
          - equity curve almacenada en `portfolio._equity_curve`
          - estado final coherente (cash, qty, avg_price, realized_pnl, last_price, etc.)
    """
    # Equity curve en memoria (lista de tuplas: (timestamp, equity))
    equity_curve: List[Tuple[object, float]] = []
    last_bar: Optional[Bar] = None

    # Prefijo de trazabilidad si el Portfolio trae run_id (útil en logs/CSV)
    run_id = getattr(portfolio, "run_id", None)
    log_prefix = f"[run:{run_id}] " if run_id else ""

    # Bucle principal sobre las barras
    for i, bar in enumerate(bars, start=1):
        last_bar = bar  # mantenemos referencia a la última barra vista

        # 1) Mark-to-market con el cierre de la barra
        #    Esto actualiza `last_price` en la cartera; equity() reflejará ese precio.
        portfolio.mark_to_market(bar.close)

        # 2) Registrar un punto de equity curve (tras MTM de esta barra)
        equity_now = portfolio.equity()
        equity_curve.append((bar.ts, equity_now))

        # 3) Logging controlado: INFO sólo de forma espaciada; DEBUG siempre detallado
        #    Mensaje con estado útil: i, close, cash, qty y equity
        msg = (
            f"{log_prefix}[{bar.ts}] {bar.symbol} i={i} "
            f"close={bar.close:.8f} cash={portfolio.cash:.2f} "
            f"qty={portfolio.qty:.8f} equity={equity_now:.2f}"
        )
        if i == 1 or (log_every and log_every > 0 and i % log_every == 0):
            logger.info(msg)
        else:
            logger.debug(msg)

        # 4) Invocar la estrategia en esta barra
        #    La estrategia puede lanzar excepciones (errores lógicos propios);
        #    las dejamos propagar para no ocultar fallos. Si quisieras
        #    seguir pese a fallos, aquí podrías envolver con try/except y loggear.
        strategy.on_bar(bar, portfolio)

        # (Opcional) Si quisieras registrar equity inmediatamente después de la acción
        # de estrategia, podrías añadir otro punto aquí. Por simplicidad, y para no
        # duplicar puntos, lo dejamos sólo tras el MTM previo.

    # Hook de cierre de la estrategia, si existe
    if hasattr(strategy, "on_finish"):
        strategy.on_finish(portfolio)

    # Almacenamos la equity curve en el portfolio para exportaciones posteriores.
    # Nota: puede haber cambiado el equity tras on_finish (por ejemplo, cierre de posición),
    # por lo que aseguramos un último punto consistente al final.
    portfolio._equity_curve = equity_curve

    # Asegurar que la curva termina en el equity final exacto
    if last_bar is not None:
        last_equity = portfolio.equity()
        # Si la lista está vacía (no debería) o el último equity difiere, empujamos el punto final.
        if not equity_curve or equity_curve[-1][1] != last_equity:
            equity_curve.append((last_bar.ts, last_equity))

    return portfolio
