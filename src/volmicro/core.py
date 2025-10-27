# src/volmicro/core.py
from dataclasses import dataclass
from typing import Any
from pandas import Timestamp

@dataclass(frozen=True)
class Bar:
    ts: Any      # timestamp (pd.Timestamp)
    open: float
    high: float
    low: float
    close: float
    volume: float
    symbol: str
