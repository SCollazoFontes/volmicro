# src/volmicro/broker.py
from __future__ import annotations
from typing import List
from volmicro.base import Order, Fill, Bar

class SimBroker:
    """
    Ejecuta las órdenes pendientes al OPEN de la siguiente barra.
    Comisión fija opcional por operación.
    """
    def __init__(self, commission_per_trade: float = 0.0):
        self._pending: List[Order] = []
        self.commission = float(commission_per_trade)

    def submit(self, order: Order) -> None:
        # El engine llama a esto cuando la estrategia pide buy/sell en la barra t.
        # Aquí solo guardamos la orden para ejecutarla en la próxima barra.
        self._pending.append(order)

    def on_next_bar_open(self, bar: Bar) -> List[Fill]:
        """
        Al entrar en la barra t+1, convertimos TODAS las órdenes pendientes
        en ejecuciones (fills) al precio de apertura (bar.open).
        """
        if not self._pending:
            return []
        fills: List[Fill] = []
        for od in self._pending:
            fills.append(Fill(
                symbol=od.symbol,
                qty=od.qty,
                price=bar.open,  # regla clave: ejecuto a la APERTURA actual
                side=od.side,
                ts=bar.ts,
                fee=self.commission,
                tag=od.tag,
            ))
        self._pending.clear()
        return fills

    def cancel_all(self) -> None:
        # Por si acaba el backtest con órdenes sin ejecutar
        self._pending.clear()
