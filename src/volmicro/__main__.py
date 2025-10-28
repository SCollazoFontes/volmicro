# src/volmicro/__main__.py

import logging
from pathlib import Path
from uuid import uuid4

from . import settings
from .binance_client import BinanceClient
from .binance_feed import iter_bars
from .engine import run_engine
from .portfolio import Portfolio
from .strategy import BuySecondBarStrategy
from src.volmicro.metrics import calculate_metrics
from src.volmicro.rules import load_symbol_rules


def main():
    # === Generar un identificador único para este run ===
    run_id = str(uuid4())
    print(f"[volmicro] run_id generado: {run_id}")

    # === Logging a consola (básico) ===
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    client = BinanceClient(testnet=settings.TESTNET)
    df = client.get_klines(symbol=settings.SYMBOL, interval=settings.INTERVAL, limit=settings.LIMIT)
    bars = iter_bars(df, symbol=settings.SYMBOL)

    portfolio = Portfolio(
        cash=10_000.0,
        symbol=settings.SYMBOL,
        fee_bps=settings.FEE_BPS,
        realized_pnl_net_fees=settings.REALIZED_NET_FEES,
        run_id=run_id,  # <--- añadido
    )

    strat = BuySecondBarStrategy(alloc_pct=settings.ALLOC_PCT)

    # === Generar subcarpeta de reportes: <SYMBOL>_<STRATEGY>_<YYYY-MM-DD>_runXX ===
    reports_dir: Path = settings.generate_report_dir(
        symbol=settings.SYMBOL,
        strategy_name=strat.__class__.__name__
    )

    # (Opcional) añadir logging a archivo dentro del report actual
    try:
        file_handler = logging.FileHandler(reports_dir / "log.txt")
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
        logging.getLogger().addHandler(file_handler)
    except Exception as e:
        logging.getLogger(__name__).warning(f"No se pudo crear FileHandler de log: {e}")

    # === Reglas de Binance: cargar y fijar en el portfolio ===
    rules = load_symbol_rules(
        settings.SYMBOL,
        testnet=settings.TESTNET,
        use_cache=settings.RULES_USE_CACHE,
        refresh=settings.RULES_REFRESH,
    )
    portfolio.set_execution_rules(rules=rules, slippage_bps=settings.SLIPPAGE_BPS)

    # === Ejecutar backtest ===
    portfolio = run_engine(
        bars=bars,
        portfolio=portfolio,
        strategy=strat,
        log_every=settings.LOG_EVERY,
    )

    print("\n=== RESUMEN FINAL ===")
    s = portfolio.summary()
    print(
        f"Equity final: {s['equity']:.2f} | PnL total: {s['total_pnl']:.2f} | "
        f"Realized: {s['realized_pnl']:.2f} | Posición: {s['qty']} @ {s['avg_price']:.2f}"
    )

    trades_df = portfolio.trades_dataframe()
    if not trades_df.empty:
        print("\nTrades:")
        print(trades_df.to_string(index=False))
    else:
        print("\nSin trades.")

    # === Exportación de resultados dentro del report actual ===
    trades_csv_path = reports_dir / "trades.csv"
    equity_csv_path = reports_dir / "equity_curve.csv"

    if not trades_df.empty:
        trades_df.to_csv(trades_csv_path, index=False)
        print(f"\nTrades exportados a {trades_csv_path}")

    eq_df = portfolio.equity_curve_dataframe()
    if not eq_df.empty:
        eq_df.to_csv(equity_csv_path, index=False)
        print(f"Equity curve exportada a {equity_csv_path}")

    # === Cálculo de métricas (summary.json dentro del report actual) ===
    summary = calculate_metrics(
        equity_curve_path=str(equity_csv_path),
        trades_path=str(trades_csv_path),
        output_dir=str(reports_dir),
    )
    print("\n📊 Métricas del backtest:")
    for k, v in summary.items():
        print(f"{k:25s}: {v}")

    print(f"\n[volmicro] run_id: {run_id}")


if __name__ == "__main__":
    main()
