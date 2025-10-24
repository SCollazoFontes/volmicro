# src/volmicro/engine.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Iterable
from volmicro.base import Strategy, Order, Bar, Context
from volmicro.broker import SimBroker
from volmicro.portfolio import Portfolio

@dataclass
class _Ctx(Context):
    symbol: str
    _engine: "Engine"
    _last_bar: Optional[Bar] = None

    @property
    def now(self):
        return self._last_bar.ts if self._last_bar else None

    def buy(self, qty: float, tag: Optional[str] = None) -> None:
        self._engine._queue_order(Order(self.symbol, qty, "BUY", tag))

    def sell(self, qty: float, tag: Optional[str] = None) -> None:
        self._engine._queue_order(Order(self.symbol, qty, "SELL", tag))

    def position(self) -> float:
        return self._engine.portfolio.position_qty(self.symbol)

    def cash(self) -> float:
        return self._engine.portfolio.cash

    def last_price(self) -> float:
        if self._last_bar:
            return self._engine.portfolio.last_price(self.symbol, self._last_bar.close)
        return 0.0

    def equity(self) -> float:
        return self._engine.portfolio.equity

class Engine:
    """
    Reglas:
    - Las órdenes lanzadas en la barra t se ejecutan al OPEN de t+1.
    - Si termina el backtest con órdenes pendientes, se cancelan.
    """
    def __init__(self, strategy: Strategy, feed: Iterable[Bar], symbol: str,
                 starting_cash: float = 10_000.0, commission_per_trade: float = 0.0):
        self.strategy = strategy
        self.feed = iter(feed)
        self.symbol = symbol
        self.broker = SimBroker(commission_per_trade)
        self.portfolio = Portfolio(starting_cash)
        self._pending_for_next_open: list[Order] = []
        self._ctx = _Ctx(symbol=symbol, _engine=self)

    def _queue_order(self, order: Order) -> None:
        self._pending_for_next_open.append(order)

    def run(self) -> None:
        self.strategy.on_start(self._ctx)

        for bar in self.feed:
            # 1) entrar en la barra actual: ejecutar lo que quedó pendiente al OPEN actual
            fills = self.broker.on_next_bar_open(bar)
            for f in fills:
                self.portfolio.on_fill(f)

            # 2) marcar a mercado con el CLOSE de esta barra
            self.portfolio.mark_to_market(bar)

            # 3) dar la barra a la estrategia para que decida (puede no hacer nada)
            self._ctx._last_bar = bar
            self.strategy.on_bar(self._ctx, bar)

            # 4) enviar al broker las órdenes recién pedidas para que se ejecuten en la próxima barra
            for od in self._pending_for_next_open:
                self.broker.submit(od)
            self._pending_for_next_open.clear()

        # fin: limpiar pendientes y notificar stop
        self.broker.cancel_all()
        self.strategy.on_stop(self._ctx)
