from ..base import Strategy
import pandas as pd

class MovingAverageCrossStrategy(Strategy):
    def generate_signals(self):
        short_window = self.params.get("short_window", 10)
        long_window = self.params.get("long_window", 50)
        df = self.data.copy()

        df["short_ma"] = df["close"].rolling(short_window).mean()
        df["long_ma"] = df["close"].rolling(long_window).mean()
        df["signal"] = 0
        df.loc[df["short_ma"] > df["long_ma"], "signal"] = 1
        df.loc[df["short_ma"] < df["long_ma"], "signal"] = -1
        return df["signal"]
