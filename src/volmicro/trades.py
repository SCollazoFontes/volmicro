# src/volmicro/trades.py
from dataclasses import dataclass
from typing import Literal, Optional
import pandas as pd

Side = Literal["BUY", "SELL"]

@dataclass
class Trade:
    ts: pd.Timestamp
    symbol: str
    side: Side
    qty: float
    price: float
    fee: float
    cash_after: float
    qty_after: float
    equity_after: float
    note: str = ""
