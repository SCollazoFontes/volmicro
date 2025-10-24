# src/volmicro/feed.py
from __future__ import annotations
from typing import Iterator
import pandas as pd
from volmicro.base import Bar

class PandasFeed:
    """
    Crea un feed a partir de un DataFrame con columnas:
    ['open','high','low','close','volume'] y un índice temporal.
    """
    def __init__(self, df: pd.DataFrame, symbol: str):
        self.df = df
        self.symbol = symbol

    def __iter__(self) -> Iterator[Bar]:
        for ts, row in self.df.iterrows():
            yield Bar(
                ts=ts,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row.get("volume", 0.0)),
                symbol=self.symbol,
            )
