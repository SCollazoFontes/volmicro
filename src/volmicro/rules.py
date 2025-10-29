# src/volmicro/rules.py
"""
Reglas del exchange (Binance Spot) y utilidades de redondeo/validación.

Objetivos del módulo
--------------------
1) Obtener desde Binance (o caché local) los **filtros** de trading por símbolo:
   - PRICE_FILTER:  tick_size     (incremento mínimo de precio)
   - LOT_SIZE:      step_size     (incremento mínimo de cantidad), min_qty, max_qty
   - NOTIONAL:      min_notional  (notional mínimo = price * qty)
2) Representarlos en una estructura inmutable (`SymbolRules`) cómoda de usar.
3) Proveer *helpers* para:
   - Redondear `price` a `tick_size` (hacia abajo).
   - Redondear `qty` a `step_size`  (hacia abajo).
   - Validar `min_qty` y `min_notional`.
4) Cachear en disco (en `rules/<SYMBOL>_rules.json`) para evitar hits innecesarios a la API.

Integración
-----------
- `__main__.py`: llama `load_symbol_rules(...)` al arrancar y lo inyecta en
    `Portfolio.set_execution_rules(...)`.
- `Portfolio._apply_execution_model(...)`: usa `apply_exchange_rules(price, qty, rules)` para
    redondear y validar `minQty/minNotional` antes de ejecutar.

Decisiones
----------
- Redondeos son **floor** (ROUND_DOWN) al múltiplo permitido para no arriesgar rechazo del exchange.
- `SymbolRules` es **dataclass frozen** (inmutable) => seguridad y trazabilidad.
- Cache en JSON con strings para Decimals (sin pérdida de precisión).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from typing import Any

from . import settings
from .binance_client import BinanceClient


# ======================================================================================
# Representación de reglas por símbolo
# ======================================================================================
@dataclass(frozen=True)
class SymbolRules:
    """
    Reglas relevantes para un `symbol` en Binance Spot.

    Campos
    ------
    symbol       : str
    tick_size    : Decimal       (PRICE_FILTER.tickSize)
    step_size    : Decimal       (LOT_SIZE.stepSize o MARKET_LOT_SIZE.stepSize)
    min_qty      : Optional[Decimal]  (LOT_SIZE.minQty, si existe)
    max_qty      : Optional[Decimal]  (LOT_SIZE.maxQty, si existe)
    min_notional : Optional[Decimal]  (NOTIONAL.minNotional o MIN_NOTIONAL.minNotional)
    raw_filters  : Dict[str, Any]     (copia cruda para debugging/auditoría)
    """

    symbol: str
    tick_size: Decimal
    step_size: Decimal
    min_qty: Decimal | None
    max_qty: Decimal | None
    min_notional: Decimal | None
    raw_filters: dict[str, Any]

    # Serialización a JSON (guardamos Decimals como strings para no perder precisión)
    def to_json(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "tick_size": str(self.tick_size),
            "step_size": str(self.step_size),
            "min_qty": str(self.min_qty) if self.min_qty is not None else None,
            "max_qty": str(self.max_qty) if self.max_qty is not None else None,
            "min_notional": str(self.min_notional) if self.min_notional is not None else None,
            "raw_filters": self.raw_filters,
        }

    @staticmethod
    def from_json(d: dict[str, Any]) -> SymbolRules:
        # Inversa de to_json
        return SymbolRules(
            symbol=d["symbol"],
            tick_size=Decimal(d["tick_size"]),
            step_size=Decimal(d["step_size"]),
            min_qty=Decimal(d["min_qty"]) if d.get("min_qty") is not None else None,
            max_qty=Decimal(d["max_qty"]) if d.get("max_qty") is not None else None,
            min_notional=Decimal(d["min_notional"]) if d.get("min_notional") is not None else None,
            raw_filters=d.get("raw_filters", {}),
        )


# ======================================================================================
# Utilidades de precisión y redondeo hacia abajo (floor al múltiplo más cercano)
# ======================================================================================


def _dec(x: str | float | int | Decimal) -> Decimal:
    """
    Normaliza a Decimal de forma segura.
    """
    return Decimal(str(x))


def _floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    """
    Redondeo **hacia abajo** (ROUND_DOWN) al múltiplo más cercano de `step`.

    Ejemplo: value=1.234, step=0.01  => 1.23
             value=100,   step=5     => 100
             value=102,   step=5     => 100
    """
    if step <= 0:
        return value
    steps = (value / step).to_integral_value(rounding=ROUND_DOWN)  # número entero de pasos
    return (steps * step).normalize()  # .normalize() quita ceros sobrantes


def round_price(price: float | Decimal, tick_size: Decimal) -> Decimal:
    """Redondea el precio hacia abajo al tick permitido por el exchange."""
    return _floor_to_step(_dec(price), tick_size)


def round_qty(qty: float | Decimal, step_size: Decimal) -> Decimal:
    """Redondea la cantidad hacia abajo al step permitido por el exchange."""
    return _floor_to_step(_dec(qty), step_size)


def is_order_valid(
    price: Decimal,
    qty: Decimal,
    min_notional: Decimal | None,
    min_qty: Decimal | None,
) -> bool:
    """
    Valida reglas mínimas básicas:
      - min_qty:      qty >= min_qty (si aplica)
      - min_notional: price * qty >= min_notional (si aplica)

    Devuelve True si pasa todos los checks.
    """
    if min_qty is not None and qty < min_qty:
        return False
    if min_notional is not None and (price * qty) < min_notional:
        return False
    return True


# ======================================================================================
# Parseo de exchange_info de Binance a SymbolRules
# ======================================================================================


def _parse_symbol_rules_from_exchange_info(symbol: str, ex_info: dict[str, Any]) -> SymbolRules:
    """
    Extrae tickSize, stepSize, minQty, maxQty y minNotional de la respuesta `exchangeInfo`.

    Estructura típica:
    {
      "symbols": [
        {
          "symbol": "BTCUSDT",
          "filters": [
            {"filterType":"PRICE_FILTER", "tickSize":"0.10", ...},
            {"filterType":"LOT_SIZE",     "stepSize":"0.00001000",
                "minQty":"0.00001000","maxQty":"9000.00000000"},
            {"filterType":"NOTIONAL",     "minNotional":"5.00"},
            ...
          ]
        }
      ]
    }
    """
    # 1) Buscar la entrada del símbolo
    syminfo = None
    for s in ex_info.get("symbols", []):
        if s.get("symbol") == symbol:
            syminfo = s
            break
    if syminfo is None:
        raise ValueError(f"Símbolo {symbol} no encontrado en exchangeInfo")

    # 2) Extraer filtros
    tick_size: Decimal | None = None
    step_size: Decimal | None = None
    min_qty: Decimal | None = None
    max_qty: Decimal | None = None
    min_notional: Decimal | None = None

    filters = syminfo.get("filters", [])
    raw_filters = {f.get("filterType"): f for f in filters}

    for f in filters:
        ftype = f.get("filterType")
        if ftype == "PRICE_FILTER":
            tick_size = _dec(f["tickSize"])
        elif ftype in ("LOT_SIZE", "MARKET_LOT_SIZE"):
            step_size = _dec(f["stepSize"])
            if "minQty" in f:
                min_qty = _dec(f["minQty"])
            if "maxQty" in f:
                max_qty = _dec(f["maxQty"])
        elif ftype in ("NOTIONAL", "MIN_NOTIONAL"):
            if "minNotional" in f:
                min_notional = _dec(f["minNotional"])

    if tick_size is None or step_size is None:
        msg = (
            f"Faltan PRICE_FILTER/LOT_SIZE para {symbol}: "
            f"tick_size={tick_size}, step_size={step_size}"
        )
        raise ValueError(msg)

    return SymbolRules(
        symbol=symbol,
        tick_size=tick_size,
        step_size=step_size,
        min_qty=min_qty,
        max_qty=max_qty,
        min_notional=min_notional,
        raw_filters=raw_filters,
    )


# ======================================================================================
# Acceso a Binance y cache local
# ======================================================================================


def fetch_symbol_rules(symbol: str, testnet: bool) -> SymbolRules:
    """
    Descarga `exchangeInfo` de Binance y lo parsea a `SymbolRules`.
    Usa el mismo entorno (testnet/mainnet) que el resto del proyecto.
    """
    client = BinanceClient(testnet=testnet)
    # En binance-connector moderno, `Spot.exchange_info` acepta symbol=...
    ex_info = client.exchange_info(symbol=symbol)
    return _parse_symbol_rules_from_exchange_info(symbol, ex_info)


def _rules_cache_path(symbol: str) -> Path:
    """
    Devuelve la ruta de la cache JSON para el símbolo, dentro de settings.RULES_DIR.
    Ej.: rules/BTCUSDT_rules.json
    """
    return Path(settings.RULES_DIR) / f"{symbol}_rules.json"


def load_symbol_rules(
    symbol: str,
    testnet: bool,
    use_cache: bool = True,
    refresh: bool = False,
) -> SymbolRules:
    """
    Carga reglas desde cache (si existe y `use_cache=True`) o las descarga de Binance.

    - use_cache=True: prioriza leer rules/<symbol>_rules.json si existe.
    - refresh=True  : ignora cache, fuerza descarga y sobrescribe.

    Flujo:
      1) Si hay cache válida y no pedimos refresh => cargar y devolver.
      2) Si no, llamar `fetch_symbol_rules(...)`, guardar en cache y devolver.
    """
    cache_path = _rules_cache_path(symbol)

    if use_cache and cache_path.exists() and not refresh:
        with open(cache_path) as f:
            data = json.load(f)
        return SymbolRules.from_json(data)

    rules = fetch_symbol_rules(symbol, testnet=testnet)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump(rules.to_json(), f, indent=4)
    return rules


# ======================================================================================
# Helper de integración: aplicar reglas a (price, qty)
# ======================================================================================


def apply_exchange_rules(
    price: float | Decimal,
    qty: float | Decimal,
    rules: SymbolRules,
) -> tuple[Decimal, Decimal, bool]:
    """
    Redondea precio y cantidad a los mínimos permitidos y valida minQty/minNotional.

    Devuelve:
      (price_rounded: Decimal, qty_rounded: Decimal, is_valid: bool)
    """
    p = round_price(price, rules.tick_size)
    q = round_qty(qty, rules.step_size)
    return p, q, is_order_valid(p, q, rules.min_notional, rules.min_qty)
