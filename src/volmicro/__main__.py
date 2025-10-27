# src/volmicro/__main__.py
import logging
from .binance_client import BinanceClient
from .binance_feed import iter_bars
from .engine import run_engine
from .portfolio import Portfolio
from .strategy import BuySecondBarStrategy

def main():
    # Logging: INFO para ver barras, DEBUG si quieres post-on_bar
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    symbol = "BTCUSDT"
    interval = "1h"
    limit = 200

    client = BinanceClient(testnet=True)
    df = client.get_klines(symbol=symbol, interval=interval, limit=limit)
    bars = iter_bars(df, symbol=symbol)

    portfolio = Portfolio(cash=10_000.0, symbol=symbol, fee_bps=1.0)  # p.ej. 1 bps de fee
    strat = BuySecondBarStrategy()

    portfolio = run_engine(bars=bars, portfolio=portfolio, strategy=strat)

    # ===== Resumen final =====
    print("\n=== RESUMEN FINAL ===")
    print(f"Equity final: {portfolio.equity():.2f}  |  PnL: {portfolio.pnl_total():.2f}")
    trades_df = portfolio.trades_dataframe()
    if not trades_df.empty:
        # muestra compacto
        print("\nTrades:")
        print(trades_df.to_string(index=False))
    else:
        print("\nSin trades.")

if __name__ == "__main__":
    main()
