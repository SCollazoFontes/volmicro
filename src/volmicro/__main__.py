# src/volmicro/__main__.py
import logging
from .binance_client import BinanceClient
from .binance_feed import iter_bars
from .engine import run_engine
from .portfolio import Portfolio
from .strategy import BuySecondBarStrategy

def main():
    logging.basicConfig(
        level=logging.INFO,  # cambia a DEBUG si quieres más detalle
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    symbol = "BTCUSDT"
    interval = "1h"
    limit = 200

    client = BinanceClient(testnet=True)
    df = client.get_klines(symbol=symbol, interval=interval, limit=limit)
    bars = iter_bars(df, symbol=symbol)

    portfolio = Portfolio(cash=10_000.0, symbol=symbol, fee_bps=1.0)
    strat = BuySecondBarStrategy()

    portfolio = run_engine(bars=bars, portfolio=portfolio, strategy=strat)

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

    trades_df = portfolio.trades_dataframe()

    if not trades_df.empty:
        out = "trades.csv"
        trades_df.to_csv(out, index=False)
        print(f"\nTrades exportados a {out}")


if __name__ == "__main__":
    main()
