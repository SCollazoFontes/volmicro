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
    fee_bps: float = 0.0
    starting_cash: float = field(init=False)
    last_price: Optional[float] = None
    trades: List[Trade] = field(default_factory=list)
    _equity_curve: list | None = None

    # tracking de posición
    avg_price: float = 0.0
    realized_pnl: float = 0.0

    realized_pnl_net_fees: bool = False  # si True, restará la fee al realized_pnl

    def __post_init__(self):
        self.starting_cash = float(self.cash)

    def equity(self, price: Optional[float] = None) -> float:
        p = self.last_price if price is None else price
        if p is None:
            return float(self.cash)
        return float(self.cash + self.qty * p)

    def mark_to_market(self, price: float):
        self.last_price = float(price)

    def _record(self, tr: Trade):
        self.trades.append(tr)

    def _fee_from_notional(self, notional: float) -> float:
        return notional * (self.fee_bps / 10_000.0)

    def buy(self, ts: pd.Timestamp, qty: float, price: float, note: str = ""):
        if qty <= 0:
            return
        notional = qty * price
        fee = self._fee_from_notional(notional)
        total = notional + fee
        if self.cash < total:
            raise ValueError("No hay cash suficiente para comprar.")
        # ajustar caja y qty
        self.cash -= total
        new_qty = self.qty + qty
        # actualizar avg_price
        if self.qty <= 0:
            self.avg_price = price
        else:
            self.avg_price = (self.avg_price * self.qty + price * qty) / new_qty
        self.qty = new_qty
        self.last_price = price
        eq = self.equity(price)
        tr = Trade(
            ts=ts, symbol=self.symbol, side="BUY", qty=qty, price=price,
            fee=fee, cash_after=float(self.cash), qty_after=float(self.qty),
            equity_after=float(eq), realized_pnl=0.0, cum_realized_pnl=self.realized_pnl,
            note=note
        )
        self._record(tr)

    def sell(self, ts: pd.Timestamp, qty: float, price: float, note: str = ""):
        if qty <= 0:
            return
        if qty > self.qty:
            raise ValueError("No hay cantidad suficiente para vender.")
        notional = qty * price
        fee = self._fee_from_notional(notional)
        # PnL realizado en esta venta (promedio)
        realized = (price - self.avg_price) * qty
        if self.realized_pnl_net_fees:
            realized -= fee  # netear fees en el PnL realizado si así se desea
        self.realized_pnl += realized
        # ajustar caja y qty
        self.cash += (notional - fee)
        self.qty -= qty
        # si la posición queda a cero, reseteamos avg_price
        if self.qty == 0:
            self.avg_price = 0.0
        self.last_price = price
        eq = self.equity(price)
        tr = Trade(
            ts=ts, symbol=self.symbol, side="SELL", qty=qty, price=price,
            fee=fee, cash_after=float(self.cash), qty_after=float(self.qty),
            equity_after=float(eq), realized_pnl=realized, cum_realized_pnl=self.realized_pnl,
            note=note
        )
        self._record(tr)

    def affordable_qty(self, price: float, alloc_pct: float = 1.0) -> float:
        if price <= 0 or alloc_pct <= 0:
            return 0.0
        fee_mult = 1.0 + (self.fee_bps / 10_000.0)
        budget = self.cash * alloc_pct
        return max(0.0, budget / (price * fee_mult))
    
    def equity_curve_dataframe(self) -> pd.DataFrame:
        if not self._equity_curve:
            return pd.DataFrame(columns=["ts","equity"])
        return pd.DataFrame(self._equity_curve, columns=["ts","equity"]).sort_values("ts").reset_index(drop=True)


    # ===== Reportes =====
    def trades_dataframe(self) -> pd.DataFrame:
        if not self.trades:
            cols = ["ts","symbol","side","qty","price","fee","cash_after","qty_after",
                    "equity_after","realized_pnl","cum_realized_pnl","note"]
            return pd.DataFrame(columns=cols)
        df = pd.DataFrame([t.__dict__ for t in self.trades]).sort_values("ts").reset_index(drop=True)
        return df

    def pnl_total(self) -> float:
        return self.equity() - self.starting_cash

    def summary(self) -> dict:
        return {
            "starting_cash": self.starting_cash,
            "cash": self.cash,
            "qty": self.qty,
            "last_price": self.last_price,
            "equity": self.equity(),
            "realized_pnl": self.realized_pnl,
            "total_pnl": self.pnl_total(),
            "avg_price": self.avg_price,
        }
