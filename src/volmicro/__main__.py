# src/volmicro/__main__.py
"""
Punto de entrada del paquete `volmicro`.

Flujo general del programa:
1) Inicializa logging y genera un `run_id` único (para trazar la ejecución).
2) Crea el cliente de Binance (testnet/mainnet) y descarga un bloque de klines.
3) Convierte el DataFrame OHLCV en un generador de `Bar` con `iter_bars`.
4) Inicializa la `Portfolio` y la `Strategy`.
5) Carga las reglas del exchange y fija el slippage en la cartera.
6) Ejecuta el backtest con `run_engine`.
7) Imprime un resumen por consola y exporta:
   - `trades.csv`
   - `equity_curve.csv`
8) Calcula métricas con `metrics.calculate_metrics(...)` y escribe `summary.json`.

Consejos:
- Puedes sobreescribir variables de `settings` con flags CLI (--symbol, --interval...).
- Los reportes se guardan en una subcarpeta con patrón:
    reports/<SYMBOL>_<STRATEGY>_<YYYY-MM-DD>_runXX
- Si algo falla (red, permisos, fichero) mostramos mensajes claros sin suprimir trazas
  críticas (fase de desarrollo). En producción podrías capturar más fino.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from uuid import uuid4

from . import settings
from .binance_client import BinanceClient
from .binance_feed import iter_bars
from .engine import run_engine
from .metrics import calculate_metrics
from .portfolio import Portfolio
from .rules import load_symbol_rules
from .strategy import BuySecondBarStrategy

# --------------------------------------------------------------------------------------
# Utilidades de logging
# --------------------------------------------------------------------------------------


def _setup_logging(loglevel: str = "INFO", logfile: Path | None = None) -> None:
    """
    Configura logging a consola y (opcionalmente) a un archivo.

    - `loglevel`: "DEBUG", "INFO", "WARNING", "ERROR"
    - `logfile`: si se proporciona, escribe los logs también en ese fichero.
    """
    level = getattr(logging, loglevel.upper(), logging.INFO)

    # Formato común para consola y archivo
    fmt = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    # Handler de consola
    logging.basicConfig(level=level, format=fmt, datefmt=datefmt)

    # (Opcional) Handler a archivo
    if logfile is not None:
        try:
            fh = logging.FileHandler(logfile)
            fh.setLevel(level)
            fh.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))
            logging.getLogger().addHandler(fh)
        except Exception as e:
            logging.getLogger(__name__).warning(f"No se pudo crear FileHandler de log: {e}")


# --------------------------------------------------------------------------------------
# CLI opcional para sobreescribir settings
# --------------------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    """
    Parser de argumentos CLI para overrides rápidos de configuración.
    Todos son opcionales: si no los pasas, se usan los valores de settings.
    """
    p = argparse.ArgumentParser(description="volmicro – backtest runner")
    p.add_argument("--symbol", help=f"Símbolo (default settings.SYMBOL={settings.SYMBOL})")
    p.add_argument("--interval", help=f"Intervalo (default settings.INTERVAL={settings.INTERVAL})")
    p.add_argument(
        "--limit", type=int, help=f"Límite klines (default settings.LIMIT={settings.LIMIT})"
    )
    p.add_argument(
        "--testnet", type=str, help=f"Usar testnet true/false (default={settings.TESTNET})"
    )
    p.add_argument("--loglevel", default="INFO", help="Nivel log (DEBUG|INFO|WARNING|ERROR)")
    p.add_argument("--logevery", type=int, help=f"Log cada N barras (default={settings.LOG_EVERY})")
    return p.parse_args()


def _coerce_bool(x: str | None, default: bool) -> bool:
    """Convierte strings tipo 'true/false/1/0/on/off' a bool, con default si None."""
    if x is None:
        return default
    return str(x).strip().lower() in {"1", "true", "yes", "y", "on"}


# --------------------------------------------------------------------------------------
# Programa principal
# --------------------------------------------------------------------------------------


def main() -> None:
    # === 1) CLI y logging ===
    args = _parse_args()

    # Overrides: si el usuario pasa flags, usamos esas; si no, settings.*
    symbol = (args.symbol or settings.SYMBOL).upper()
    interval = args.interval or settings.INTERVAL
    limit = args.limit if args.limit is not None else settings.LIMIT
    testnet = _coerce_bool(args.testnet, settings.TESTNET)
    log_every = args.logevery if args.logevery is not None else settings.LOG_EVERY

    # Generar un identificador único para este run (útil en CSVs y logs)
    run_id = str(uuid4())
    print(f"[volmicro] run_id generado: {run_id}")

    # Configurar logging (consola ahora; fichero se añade cuando tengamos report_dir)
    _setup_logging(loglevel=args.loglevel)

    # === 2) Cliente y descarga de datos ===
    client = BinanceClient(testnet=testnet)
    try:
        df = client.get_klines(symbol=symbol, interval=interval, limit=limit)
    except Exception:
        msg = (
            "Error descargando klines de Binance: "
            f"symbol={symbol} interval={interval} limit={limit}"
        )
        logging.getLogger(__name__).exception(msg)
        raise

    # === 3) Transformación a barras ===
    try:
        bars = iter_bars(df, symbol=symbol)
    except Exception:
        logging.getLogger(__name__).exception("Error convirtiendo DataFrame OHLCV a barras")
        raise

    # === 4) Portfolio y estrategia ===
    portfolio = Portfolio(
        cash=10_000.0,  # efectivo inicial (puedes exponer por CLI más adelante)
        symbol=symbol,
        fee_bps=settings.FEE_BPS,
        realized_pnl_net_fees=settings.REALIZED_NET_FEES,
        run_id=run_id,
    )
    strat = BuySecondBarStrategy(alloc_pct=settings.ALLOC_PCT)

    # === 5) Crear carpeta de reportes para esta ejecución ===
    reports_dir: Path = settings.generate_report_dir(
        symbol=symbol,
        strategy_name=strat.__class__.__name__,
    )

    # Añadimos logging a archivo dentro del report actual
    _setup_logging(loglevel=args.loglevel, logfile=reports_dir / "log.txt")

    # === 6) Reglas de Binance: cargar y fijar en el portfolio ===
    try:
        rules = load_symbol_rules(
            symbol=symbol,
            testnet=testnet,
            use_cache=settings.RULES_USE_CACHE,
            refresh=settings.RULES_REFRESH,
        )
        portfolio.set_execution_rules(rules=rules, slippage_bps=settings.SLIPPAGE_BPS)
    except Exception:
        logging.getLogger(__name__).exception("Error cargando reglas del exchange")
        raise

    # === 7) Ejecutar backtest ===
    try:
        portfolio = run_engine(
            bars=bars,
            portfolio=portfolio,
            strategy=strat,
            log_every=log_every,
        )
    except Exception:
        logging.getLogger(__name__).exception("Error durante la ejecución del backtest")
        raise

    # === 8) Resumen por consola ===
    print("\n=== RESUMEN FINAL ===")
    s = portfolio.summary()
    print(
        f"Equity final: {s['equity']:.2f} | PnL total: {s['total_pnl']:.2f} | "
        f"Realized: {s['realized_pnl']:.2f} | Posición: {s['qty']} @ {s['avg_price']:.6f}"
    )

    # === 9) Exportación de resultados a CSV dentro del report ===
    trades_csv_path = reports_dir / "trades.csv"
    equity_csv_path = reports_dir / "equity_curve.csv"

    trades_df = portfolio.trades_dataframe()
    if not trades_df.empty:
        try:
            trades_df.to_csv(trades_csv_path, index=False)
            print(f"Trades exportados a {trades_csv_path}")
        except Exception as e:
            logging.getLogger(__name__).warning(f"No se pudo escribir trades.csv: {e}")
    else:
        print("Sin trades.")

    eq_df = portfolio.equity_curve_dataframe()
    if not eq_df.empty:
        try:
            eq_df.to_csv(equity_csv_path, index=False)
            print(f"Equity curve exportada a {equity_csv_path}")
        except Exception as e:
            logging.getLogger(__name__).warning(f"No se pudo escribir equity_curve.csv: {e}")

    # === 10) Cálculo de métricas y summary.json ===
    try:
        summary = calculate_metrics(
            equity_curve_path=str(equity_csv_path),
            trades_path=str(trades_csv_path),
            output_dir=str(reports_dir),
        )
        print("\n📊 Métricas del backtest:")
        for k, v in summary.items():
            print(f"{k:25s}: {v}")
    except Exception as e:
        logging.getLogger(__name__).warning(f"Fallo calculando métricas: {e}")

    print(f"\n[volmicro] run_id: {run_id}")


if __name__ == "__main__":
    main()
