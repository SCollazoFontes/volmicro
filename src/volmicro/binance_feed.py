# src/volmicro/binance_feed.py
from __future__ import annotations
import pandas as pd
from typing import Iterator
from .core import Bar

def iter_bars(df: pd.DataFrame, symbol: str) -> Iterator[Bar]:
    """
    Convierte un DataFrame de klines (index UTC, columnas: open, high, low, close, volume)
    en un generador de objetos Bar.
    """
    for ts, row in df.iterrows():
        yield Bar(
            ts=ts, symbol=symbol,
            open=float(row["open"]), high=float(row["high"]),
            low=float(row["low"]), close=float(row["close"]),
            volume=float(row["volume"])
        )
