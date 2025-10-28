from __future__ import annotations
import pandas as pd
from typing import Iterator
from .core import Bar

def iter_bars(df: pd.DataFrame, symbol: str) -> Iterator[Bar]:
    required = {"open","high","low","close","volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"El DataFrame de feed no tiene columnas: {missing}")
    if df.index.tz is None:
        raise ValueError("El índice del DataFrame debe ser UTC tz-aware.")

    for ts, row in df.iterrows():
        yield Bar(
            ts=ts, symbol=symbol,
            open=float(row["open"]), high=float(row["high"]),
            low=float(row["low"]), close=float(row["close"]),
            volume=float(row["volume"])
        )
