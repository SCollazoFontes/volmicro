# src/volmicro/portfolio.py
from dataclasses import dataclass

@dataclass
class Portfolio:
    cash: float = 10000.0   # saldo inicial
    qty: float = 0.0         # posición (unidades)
    last_price: float = 0.0  # último precio de marcado

    @property
    def equity(self) -> float:
        # Valor total = efectivo + valor de la posición marcada a mercado
        return self.cash + self.qty * self.last_price

    def mark(self, price: float) -> None:
        """Actualiza el último precio para calcular equity."""
        self.last_price = float(price)

    def buy(self, qty: float, price: float) -> None:
        """Compra qty al precio dado (modelo instantáneo sin comisiones)."""
        cost = float(qty) * float(price)
        if cost > self.cash:
            # compra parcial si no alcanza el efectivo
            qty = self.cash / float(price)
            cost = qty * float(price)
        self.cash -= cost
        self.qty += qty
        self.last_price = float(price)

    def sell(self, qty: float, price: float) -> None:
        """Vende qty al precio dado (modelo instantáneo sin comisiones)."""
        qty = min(qty, self.qty)
        proceeds = float(qty) * float(price)
        self.cash += proceeds
        self.qty -= qty
        self.last_price = float(price)
