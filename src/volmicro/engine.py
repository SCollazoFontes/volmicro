# src/volmicro/engine.py
"""
Motor (engine) del backtest.

Responsabilidad
---------------
Recorrer una secuencia de barras (iterable de `Bar`) y, para cada una:
1) Marcar a mercado la cartera con el precio de cierre de la barra
   (mark-to-market).
2) Registrar un punto de la **equity curve** (timestamp, equity).
3) Invocar la lógica de la **estrategia**:
   `strategy.on_bar(bar, portfolio)`, la cual puede decidir comprar o vender
   usando la API del `Portfolio`.

Al finalizar:
- Si la estrategia implementa `on_finish(portfolio)` o `on_end(...)`, se llama.
- Se asegura que la equity curve termina con un punto actualizado al equity
  final.
- Si el `Portfolio` define `reports_dir` (ruta), se exportan:
    - reports_dir/equity_curve.csv  (siempre, a partir de los datos internos)
    - reports_dir/trades.csv        (si hay datos de trades accesibles)

Interfaz
--------
run_engine(
    bars: Iterable[Bar],
    portfolio: Portfolio,
    strategy: Any,  # objeto con .on_bar(bar, portfolio) y opcional .on_finish/.on_end
    log_every: int = 10
) -> Portfolio

Notas de diseño
---------------
- No acopla la obtención de datos: recibe `bars` ya listos (p.ej. desde
  binance_feed.iter_bars).
- No acopla la estrategia: sólo exige `on_bar`. `on_finish`/`on_end` son
  opcionales.
- Guarda la equity curve en memoria y la exporta si `portfolio.reports_dir`
  está definido.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .core import Bar
from .portfolio import Portfolio

logger = logging.getLogger(__name__)


def run_engine(
    bars: Iterable[Bar],
    portfolio: Portfolio,
    strategy: Any,
    log_every: int = 10,
) -> Portfolio:
    """
    Ejecuta el loop principal del backtest barra a barra.
    """
    # Equity curve en memoria: lista de tuplas (timestamp, equity).
    # El tipo de timestamp lo define Bar.ts (p. ej. int(ms) o datetime).
    equity_curve: list[tuple[datetime, float]] = []
    last_bar: Bar | None = None

    # Prefijo de trazabilidad si el Portfolio trae run_id (útil en logs/CSV)
    run_id = getattr(portfolio, "run_id", None)
    log_prefix = f"[run:{run_id}] " if run_id else ""

    # Bucle principal sobre las barras
    for i, bar in enumerate(bars, start=1):
        last_bar = bar  # mantenemos referencia a la última barra vista

        # 1) Mark-to-market con el cierre de la barra
        portfolio.mark_to_market(bar.close)

        # 2) Registrar un punto de equity curve (tras MTM de esta barra)
        equity_now = portfolio.equity()
        equity_curve.append((bar.ts, equity_now))

        # 3) Logging controlado
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
        strategy.on_bar(bar, portfolio)

    # Hooks de cierre de la estrategia, si existen
    on_finish = getattr(strategy, "on_finish", None)
    if callable(on_finish):
        try:
            on_finish(portfolio)
        except Exception:
            logger.exception("%sError en strategy.on_finish()", log_prefix)
            raise

    on_end = getattr(strategy, "on_end", None)
    if callable(on_end):
        try:
            on_end(len(equity_curve), last_bar, portfolio)
        except Exception:
            logger.exception("%sError en strategy.on_end()", log_prefix)
            raise

    # Guardar equity curve en portfolio y asegurar último punto coherente
    portfolio._equity_curve = equity_curve  # expuesto intencionalmente

    if last_bar is not None:
        final_equity = portfolio.equity()
        if not equity_curve or equity_curve[-1][1] != final_equity:
            equity_curve.append((last_bar.ts, final_equity))

    # ------------------------------------------------------------------
    # Exportación automática de reports si hay reports_dir
    # ------------------------------------------------------------------
    reports_dir = getattr(portfolio, "reports_dir", None)
    if reports_dir is not None:
        try:
            _export_equity_curve_csv(equity_curve, Path(reports_dir), log_prefix)
        except Exception:
            logger.exception("%sFallo exportando equity_curve.csv", log_prefix)
        try:
            _export_trades_csv_if_any(portfolio, Path(reports_dir), log_prefix)
        except Exception:
            logger.exception("%sFallo exportando trades.csv", log_prefix)

    return portfolio


# ----------------------------------------------------------------------
# Helpers de exportación
# ----------------------------------------------------------------------


def _export_equity_curve_csv(
    equity_curve: list[tuple[Any, float]],
    reports_dir: Path,
    log_prefix: str,
) -> None:
    """Escribe equity_curve.csv a partir de la lista local."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    if not equity_curve:
        logger.info("%sEquity curve vacía; no se escribe CSV", log_prefix)
        return
    df = pd.DataFrame(equity_curve, columns=["ts", "equity"])
    path_equity = reports_dir / "equity_curve.csv"
    df.to_csv(path_equity, index=False)
    logger.info("%sEquity curve escrita en %s", log_prefix, path_equity)


def _export_trades_csv_if_any(
    portfolio: Portfolio,
    reports_dir: Path,
    log_prefix: str,
) -> None:
    """Intenta escribir trades.csv si hay trades accesibles en el Portfolio."""
    reports_dir.mkdir(parents=True, exist_ok=True)

    # 1) Vía método oficial si existe
    trades_df_method = getattr(portfolio, "trades_dataframe", None)
    if callable(trades_df_method):
        df_any = trades_df_method()
        if isinstance(df_any, pd.DataFrame) and not df_any.empty:
            path = reports_dir / "trades.csv"
            df_any.to_csv(path, index=False)
            logger.info(
                "%sTrades escritos (trades_dataframe()) en %s",
                log_prefix,
                path,
            )
        else:
            logger.info("%sNo hay trades (trades_dataframe vacío)", log_prefix)
        return

    # 2) Vía atributo _trades si es iterable
    trades = getattr(portfolio, "_trades", None)
    if not trades:
        logger.info("%sNo hay trades para exportar", log_prefix)
        return

    # Intentar mapear a dicts
    rows: list[dict[str, Any]] = []
    for t in trades:
        to_dict = getattr(t, "to_dict", None)
        if callable(to_dict):
            rows.append(to_dict())
        elif isinstance(t, dict):
            rows.append(t)
        else:
            rows.append(getattr(t, "__dict__", {}))

    if not rows:
        logger.info("%sNo hay trades serializables", log_prefix)
        return

    df = pd.DataFrame(rows)
    path = reports_dir / "trades.csv"
    df.to_csv(path, index=False)
    logger.info("%sTrades escritos (fallback _trades) en %s", log_prefix, path)
