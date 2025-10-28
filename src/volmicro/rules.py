from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Optional, Dict, Any

from . import settings
from .binance_client import BinanceClient


@dataclass(frozen=True)
class SymbolRules:
    symbol: str
    tick_size: Decimal           # incremento mínimo de precio
    step_size: Decimal           # incremento mínimo de cantidad
    min_qty: Optional[Decimal]   # cantidad mínima (si aplica)
    max_qty: Optional[Decimal]   # cantidad máxima (si aplica)
    min_notional: Optional[Decimal]  # valor mínimo de orden (precio*qty)
    raw_filters: Dict[str, Any]  # filtros completos por si queremos depurar

    def to_json(self) -> Dict[str, Any]:
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
    def from_json(d: Dict[str, Any]) -> "SymbolRules":
        return SymbolRules(
            symbol=d["symbol"],
            tick_size=Decimal(d["tick_size"]),
            step_size=Decimal(d["step_size"]),
            min_qty=Decimal(d["min_qty"]) if d.get("min_qty") is not None else None,
            max_qty=Decimal(d["max_qty"]) if d.get("max_qty") is not None else None,
            min_notional=Decimal(d["min_notional"]) if d.get("min_notional") is not None else None,
            raw_filters=d.get("raw_filters", {}),
        )


def _dec(x: str | float | int) -> Decimal:
    return Decimal(str(x))


def _floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    """
    Redondeo hacia abajo al múltiplo más cercano de 'step'.
    Evita pasar del tick/step permitido.
    """
    if step <= 0:
        return value
    # número de pasos enteros
    steps = (value / step).to_integral_value(rounding=ROUND_DOWN)
    return (steps * step).normalize()


def round_price(price: float | Decimal, tick_size: Decimal) -> Decimal:
    """Precio redondeado hacia abajo al tick permitido."""
    return _floor_to_step(_dec(price), tick_size)


def round_qty(qty: float | Decimal, step_size: Decimal) -> Decimal:
    """Cantidad redondeada hacia abajo al step permitido."""
    return _floor_to_step(_dec(qty), step_size)


def is_order_valid(price: Decimal, qty: Decimal,
                   min_notional: Optional[Decimal],
                   min_qty: Optional[Decimal]) -> bool:
    """
    Valida reglas mínimas básicas: notional y cantidad mínima.
    """
    if min_qty is not None and qty < min_qty:
        return False
    if min_notional is not None and (price * qty) < min_notional:
        return False
    return True


def _parse_symbol_rules_from_exchange_info(symbol: str, ex_info: Dict[str, Any]) -> SymbolRules:
    """Extrae tickSize, stepSize, minQty, maxQty, minNotional de exchangeInfo."""
    # Buscar el símbolo
    syminfo = None
    for s in ex_info.get("symbols", []):
        if s.get("symbol") == symbol:
            syminfo = s
            break
    if syminfo is None:
        raise ValueError(f"Símbolo {symbol} no encontrado en exchangeInfo")

    tick_size = None
    step_size = None
    min_qty = None
    max_qty = None
    min_notional = None

    filters = syminfo.get("filters", [])
    raw_filters = {f.get("filterType"): f for f in filters}

    for f in filters:
        ftype = f.get("filterType")
        if ftype == "PRICE_FILTER":
            tick_size = _dec(f["tickSize"])
        elif ftype in ("LOT_SIZE", "MARKET_LOT_SIZE"):
            # LOT_SIZE: para órdenes limit; MARKET_LOT_SIZE: para market (en SPOT a veces aparece)
            step_size = _dec(f["stepSize"])
            # minQty/maxQty pueden estar en LOT_SIZE
            if "minQty" in f:
                min_qty = _dec(f["minQty"])
            if "maxQty" in f:
                max_qty = _dec(f["maxQty"])
        elif ftype in ("NOTIONAL", "MIN_NOTIONAL"):
            # Binance Spot moderno usa "NOTIONAL" con "minNotional"
            # Algunos entornos aún exponen "MIN_NOTIONAL"
            if "minNotional" in f:
                min_notional = _dec(f["minNotional"])

    if tick_size is None or step_size is None:
        raise ValueError(f"Faltan PRICE_FILTER/LOT_SIZE para {symbol}: tick_size={tick_size}, step_size={step_size}")

    return SymbolRules(
        symbol=symbol,
        tick_size=tick_size,
        step_size=step_size,
        min_qty=min_qty,
        max_qty=max_qty,
        min_notional=min_notional,
        raw_filters=raw_filters,
    )


def fetch_symbol_rules(symbol: str, testnet: bool) -> SymbolRules:
    """
    Llama a Binance y devuelve las reglas del símbolo.
    Usa el cliente del proyecto (mismo testnet/mainnet que settings).
    """
    client = BinanceClient(testnet=testnet)
    # binance-connector (Spot) -> exchange_info(symbol="BTCUSDT")
    ex_info = client.client.spot().exchange_info(symbol=symbol) if hasattr(client.client, "spot") else client.client.exchange_info(symbol=symbol)
    return _parse_symbol_rules_from_exchange_info(symbol, ex_info)


def _rules_cache_path(symbol: str) -> Path:
    """Ruta al fichero de cache JSON del símbolo en settings.RULES_DIR."""
    return Path(settings.RULES_DIR) / f"{symbol}_rules.json"


def load_symbol_rules(symbol: str, testnet: bool,
                      use_cache: bool = True, refresh: bool = False) -> SymbolRules:
    """
    Carga reglas desde cache (rules/<symbol>_rules.json) o las descarga de Binance.
    - use_cache=True: intenta leer del disco si existe
    - refresh=True : fuerza a descargar de Binance y sobreescribir cache
    """
    cache_path = _rules_cache_path(symbol)
    if use_cache and cache_path.exists() and not refresh:
        with open(cache_path, "r") as f:
            data = json.load(f)
        return SymbolRules.from_json(data)

    rules = fetch_symbol_rules(symbol, testnet=testnet)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump(rules.to_json(), f, indent=4)
    return rules


# === Helpers de integración a usar desde portfolio/engine ===

def apply_exchange_rules(price: float | Decimal,
                         qty: float | Decimal,
                         rules: SymbolRules) -> tuple[Decimal, Decimal, bool]:
    """
    Redondea precio/cantidad según tick/step y valida minQty/minNotional.
    Devuelve (price_rounded, qty_rounded, is_valid).
    """
    p = round_price(price, rules.tick_size)
    q = round_qty(qty, rules.step_size)
    return p, q, is_order_valid(p, q, rules.min_notional, rules.min_qty)
