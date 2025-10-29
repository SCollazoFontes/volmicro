# src/volmicro/portfolio.py
"""
Módulo de cartera y ejecución simulada.

Responsabilidades principales
-----------------------------
1) Mantener el estado de la cartera:
   - cash (efectivo), qty (posición), avg_price (precio medio), realized_pnl (PnL realizado),
     last_price (último precio marcado), equity (valor total = cash + qty * last_price).
2) Simular la ejecución de órdenes BUY/SELL:
   - Aplicar slippage en bps al precio de referencia (p. ej. el close de la barra).
   - Respetar reglas del exchange (tickSize, stepSize, minQty, minNotional) si están disponibles.
   - Cobrar comisiones en bps sobre el notional.
   - Validar cash suficiente (BUY) y antidad disponible (SELL).
   - Registrar el trade (con metadatos útiles para auditoría) manteniendo un schema_version.
3) Proveer utilidades de sizing (p. ej. affordable_qty), reporting
   (equity_curve_dataframe, trades_dataframe, summary) y engancharse al engine
   (mark_to_market).

Diseño
------
- La simulación de ejecución está separada en `_apply_execution_model(...)` que devuelve
  un `ExecPreview` (vista previa) con precio/cantidad tras slippage+redondeos y checks.
- Las reglas del exchange se modelan con `SymbolRules` y se aplican vía
  `apply_exchange_rules(...)` (en `src/volmicro/rules.py`).
- Los trades se almacenan como dataclasses `Trade` y además guardamos metadatos paralelos
  (slippage aplicado, redondeos, reglas usadas, run_id, fee_bps, etc.) para cumplir un
  **esquema** estable (ver `tests/test_trades_schema.py` y `SCHEMA_VERSION`).

Integración
-----------
- `engine.run_engine(...)` llama `portfolio.mark_to_market()` con cada barra y delega
  en la estrategia `strategy.on_bar(bar, portfolio)` que probablemente invoca `buy(...)`
  o `sell(...)`.
- `__main__.py` inicializa `Portfolio(...)`, carga reglas y slippage con `set_execution_rules(...)`,
  y al terminar exporta `trades_dataframe()` y `equity_curve_dataframe()` a CSV.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

import pandas as pd

from src.volmicro.const import SCHEMA_VERSION  # versión del esquema de salida (CSV de trades)
from src.volmicro.rules import SymbolRules, apply_exchange_rules

from . import settings
from .trades import Trade

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------------------
# Estructura de vista previa de ejecución (resultado de aplicar slippage + reglas)
# --------------------------------------------------------------------------------------
@dataclass
class ExecPreview:
    """
    Resultado intermedio de la simulación de ejecución ANTES de tocar el estado de la cartera.

    Campos principales:
    - valid:   Si la orden supera los checks (cash, minNotional, minQty, etc.).
    - reason:  Texto explicativo si no es válida.
    - intended_price:      Precio de referencia (p. ej., close de la barra).
    - exec_price_raw:      Precio tras slippage, ANTES de redondear al tick del exchange.
    - exec_price:          Precio final tras redondear al tick permitido.
    - qty_raw:             Cantidad ideal (antes de stepSize).
    - qty_rounded:         Cantidad final tras stepSize/minQty.
    - price_round_diff:    Diferencia por redondeo de precio (raw - final).
    - qty_round_diff:      Diferencia por redondeo de cantidad (raw - final).
    - slippage_bps:        Slippage aplicado (bps).
    - notional_before_round:  Notional con exec_price_raw * qty_raw (informativo).
    - notional_after_round:   Notional con exec_price * qty_rounded (base para fee_bps).
    """

    valid: bool
    reason: str | None
    intended_price: float
    exec_price_raw: float
    exec_price: float
    qty_raw: float
    qty_rounded: float
    price_round_diff: float
    qty_round_diff: float
    slippage_bps: float
    notional_before_round: float
    notional_after_round: float


# --------------------------------------------------------------------------------------
# Cartera: estado, ejecución simulada, reporting
# --------------------------------------------------------------------------------------
@dataclass
class Portfolio:
    """
    Estado y operaciones de la cartera para el backtest/paper.

    Parámetros de construcción
    --------------------------
    cash : float
        Efectivo inicial. (default 10_000.0)
    qty : float
        Cantidad inicial en el símbolo (default 0.0).
    symbol : str
        Símbolo del activo (ej. "BTCUSDT").
    fee_bps : float
        Comisión explícita en bps sobre el notional (ej. 1.0 => 0.01%).
    realized_pnl_net_fees : bool
        Si True, las ventas restan la fee del realized PnL (además de restarla del cash).
        Si False, el realized PnL no descuenta fees (solo el cash se ve afectado).
    rules : Optional[SymbolRules]
        Reglas del exchange (tickSize, stepSize, minNotional, etc.) usadas para redondeos/checks.
    slippage_bps : float
        Slippage en bps aplicado al precio de referencia (BUY sube, SELL baja).
    run_id : Optional[str]
        Identificador único de la ejecución (se propaga a metadatos de trades).

    Atributos derivados
    -------------------
    starting_cash : float
        Copia del cash inicial para calcular PnL total.
    last_price : Optional[float]
        Último precio marcado por mark_to_market; si None, equity = cash.
    trades : List[Trade]
        Lista de operaciones ejecutadas (BUY/SELL).
    _trade_meta : List[Dict[str, Any]]
        Metadatos paralelos (slippage/rounding/reglas/etc.) alineados con `trades`.
    _equity_curve : List[Tuple[pd.Timestamp, float]]
        Muestras de la curva de equity registradas por el `engine`.
    avg_price : float
        Precio medio de la posición actual (si qty>0).
    realized_pnl : float
        PnL realizado acumulado (sin o con fees, según `realized_pnl_net_fees`).
    """

    # --- Estado principal ---
    cash: float = 10_000.0
    qty: float = 0.0
    symbol: str = "BTCUSDT"
    fee_bps: float = 0.0

    # --- Estado derivado / tracking ---
    starting_cash: float = field(init=False)
    last_price: float | None = None
    trades: list[Trade] = field(default_factory=list)
    _trade_meta: list[dict[str, Any]] = field(default_factory=list)
    _equity_curve: list[tuple[pd.Timestamp, float]] | None = None

    # --- Posición y PnL ---
    avg_price: float = 0.0
    realized_pnl: float = 0.0
    realized_pnl_net_fees: bool = False

    # --- Reglas de exchange y slippage ---
    rules: SymbolRules | None = None
    slippage_bps: float = field(default_factory=lambda: float(settings.SLIPPAGE_BPS))

    # --- Identificador de ejecución ---
    run_id: str | None = None
    reports_dir: str | None = None

    # ----------------------------------------------------------------------------------
    # Ciclo de vida
    # ----------------------------------------------------------------------------------
    def __post_init__(self) -> None:
        """Guarda el cash inicial para calcular PnL total a futuro."""
        self.starting_cash = float(self.cash)

    # ----------------------------------------------------------------------------------
    # API de reglas y slippage
    # ----------------------------------------------------------------------------------
    def set_execution_rules(self, rules: SymbolRules, slippage_bps: float) -> None:
        """
        Inyecta reglas del exchange y el slippage del modelo de ejecución.
        Debe llamarse desde __main__.py antes del backtest.
        """
        self.rules = rules
        self.slippage_bps = float(slippage_bps)

    # ----------------------------------------------------------------------------------
    # Helpers de estado
    # ----------------------------------------------------------------------------------
    def equity(self, price: float | None = None) -> float:
        """
        Devuelve el valor total de la cartera:
          equity = cash + qty * (price o last_price)
        Si no hay precio, el equity es el cash (sin marcar a mercado).
        """
        p = self.last_price if price is None else price
        if p is None:
            return float(self.cash)
        return float(self.cash + self.qty * p)

    def mark_to_market(self, price: float) -> None:
        """
        Actualiza `last_price` con el precio observado (p. ej., el close de la barra).
        No cambia cash ni qty; solo afecta equity vía `equity()`.
        """
        self.last_price = float(price)

    def _record(self, tr: Trade, meta: dict[str, Any] | None = None) -> None:
        """
        Registra un trade y sus metadatos (alineados por índice).
        """
        self.trades.append(tr)
        self._trade_meta.append(meta or {})

    def _fee_from_notional(self, notional: float) -> float:
        """
        Calcula la comisión explícita:
          fee = notional * fee_bps / 10_000
        """
        return notional * (self.fee_bps / 10_000.0)

    # ----------------------------------------------------------------------------------
    # Snapshot de reglas para logging/export (tick/step/minNotional usados)
    # ----------------------------------------------------------------------------------
    def _rules_snapshot(self) -> dict[str, Any]:
        """
        Devuelve un dict con los parámetros relevantes de reglas usados en la ejecución.
        Soporta objetos `SymbolRules` con distintos nombres de atributo o dicts similares.
        """
        r = self.rules
        if r is None:
            return {"tickSize_used": None, "stepSize_used": None, "minNotional_used": None}

        def get_any(obj: Any, names: list[str]):
            for n in names:
                if hasattr(obj, n):
                    return getattr(obj, n)
                if isinstance(obj, dict) and n in obj:
                    return obj[n]
            return None

        tick = get_any(r, ["tick_size", "tickSize", "tick_size_step", "tick_size"])
        step = get_any(r, ["step_size", "stepSize", "step_size_step", "step_size"])
        minimo = get_any(r, ["min_notional", "minNotional", "notionalMin", "min_notional_value"])

        return {
            "tickSize_used": tick,
            "stepSize_used": step,
            "minNotional_used": minimo,
        }

    # ----------------------------------------------------------------------------------
    # Núcleo de ejecución: modelo (slippage + redondeos + checks)
    # ----------------------------------------------------------------------------------
    def _apply_execution_model(
        self,
        side: Literal["BUY", "SELL"],
        ref_price: float,
        qty_raw: float,
    ) -> ExecPreview:
        """
        Aplica el **modelo de ejecución** sin mutar estado:
          1) Aplica slippage (bps) al precio de referencia.
          2) Redondea precio (tickSize) y cantidad (stepSize) según reglas (si hay).
          3) Valida minQty/minNotional y cash (para BUY).
          4) Devuelve un `ExecPreview` con todos los detalles.

        Si algo no cuadra (qty<=0, precio<=0, falta cash, minNotional...), devuelve `valid=False`.
        """
        # Validación básica
        if qty_raw <= 0 or ref_price <= 0:
            return ExecPreview(
                valid=False,
                reason="qty/ref_price no válidos",
                intended_price=ref_price,
                exec_price_raw=ref_price,
                exec_price=ref_price,
                qty_raw=qty_raw,
                qty_rounded=0.0,
                price_round_diff=0.0,
                qty_round_diff=qty_raw,
                slippage_bps=self.slippage_bps,
                notional_before_round=0.0,
                notional_after_round=0.0,
            )

        # 1) Slippage
        slip = self.slippage_bps / 10_000.0
        exec_price_raw = ref_price * (1 + slip) if side == "BUY" else ref_price * (1 - slip)

        # 2) Redondeos según reglas del exchange (si existen)
        if self.rules is not None:
            p_dec, q_dec, ok = apply_exchange_rules(
                price=exec_price_raw, qty=qty_raw, rules=self.rules
            )
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

        # 3) Tras redondeo, la cantidad debe ser > 0
        if qty_rounded <= 0:
            return ExecPreview(
                valid=False,
                reason="qty_rounded == 0 tras stepSize",
                intended_price=ref_price,
                exec_price_raw=exec_price_raw,
                exec_price=exec_price,
                qty_raw=qty_raw,
                qty_rounded=qty_rounded,
                price_round_diff=price_round_diff,
                qty_round_diff=qty_round_diff,
                slippage_bps=self.slippage_bps,
                notional_before_round=notional_before,
                notional_after_round=notional_after,
            )

        # 4) Cash suficiente en BUY (incluye fee explícita)
        if side == "BUY":
            fee_factor = 1.0 + (self.fee_bps / 10_000.0)
            if notional_after * fee_factor > (self.cash + 1e-9):
                return ExecPreview(
                    valid=False,
                    reason="cash insuficiente (notional + fee)",
                    intended_price=ref_price,
                    exec_price_raw=exec_price_raw,
                    exec_price=exec_price,
                    qty_raw=qty_raw,
                    qty_rounded=qty_rounded,
                    price_round_diff=price_round_diff,
                    qty_round_diff=qty_round_diff,
                    slippage_bps=self.slippage_bps,
                    notional_before_round=notional_before,
                    notional_after_round=notional_after,
                )

        # 5) Reglas de exchange (minNotional/minQty) ya validadas en apply_exchange_rules
        if self.rules is not None and not ok:
            return ExecPreview(
                valid=False,
                reason="reglas exchange: minNotional/minQty",
                intended_price=ref_price,
                exec_price_raw=exec_price_raw,
                exec_price=exec_price,
                qty_raw=qty_raw,
                qty_rounded=qty_rounded,
                price_round_diff=price_round_diff,
                qty_round_diff=qty_round_diff,
                slippage_bps=self.slippage_bps,
                notional_before_round=notional_before,
                notional_after_round=notional_after,
            )

        # Si todo OK, devolvemos vista previa válida
        return ExecPreview(
            valid=True,
            reason=None,
            intended_price=ref_price,
            exec_price_raw=exec_price_raw,
            exec_price=exec_price,
            qty_raw=qty_raw,
            qty_rounded=qty_rounded,
            price_round_diff=price_round_diff,
            qty_round_diff=qty_round_diff,
            slippage_bps=self.slippage_bps,
            notional_before_round=notional_before,
            notional_after_round=notional_after,
        )

    # ----------------------------------------------------------------------------------
    # Órdenes de compra/venta (mutan estado si la ejecución es válida)
    # ----------------------------------------------------------------------------------
    def buy(self, ts: pd.Timestamp, qty: float, price: float, note: str = "") -> None:
        """
        Orden de compra:
          - Llama al modelo de ejecución.
          - Si es válida, descuenta cash (incluyendo la fee), aumenta qty y recalcula avg_price.
          - Registra trade con metadatos: slippage, redondeos, reglas, run_id, schema_version
        """
        if qty <= 0:
            return

        prev = self._apply_execution_model(side="BUY", ref_price=price, qty_raw=qty)
        if not prev.valid:
            logger.info(f"[BUY omitido] {prev.reason} | qty_raw={qty:.8f} ref={price:.2f}")
            return

        # Usamos los valores finales de ejecución (post slippage + redondeos)
        price = prev.exec_price
        qty = prev.qty_rounded

        # Notional y comisiones
        notional = qty * price
        fee = self._fee_from_notional(notional)
        total = notional + fee

        # Check defensivo extra (debería estar cubierto en preview)
        if self.cash + 1e-9 < total:
            logger.info("[BUY omitido] cash insuficiente en ejecución final")
            return

        # --- Actualización de estado ---
        self.cash -= total
        new_qty = self.qty + qty
        if self.qty <= 0:
            # Si no había posición, el avg_price es directamente el precio de ejecución
            self.avg_price = price
        else:
            # Recalcular promedio ponderado
            self.avg_price = (self.avg_price * self.qty + price * qty) / new_qty
        self.qty = new_qty
        self.last_price = price  # para que equity() refleje el nuevo nivel
        eq = self.equity(price)

        # --- Registro del trade ---
        tr = Trade(
            ts=ts,
            symbol=self.symbol,
            side="BUY",
            qty=qty,
            price=price,
            fee=fee,
            cash_after=float(self.cash),
            qty_after=float(self.qty),
            equity_after=float(eq),
            realized_pnl=0.0,
            cum_realized_pnl=self.realized_pnl,
            note=note,
        )

        # fee_bps “real” sobre el notional ejecutado tras redondeos (útil para auditoría)
        fee_bps_calc = 1e4 * (fee / prev.notional_after_round) if prev.notional_after_round else 0.0

        # Metadatos enriquecidos + snapshot de reglas + schema_version
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

    def sell(self, ts: pd.Timestamp, qty: float, price: float, note: str = "") -> None:
        """
        Orden de venta:
          - Verifica que hay suficiente cantidad (qty <= posición).
          - Aplica modelo de ejecución.
          - Si es válida, suma efectivo (menos fee), reduce qty y actualiza realized PnL.
          - Registra el trade con metadatos completos.
        """
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
            # Protección por si el redondeo sube ligeramente la cantidad
            qty = min(qty, self.qty)

        notional = qty * price
        fee = self._fee_from_notional(notional)

        # PnL realizado: (precio - avg_price) * qty  [con opción de restar fees]
        realized = (price - self.avg_price) * qty
        if self.realized_pnl_net_fees:
            realized -= fee
        self.realized_pnl += realized

        # Efectivo: entra notional menos fee
        self.cash += notional - fee

        # Reducir posición y resetear avg_price si cerramos
        self.qty -= qty
        if self.qty <= 1e-12:
            self.qty = 0.0
            self.avg_price = 0.0

        self.last_price = price
        eq = self.equity(price)

        tr = Trade(
            ts=ts,
            symbol=self.symbol,
            side="SELL",
            qty=qty,
            price=price,
            fee=fee,
            cash_after=float(self.cash),
            qty_after=float(self.qty),
            equity_after=float(eq),
            realized_pnl=realized,
            cum_realized_pnl=self.realized_pnl,
            note=note,
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

    # ----------------------------------------------------------------------------------
    # Sizing: calcular cantidad asequible dado un precio y un % del cash
    # ----------------------------------------------------------------------------------
    def affordable_qty(self, price: float, alloc_pct: float = 1.0) -> float:
        """
        Cantidad máxima que podemos comprar con un presupuesto = cash * alloc_pct,
        considerando comisión explícita (fee_bps). NO aplica reglas (tick/step).

        Se usa típicamente en la estrategia para decidir la qty "raw" que se
        intentará ejecutar; luego `_apply_execution_model` la ajustará a stepSize.
        """
        if price <= 0 or alloc_pct <= 0:
            return 0.0
        fee_mult = 1.0 + (self.fee_bps / 10_000.0)
        budget = self.cash * alloc_pct
        return max(0.0, budget / (price * fee_mult))

    # ----------------------------------------------------------------------------------
    # Reporting: equity curve, trades dataframe, summary
    # ----------------------------------------------------------------------------------
    def equity_curve_dataframe(self) -> pd.DataFrame:
        """
        Devuelve la curva de equity registrada por el engine como DataFrame:
          columnas: ["ts", "equity"], ordenada por tiempo.
        Si aún no hay puntos, devuelve un DataFrame vacío con esas columnas.
        """
        if not self._equity_curve:
            return pd.DataFrame(columns=["ts", "equity"])
        return (
            pd.DataFrame(self._equity_curve, columns=["ts", "equity"])
            .sort_values("ts")
            .reset_index(drop=True)
        )

    def trades_dataframe(self) -> pd.DataFrame:
        """
        Devuelve un DataFrame de trades combinando `Trade` + metadatos enriquecidos.

        Si hay metadatos (self._trade_meta) con la misma longitud que `trades`,
        se concatenan columna a columna. Si no, devuelve las columnas base.

        Columnas base (coinciden con dataclass Trade):
            ["ts","symbol","side","qty","price","fee",
             "cash_after","qty_after","equity_after",
             "realized_pnl","cum_realized_pnl","note"]

        Metadatos adicionales (si disponibles):
            ["intended_price","exec_price_raw","price_round_diff",
             "qty_raw","qty_rounded","qty_round_diff","slippage_bps",
             "notional_before_round","notional_after_round","rule_check",
             "run_id","fee_bps","tickSize_used","stepSize_used",
             "minNotional_used","schema_version"]
        """
        base_cols = [
            "ts",
            "symbol",
            "side",
            "qty",
            "price",
            "fee",
            "cash_after",
            "qty_after",
            "equity_after",
            "realized_pnl",
            "cum_realized_pnl",
            "note",
        ]

        # Si no hay trades aún, devolvemos cabecera completa vacía (base + extra),
        # porque los tests esperan esas columnas aunque no haya filas.
        if not self.trades:
            extra_cols = [
                "intended_price",
                "exec_price_raw",
                "price_round_diff",
                "qty_raw",
                "qty_rounded",
                "qty_round_diff",
                "slippage_bps",
                "notional_before_round",
                "notional_after_round",
                "rule_check",
                "run_id",
                "fee_bps",
                "schema_version",
                "tickSize_used",
                "stepSize_used",
                "minNotional_used",
            ]
            return pd.DataFrame(columns=base_cols + extra_cols)

        # Construimos el DF base a partir de los dataclasses Trade
        df = (
            pd.DataFrame([t.__dict__ for t in self.trades]).sort_values("ts").reset_index(drop=True)
        )

        # Si tenemos metadatos alineados, los añadimos; si no, devolvemos base ordenada
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
        """PnL total = equity() - starting_cash (usa last_price actual para MTM)."""
        return self.equity() - self.starting_cash

    def summary(self) -> dict:
        """
        Resumen compacto del estado actual:
          starting_cash, cash, qty, last_price, equity, realized_pnl, total_pnl, avg_price
        """
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
