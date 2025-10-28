# src/volmicro/portfolio.py
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Literal, Dict, Any
import pandas as pd
from .trades import Trade
from decimal import Decimal
import math
from src.volmicro.rules import SymbolRules, apply_exchange_rules
from . import settings
from src.volmicro.const import SCHEMA_VERSION  # <-- esquema de datos

logger = logging.getLogger(__name__)

# ----------------------------
# Estructura para vista previa de ejecución (slippage + reglas)
# ----------------------------
@dataclass
class ExecPreview:
    valid: bool
    reason: Optional[str]
    intended_price: float              # precio de referencia (p.ej., close de barra)
    exec_price_raw: float              # precio tras slippage, antes de redondeo tick
    exec_price: float                  # precio final tras redondeo tick
    qty_raw: float                     # qty ideal antes de reglas
    qty_rounded: float                 # qty final tras stepSize
    price_round_diff: float            # exec_price_raw - exec_price
    qty_round_diff: float              # qty_raw - qty_rounded
    slippage_bps: float
    notional_before_round: float       # exec_price_raw * qty_raw
    notional_after_round: float        # exec_price * qty_rounded


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

    # === Reglas y slippage ===
    rules: Optional[SymbolRules] = None
    slippage_bps: float = field(default_factory=lambda: float(settings.SLIPPAGE_BPS))

    # metadatos paralelos a self.trades para columnas avanzadas en trades.csv
    _trade_meta: List[Dict[str, Any]] = field(default_factory=list)

    # run_id para identificar la ejecución
    run_id: Optional[str] = None

    def __post_init__(self):
        self.starting_cash = float(self.cash)

    # ----------------------------
    # API de reglas/slippage
    # ----------------------------
    def set_execution_rules(self, rules: SymbolRules, slippage_bps: float) -> None:
        """Fija reglas de exchange y slippage (bps) para este portfolio."""
        self.rules = rules
        self.slippage_bps = float(slippage_bps)

    # ----------------------------
    # Helpers
    # ----------------------------
    def equity(self, price: Optional[float] = None) -> float:
        p = self.last_price if price is None else price
        if p is None:
            return float(self.cash)
        return float(self.cash + self.qty * p)

    def mark_to_market(self, price: float):
        self.last_price = float(price)

    def _record(self, tr: Trade, meta: Optional[Dict[str, Any]] = None):
        self.trades.append(tr)
        self._trade_meta.append(meta or {})

    def _fee_from_notional(self, notional: float) -> float:
        return notional * (self.fee_bps / 10_000.0)

    def _rules_snapshot(self) -> Dict[str, Any]:
        """
        Devuelve un dict con tickSize/stepSize/minNotional robusto a distintos nombres
        (p.ej., tickSize vs tick_size, minNotional vs min_notional/notionalMin).
        """
        r = self.rules
        if r is None:
            return {"tickSize_used": None, "stepSize_used": None, "minNotional_used": None}

        def get_any(obj, names):
            # Soporta objeto con atributos o dict-like
            for n in names:
                if hasattr(obj, n):
                    return getattr(obj, n)
                if isinstance(obj, dict) and n in obj:
                    return obj[n]
            return None

        tick = get_any(r, ["tickSize", "tick_size", "tick_size_step", "tick_size"])
        step = get_any(r, ["stepSize", "step_size", "step_size_step", "step_size"])
        minimo = get_any(r, ["minNotional", "min_notional", "notionalMin", "min_notional_value"])

        return {
            "tickSize_used": tick,
            "stepSize_used": step,
            "minNotional_used": minimo,
        }

    def _apply_execution_model(self,
                               side: Literal["BUY", "SELL"],
                               ref_price: float,
                               qty_raw: float) -> ExecPreview:
        """
        Aplica slippage (bps) -> redondeo tick/step -> validación reglas (minNotional/minQty)
        y chequeos básicos (cash, qty>0). No modifica estado; solo devuelve la vista previa.
        """
        if qty_raw <= 0 or ref_price <= 0:
            return ExecPreview(False, "qty/ref_price no válidos", ref_price, ref_price, ref_price,
                               qty_raw, 0.0, 0.0, qty_raw, self.slippage_bps, 0.0, 0.0)

        # 1) slippage
        slip = self.slippage_bps / 10_000.0
        exec_price_raw = ref_price * (1 + slip) if side == "BUY" else ref_price * (1 - slip)

        # 2) redondeos según reglas (si existen)
        if self.rules is not None:
            p_dec, q_dec, ok = apply_exchange_rules(price=exec_price_raw, qty=qty_raw, rules=self.rules)
            exec_price = float(p_dec)
            qty_rounded = float(q_dec)
        else:
            exec_price = exec_price_raw
            qty_rounded = qty_raw
            ok = True  # sin reglas, asumimos válido

        price_round_diff = exec_price_raw - exec_price
        qty_round_diff = qty_raw - qty_rounded
        notional_before = exec_price_raw * qty_raw
        notional_after = exec_price * qty_rounded

        # 3) qty debe quedar > 0 tras redondeo
        if qty_rounded <= 0:
            return ExecPreview(False, "qty_rounded == 0 tras stepSize", ref_price, exec_price_raw, exec_price,
                               qty_raw, qty_rounded, price_round_diff, qty_round_diff, self.slippage_bps,
                               notional_before, notional_after)

        # 4) cash suficiente para BUY (incluyendo fee explícita)
        if side == "BUY":
            fee_factor = 1.0 + (self.fee_bps / 10_000.0)
            if notional_after * fee_factor > (self.cash + 1e-9):
                return ExecPreview(False, "cash insuficiente (notional + fee)", ref_price, exec_price_raw, exec_price,
                                   qty_raw, qty_rounded, price_round_diff, qty_round_diff, self.slippage_bps,
                                   notional_before, notional_after)

        # 5) reglas de exchange (si existen) ya comprobadas en apply_exchange_rules
        if self.rules is not None and not ok:
            return ExecPreview(False, "reglas exchange: minNotional/minQty", ref_price, exec_price_raw, exec_price,
                               qty_raw, qty_rounded, price_round_diff, qty_round_diff, self.slippage_bps,
                               notional_before, notional_after)

        return ExecPreview(True, None, ref_price, exec_price_raw, exec_price,
                           qty_raw, qty_rounded, price_round_diff, qty_round_diff, self.slippage_bps,
                           notional_before, notional_after)

    # ----------------------------
    # Ejecución de órdenes (aplica modelo)
    # ----------------------------
    def buy(self, ts: pd.Timestamp, qty: float, price: float, note: str = ""):
        if qty <= 0:
            return

        prev = self._apply_execution_model(side="BUY", ref_price=price, qty_raw=qty)
        if not prev.valid:
            logger.info(f"[BUY omitido] {prev.reason} | qty_raw={qty:.8f} ref={price:.2f}")
            return

        price = prev.exec_price
        qty = prev.qty_rounded

        notional = qty * price
        fee = self._fee_from_notional(notional)
        total = notional + fee

        if self.cash + 1e-9 < total:
            logger.info("[BUY omitido] cash insuficiente en ejecución final")
            return

        # ajustar estado
        self.cash -= total
        new_qty = self.qty + qty
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

        fee_bps_calc = 1e4 * (fee / prev.notional_after_round) if prev.notional_after_round else 0.0
        # Metadatos avanzados + snapshot de reglas + schema
        meta = {
            "intended_price": prev.intended_price,
            "exec_price_raw": prev.exec_price_raw,
            "price_round_diff": prev.price_round_diff,
            "qty_raw": prev.qty_raw,
            "qty_rounded": prev.qty_rounded,
            "qty_round_diff": prev.qty_round_diff,
            "slippage_bps": prev.slippage_bps,
            "notional_before_round": prev.notional_before_round,
            "notional_after_round": prev.notional_after_round,
            "rule_check": "OK" if prev.valid else prev.reason,
            "run_id": self.run_id,
            "fee_bps": fee_bps_calc,
            "schema_version": SCHEMA_VERSION,
            **self._rules_snapshot(),
        }
        self._record(tr, meta=meta)

    def sell(self, ts: pd.Timestamp, qty: float, price: float, note: str = ""):
        if qty <= 0:
            return
        if qty > self.qty + 1e-12:
            raise ValueError("No hay cantidad suficiente para vender.")

        prev = self._apply_execution_model(side="SELL", ref_price=price, qty_raw=qty)
        if not prev.valid:
            logger.info(f"[SELL omitido] {prev.reason} | qty_raw={qty:.8f} ref={price:.2f}")
            return

        price = prev.exec_price
        qty = prev.qty_rounded
        if qty > self.qty + 1e-12:
            qty = min(qty, self.qty)

        notional = qty * price
        fee = self._fee_from_notional(notional)

        realized = (price - self.avg_price) * qty
        if self.realized_pnl_net_fees:
            realized -= fee
        self.realized_pnl += realized

        self.cash += (notional - fee)
        self.qty -= qty
        if self.qty <= 1e-12:
            self.qty = 0.0
            self.avg_price = 0.0

        self.last_price = price
        eq = self.equity(price)

        tr = Trade(
            ts=ts, symbol=self.symbol, side="SELL", qty=qty, price=price,
            fee=fee, cash_after=float(self.cash), qty_after=float(self.qty),
            equity_after=float(eq), realized_pnl=realized, cum_realized_pnl=self.realized_pnl,
            note=note
        )

        fee_bps_calc = 1e4 * (fee / prev.notional_after_round) if prev.notional_after_round else 0.0
        meta = {
            "intended_price": prev.intended_price,
            "exec_price_raw": prev.exec_price_raw,
            "price_round_diff": prev.price_round_diff,
            "qty_raw": prev.qty_raw,
            "qty_rounded": prev.qty_rounded,
            "qty_round_diff": prev.qty_round_diff,
            "slippage_bps": prev.slippage_bps,
            "notional_before_round": prev.notional_before_round,
            "notional_after_round": prev.notional_after_round,
            "rule_check": "OK" if prev.valid else prev.reason,
            "run_id": self.run_id,
            "fee_bps": fee_bps_calc,
            "schema_version": SCHEMA_VERSION,
            **self._rules_snapshot(),
        }
        self._record(tr, meta=meta)

    # ----------------------------
    # Sizing
    # ----------------------------
    def affordable_qty(self, price: float, alloc_pct: float = 1.0) -> float:
        if price <= 0 or alloc_pct <= 0:
            return 0.0
        fee_mult = 1.0 + (self.fee_bps / 10_000.0)
        budget = self.cash * alloc_pct
        return max(0.0, budget / (price * fee_mult))

    # ----------------------------
    # Reports
    # ----------------------------
    def equity_curve_dataframe(self) -> pd.DataFrame:
        if not self._equity_curve:
            return pd.DataFrame(columns=["ts", "equity"])
        return pd.DataFrame(self._equity_curve, columns=["ts", "equity"]).sort_values("ts").reset_index(drop=True)

    def trades_dataframe(self) -> pd.DataFrame:
        """
        Combina los datos de Trade con metadatos de ejecución (slippage/reglas).
        """
        base_cols = ["ts","symbol","side","qty","price","fee","cash_after","qty_after",
                     "equity_after","realized_pnl","cum_realized_pnl","note"]

        if not self.trades:
            extra_cols = [
                "intended_price","exec_price_raw","price_round_diff","qty_raw","qty_rounded",
                "qty_round_diff","slippage_bps","notional_before_round","notional_after_round","rule_check",
                "run_id","fee_bps","tickSize_used","stepSize_used","minNotional_used","schema_version"
            ]
            return pd.DataFrame(columns=base_cols + extra_cols)

        df = pd.DataFrame([t.__dict__ for t in self.trades]).sort_values("ts").reset_index(drop=True)

        if self._trade_meta and len(self._trade_meta) == len(self.trades):
            meta_df = pd.DataFrame(self._trade_meta).reindex(df.index)
            df = pd.concat([df, meta_df], axis=1)
        else:
            for c in base_cols:
                if c not in df.columns:
                    df[c] = None
            df = df[base_cols]

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
