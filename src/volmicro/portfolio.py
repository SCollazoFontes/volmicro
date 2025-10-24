# src/volmicro/portfolio.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict
from volmicro.base import Fill, Bar

@dataclass
class _Pos:
    qty: float = 0.0
    avg_price: float = 0.0

class Portfolio:
    def __init__(self, starting_cash: float):
        self.cash = float(starting_cash)     # dinero líquido
        self._pos: Dict[str, _Pos] = {}      # posiciones por símbolo
        self._last_price: Dict[str, float] = {}
        self.equity = float(starting_cash)   # valor total (cash + posiciones)

    # --- se llama cuando el broker “ejecuta” una orden (Fill) ---
    def on_fill(self, fill: Fill) -> None:
        p = self._pos.setdefault(fill.symbol, _Pos())
        signed_qty = fill.qty if fill.side == "BUY" else -fill.qty

        # Impacto en caja: pagas (o recibes) precio*qty y pagas fee
        self.cash -= signed_qty * fill.price + fill.fee

        # Actualizar cantidad y precio medio
        new_qty = p.qty + signed_qty
        if p.qty == 0.0:
            p.avg_price = fill.price
        elif (p.qty >= 0 and signed_qty >= 0) or (p.qty <= 0 and signed_qty <= 0):
            # Aumentas posición en la misma dirección -> nueva media ponderada
            p.avg_price = (
                abs(p.qty) * p.avg_price + abs(signed_qty) * fill.price
            ) / (abs(p.qty) + abs(signed_qty))
        else:
            # Estás reduciendo/invirtiendo la posición
            if (p.qty > 0 and new_qty < 0) or (p.qty < 0 and new_qty > 0):
                # cruzaste a la dirección opuesta -> nueva media al último precio
                p.avg_price = fill.price

        p.qty = new_qty

    # --- marcar a mercado con la barra actual (usa el CLOSE) ---
    def mark_to_market(self, bar: Bar) -> None:
        self._last_price[bar.symbol] = bar.close
        pos_val = 0.0
        for sym, p in self._pos.items():
            price = self._last_price.get(sym, bar.close)
            pos_val += p.qty * price
        self.equity = self.cash + pos_val

    # --- consultas sencillas ---
    def position_qty(self, symbol: str) -> float:
        return self._pos.get(symbol, _Pos()).qty

    def last_price(self, symbol: str, fallback: float) -> float:
        return self._last_price.get(symbol, fallback)
