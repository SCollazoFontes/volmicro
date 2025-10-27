# src/volmicro/portfolio.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional
import pandas as pd

from .trades import Trade

@dataclass
class Portfolio:
    cash: float = 10_000.0
    qty: float = 0.0
    symbol: str = "BTCUSDT"
    fee_bps: float = 0.0  # comisiones en basis points (0.0 => sin comisiones)
    starting_cash: float = field(init=False)
    last_price: Optional[float] = None
    trades: List[Trade] = field(default_factory=list)

    def __post_init__(self):
        self.starting_cash = float(self.cash)

    # ============== Estado / MTM ==============
    def equity(self, price: Optional[float] = None) -> float:
        p = self.last_price if price is None else price
        if p is None:
            # al inicio, si no conocemos precio, la equity es solo el cash
            return float(self.cash)
        return float(self.cash + self.qty * p)

    def mark_to_market(self, price: float):
        """Actualiza el último precio conocido para marcar a mercado."""
        self.last_price = float(price)

    # ============== Ejecución ==============
    def _record_trade(self, ts: pd.Timestamp, side: str, qty: float, price: float, note: str = ""):
        notional = qty * price
        fee = notional * (self.fee_bps / 10_000.0)

        if side == "BUY":
            if self.cash < notional + fee:
                raise ValueError("No hay cash suficiente para comprar.")
            self.cash -= (notional + fee)
            self.qty += qty

        elif side == "SELL":
            if self.qty < qty:
                raise ValueError("No hay cantidad suficiente para vender.")
            self.cash += (notional - fee)
            self.qty -= qty

        # actualizar último precio y equity
        self.last_price = float(price)
        eq = self.equity(price)

        self.trades.append(
            Trade(
                ts=ts, symbol=self.symbol, side=side, qty=qty, price=price,
                fee=fee, cash_after=float(self.cash), qty_after=float(self.qty),
                equity_after=float(eq), note=note
            )
        )

    def buy(self, ts: pd.Timestamp, qty: float, price: float, note: str = ""):
        self._record_trade(ts=ts, side="BUY", qty=qty, price=price, note=note)

    def sell(self, ts: pd.Timestamp, qty: float, price: float, note: str = ""):
        self._record_trade(ts=ts, side="SELL", qty=qty, price=price, note=note)

    # ============== Reportes ==============
    def trades_dataframe(self) -> pd.DataFrame:
        if not self.trades:
            return pd.DataFrame(columns=["ts","symbol","side","qty","price","fee","cash_after","qty_after","equity_after","note"])
        df = pd.DataFrame([t.__dict__ for t in self.trades])
        df = df.sort_values("ts").reset_index(drop=True)
        return df

    def pnl_total(self) -> float:
        return self.equity() - self.starting_cash
