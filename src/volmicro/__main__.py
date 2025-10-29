# src/volmicro/__main__.py
"""
Punto de entrada del paquete `volmicro`.

Novedad:
- Conexión de `data.start` / `data.end` desde YAML a `BinanceClient.get_klines`.
- Log y manifest ya incluyen estos campos vía `cfg["data"]`.

Resumen:
1) CLI + YAML → config efectiva (CLI > YAML > settings).
2) Descargar klines por límite o por rango (start/end).
3) Backtest completo y persistencia de resultados + run_manifest.json.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from shutil import copyfile
from typing import Any
from uuid import uuid4

try:
    import yaml  # type: ignore[import-untyped]
except Exception:  # pragma: no cover
    yaml = None

from . import settings
from .binance_client import BinanceClient
from .binance_feed import iter_bars
from .engine import run_engine
from .metrics import calculate_metrics
from .portfolio import Portfolio
from .rules import load_symbol_rules
from .strategy import BuySecondBarStrategy

# --------------------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------------------


def _setup_logging(loglevel: str = "INFO", logfile: Path | None = None) -> None:
    level = getattr(logging, loglevel.upper(), logging.INFO)
    fmt = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    logging.basicConfig(level=level, format=fmt, datefmt=datefmt)
    if logfile is not None:
        try:
            fh = logging.FileHandler(logfile)
            fh.setLevel(level)
            fh.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))
            logging.getLogger().addHandler(fh)
        except Exception as e:  # pragma: no cover
            logging.getLogger(__name__).warning(f"No se pudo crear FileHandler: {e}")


# --------------------------------------------------------------------------------------
# Config (YAML + CLI)
# --------------------------------------------------------------------------------------


def _load_yaml_config(path: str | Path) -> dict[str, Any]:
    if path is None:
        return {}
    if yaml is None:
        raise RuntimeError("PyYAML no está instalado. Ejecuta: pip install pyyaml")
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"No existe el archivo de configuración: {p}")
    with p.open("r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}
    if not isinstance(cfg, dict):
        raise ValueError("El YAML debe tener un objeto dict en la raíz.")
    return cfg


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="volmicro – backtest/paper/live runner")
    p.add_argument("--config", type=str, default=None, help="Ruta a YAML (configs/example.yaml)")
    p.add_argument(
        "--mode",
        type=str,
        choices=["backtest", "paper", "live"],
        default=None,
        help="Modo de ejecución (sobrescribe YAML).",
    )
    p.add_argument("--symbol", help=f"Símbolo (default settings.SYMBOL={settings.SYMBOL})")
    p.add_argument("--interval", help=f"Intervalo (default settings.INTERVAL={settings.INTERVAL})")
    p.add_argument("--limit", type=int, help=f"Límite klines (default={settings.LIMIT})")
    p.add_argument(
        "--testnet", type=str, help=f"Usar testnet true/false (default={settings.TESTNET})"
    )
    p.add_argument("--loglevel", default="INFO", help="Nivel log (DEBUG|INFO|WARNING|ERROR)")
    p.add_argument("--logevery", type=int, help=f"Log cada N barras (default={settings.LOG_EVERY})")
    return p.parse_args()


def _coerce_bool(x: str | None, default: bool) -> bool:
    if x is None:
        return default
    return str(x).strip().lower() in {"1", "true", "yes", "y", "on"}


def _resolve_config(args: argparse.Namespace) -> dict[str, Any]:
    # 1) YAML (si existe)
    config_path = args.config
    if config_path is None:
        default_cfg = Path("configs/example.yaml")
        config_path = str(default_cfg) if default_cfg.exists() else None
    ycfg: dict[str, Any] = _load_yaml_config(config_path) if config_path else {}

    # 2) Defaults desde settings
    mode = "backtest"
    symbol = settings.SYMBOL
    interval = settings.INTERVAL
    limit = settings.LIMIT
    start = None
    end = None
    testnet = settings.TESTNET
    log_every = settings.LOG_EVERY
    fees_bps = settings.FEE_BPS
    slippage_bps = settings.SLIPPAGE_BPS
    loglevel = "INFO"

    # 3) Mezclar YAML
    mode = ycfg.get("mode", mode)
    data = ycfg.get("data", {})
    execution = ycfg.get("execution", {})
    symbol = data.get("symbol", symbol)
    interval = data.get("interval", interval)
    limit = int(data.get("limit", limit)) if "limit" in data else limit
    start = data.get("start", start)  # puede ser "YYYY-MM-DD" o timestamp
    end = data.get("end", end)
    log_every = int(execution.get("log_every", log_every))
    fees_bps = int(execution.get("fees_bps", fees_bps))
    slippage_bps = int(execution.get("slippage_bps", slippage_bps))

    # 4) Overrides CLI
    mode = args.mode or mode
    symbol = (args.symbol or symbol).upper()
    interval = args.interval or interval
    limit = args.limit if args.limit is not None else limit
    testnet = _coerce_bool(args.testnet, testnet)
    log_every = args.logevery if args.logevery is not None else log_every
    loglevel = args.loglevel or loglevel

    return {
        "mode": mode,
        "data": {
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
            "start": start,
            "end": end,
        },
        "execution": {"log_every": log_every, "fees_bps": fees_bps, "slippage_bps": slippage_bps},
        "flags": {"testnet": testnet, "loglevel": loglevel},
        "raw_yaml": ycfg,
        "config_path": config_path,
    }


# --------------------------------------------------------------------------------------
# Run manifest (trazabilidad)
# --------------------------------------------------------------------------------------


def _git_commit_hash() -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.STDOUT
        )
        return out.decode("utf-8").strip()
    except Exception:
        return None


def _write_run_manifest(
    reports_dir: Path,
    run_id: str,
    cfg_effective: dict[str, Any],
    trades_csv: Path,
    equity_csv: Path,
    summary: dict[str, Any] | None,
) -> None:
    manifest: dict[str, Any] = {}
    manifest["id"] = run_id
    manifest["timestamp_utc"] = datetime.now(tz=UTC).isoformat()
    manifest["git_commit"] = _git_commit_hash()
    manifest["config_path"] = cfg_effective.get("config_path")
    manifest["config_effective"] = {
        "mode": cfg_effective.get("mode"),
        "data": cfg_effective.get("data"),
        "execution": cfg_effective.get("execution"),
        "flags": cfg_effective.get("flags"),
    }
    cfg_copy_name = None
    if cfg_effective.get("config_path"):
        try:
            src = Path(cfg_effective["config_path"])
            if src.exists():
                cfg_copy_name = "config_used.yaml"
                copyfile(src, reports_dir / cfg_copy_name)
        except Exception as e:  # pragma: no cover
            logging.getLogger(__name__).warning(f"No se pudo copiar el YAML al report: {e}")
    manifest["config_yaml_copy"] = cfg_copy_name
    outputs: dict[str, Any] = {
        "trades_csv": str(trades_csv),
        "equity_curve_csv": str(equity_csv),
        "summary_json": str(reports_dir / "summary.json"),
        "log_file": str(reports_dir / "log.txt"),
    }
    manifest["outputs"] = outputs
    if summary is not None:
        manifest["metrics"] = summary
    try:
        out_path = reports_dir / "run_manifest.json"
        with out_path.open("w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, ensure_ascii=False)
        logging.info("Run manifest escrito en %s", out_path)
    except Exception as e:  # pragma: no cover
        logging.getLogger(__name__).warning(f"No se pudo escribir run_manifest.json: {e}")


# --------------------------------------------------------------------------------------
# Programa principal
# --------------------------------------------------------------------------------------


def main() -> None:
    # Config efectiva
    args = _parse_args()
    cfg = _resolve_config(args)

    mode = cfg["mode"]
    symbol = cfg["data"]["symbol"]
    interval = cfg["data"]["interval"]
    limit = cfg["data"]["limit"]
    start = cfg["data"]["start"]
    end = cfg["data"]["end"]

    testnet = cfg["flags"]["testnet"]
    loglevel = cfg["flags"]["loglevel"]

    log_every = cfg["execution"]["log_every"]
    fees_bps = cfg["execution"]["fees_bps"]
    slippage_bps = cfg["execution"]["slippage_bps"]

    run_id = str(uuid4())
    print(f"[volmicro] run_id generado: {run_id}")

    _setup_logging(loglevel=loglevel)

    logging.info(
        "Run config: mode=%s symbol=%s interval=%s limit=%s start=%s end=%s "
        "log_every=%s fees_bps=%s slippage_bps=%s testnet=%s config_path=%s",
        mode,
        symbol,
        interval,
        limit,
        start,
        end,
        log_every,
        fees_bps,
        slippage_bps,
        testnet,
        cfg["config_path"],
    )

    # Cliente y descarga
    client = BinanceClient(testnet=testnet)
    try:
        df = client.get_klines(
            symbol=symbol,
            interval=interval,
            limit=limit,
            start=start,
            end=end,
        )
    except Exception:
        msg = (
            "Error descargando klines de Binance: "
            f"symbol={symbol} interval={interval} limit={limit} start={start} end={end}"
        )
        logging.getLogger(__name__).exception(msg)
        raise

    # Transformación a barras
    try:
        bars = iter_bars(df, symbol=symbol)
    except Exception:
        logging.getLogger(__name__).exception("Error convirtiendo DataFrame OHLCV a barras")
        raise  # <-- el re-raise va DENTRO del except

    # Portfolio + Strategy
    portfolio = Portfolio(
        cash=10_000.0,
        symbol=symbol,
        fee_bps=fees_bps,
        realized_pnl_net_fees=settings.REALIZED_NET_FEES,
        run_id=run_id,
    )
    strat = BuySecondBarStrategy(alloc_pct=settings.ALLOC_PCT)

    # Reports dir + logging a archivo
    reports_dir: Path = settings.generate_report_dir(
        symbol=symbol,
        strategy_name=strat.__class__.__name__,
    )
    _setup_logging(loglevel=loglevel, logfile=reports_dir / "log.txt")

    # PUNTO CLAVE: exponer reports_dir al engine vía Portfolio
    portfolio.reports_dir = str(reports_dir)

    # Reglas de exchange
    try:
        rules = load_symbol_rules(
            symbol=symbol,
            testnet=testnet,
            use_cache=settings.RULES_USE_CACHE,
            refresh=settings.RULES_REFRESH,
        )
        portfolio.set_execution_rules(rules=rules, slippage_bps=slippage_bps)
    except Exception:
        logging.getLogger(__name__).exception("Error cargando reglas del exchange")
        raise

    # Backtest
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

    # Resumen
    print("\n=== RESUMEN FINAL ===")
    s = portfolio.summary()
    print(
        f"Equity final: {s['equity']:.2f} | PnL total: {s['total_pnl']:.2f} | "
        f"Realized: {s['realized_pnl']:.2f} | Posición: {s['qty']} @ {s['avg_price']:.6f}"
    )

    # Exportaciones (si el engine ya escribió, seguimos ok)
    trades_csv = reports_dir / "trades.csv"
    equity_csv = reports_dir / "equity_curve.csv"

    trades_df = portfolio.trades_dataframe()
    if not trades_df.empty:
        try:
            trades_df.to_csv(trades_csv, index=False)
            print(f"Trades exportados a {trades_csv}")
        except Exception as e:
            logging.getLogger(__name__).warning(f"No se pudo escribir trades.csv: {e}")
    else:
        if trades_csv.exists():
            print(f"Trades ya exportados por engine en {trades_csv}")
        else:
            print("Sin trades.")

    eq_df = portfolio.equity_curve_dataframe()
    if not eq_df.empty:
        try:
            eq_df.to_csv(equity_csv, index=False)
            print(f"Equity curve exportada a {equity_csv}")
        except Exception as e:
            logging.getLogger(__name__).warning(f"No se pudo escribir equity_curve.csv: {e}")
    else:
        if equity_csv.exists():
            print(f"Equity curve ya exportada por engine en {equity_csv}")
        else:
            logging.getLogger(__name__).warning("Equity curve vacía; no se pudo exportar.")

    # Métricas
    summary: dict[str, Any] | None = None
    try:
        summary = calculate_metrics(
            equity_curve_path=str(equity_csv),
            trades_path=str(trades_csv),
            output_dir=str(reports_dir),
        )
        print("\n📊 Métricas del backtest:")
        for k, v in summary.items():
            print(f"{k:25s}: {v}")
    except Exception as e:  # pragma: no cover
        logging.getLogger(__name__).warning(f"Fallo calculando métricas: {e}")

    # Manifest
    try:
        _write_run_manifest(
            reports_dir=reports_dir,
            run_id=run_id,
            cfg_effective=cfg,
            trades_csv=trades_csv,
            equity_csv=equity_csv,
            summary=summary,
        )
    except Exception as e:  # pragma: no cover
        logging.getLogger(__name__).warning(f"No se pudo escribir manifest: {e}")

    print(f"\n[volmicro] run_id: {run_id}")


if __name__ == "__main__":
    main()
