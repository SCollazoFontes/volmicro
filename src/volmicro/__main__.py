import logging
from . import settings
from .binance_client import BinanceClient
from .binance_feed import iter_bars
from .engine import run_engine
from .portfolio import Portfolio
from .strategy import BuySecondBarStrategy

def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")

    client = BinanceClient(testnet=settings.TESTNET)
    df = client.get_klines(symbol=settings.SYMBOL, interval=settings.INTERVAL, limit=settings.LIMIT)
    bars = iter_bars(df, symbol=settings.SYMBOL)

    portfolio = Portfolio(
        cash=10_000.0,
        symbol=settings.SYMBOL,
        fee_bps=settings.FEE_BPS,
        realized_pnl_net_fees=settings.REALIZED_NET_FEES
    )
    strat = BuySecondBarStrategy(alloc_pct=settings.ALLOC_PCT)

    portfolio = run_engine(bars=bars, portfolio=portfolio, strategy=strat, log_every=settings.LOG_EVERY)

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

    eq_df = portfolio.equity_curve_dataframe()
    if not eq_df.empty:
        eq_out = "equity_curve.csv"
        eq_df.to_csv(eq_out, index=False)
        print(f"Equity curve exportada a {eq_out}")



if __name__ == "__main__":
    main()
