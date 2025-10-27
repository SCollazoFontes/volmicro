# src/volmicro/__main__.py
from src.volmicro.binance_feed import iter_bars
from src.volmicro.engine import run
from src.volmicro.strategy import BuySecondBarStrategy

def main():
    bars = iter_bars(
        symbol="BTCUSDT",
        interval="1h",
        start_str="2025-10-26 00:00:00",
        limit=10,
    )
    strat = BuySecondBarStrategy()
    portfolio = run(bars, strategy=strat, cash_init=10_000.0)
    print(f"FIN → cash={portfolio.cash:.2f} qty={portfolio.qty:.6f} equity={portfolio.equity:.2f}")

if __name__ == "__main__":
    main()
