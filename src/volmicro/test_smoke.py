import pandas as pd
from src.volmicro.core import Bar
from src.volmicro.engine import run_engine
from src.volmicro.portfolio import Portfolio
from src.volmicro.strategy import BuySecondBarStrategy

def make_df(n=10, start=100.0, step=1.0):
    idx = pd.date_range("2025-01-01", periods=n, freq="H", tz="UTC")
    data = {
        "open":  [start + i*step for i in range(n)],
        "high":  [start + i*step + 1 for i in range(n)],
        "low":   [start + i*step - 1 for i in range(n)],
        "close": [start + i*step for i in range(n)],
        "volume":[1.0]*n,
    }
    df = pd.DataFrame(data, index=idx)
    return df

def test_engine_runs_and_trades():
    df = make_df(n=10, start=100.0, step=1.0)
    from src.volmicro.binance_feed import iter_bars
    bars = iter_bars(df, symbol="TEST")

    p = Portfolio(cash=1000.0, symbol="TEST", fee_bps=0.0)
    strat = BuySecondBarStrategy(alloc_pct=0.10)
    p = run_engine(bars, p, strat, log_every=1000)  # sin ruido

    trades = p.trades_dataframe()
    assert len(trades) == 2  # compra en barra 2 y venta al final
    assert p.equity() > p.starting_cash  # precio sube => equity sube
