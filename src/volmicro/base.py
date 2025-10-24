# src/volmicro/base.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Protocol, Literal, Dict, Any

Side = Literal["BUY", "SELL"]

@dataclass(frozen=True)
class Bar:
    ts: Any          # timestamp (pd.Timestamp u otro)
    open: float
    high: float
    low: float
    close: float
    volume: float
    symbol: str

@dataclass(frozen=True)
class Order:
    symbol: str
    qty: float
    side: Side       # "BUY" o "SELL"
    tag: Optional[str] = None

@dataclass(frozen=True)
class Fill:
    symbol: str
    qty: float
    price: float
    side: Side
    ts: Any
    fee: float = 0.0
    tag: Optional[str] = None

class Strategy(Protocol):
    def on_start(self, ctx: "Context") -> None: ...
    def on_bar(self, ctx: "Context", bar: Bar) -> None: ...
    def on_stop(self, ctx: "Context") -> None: ...

class Context(Protocol):
    symbol: str
    now: Any
    def buy(self, qty: float, tag: Optional[str] = None) -> None: ...
    def sell(self, qty: float, tag: Optional[str] = None) -> None: ...
    def position(self) -> float: ...
    def cash(self) -> float: ...
    def equity(self) -> float: ...
    def last_price(self) -> float: ...
