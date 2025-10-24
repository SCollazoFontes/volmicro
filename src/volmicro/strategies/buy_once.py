# src/volmicro/strategies/buy_once.py
from __future__ import annotations
from ..base import Strategy, Bar

class BuyOnce(Strategy):
    def __init__(self, qty: float = 1.0):
        self.qty = float(qty)
        self._done = False

    def on_start(self, ctx) -> None:
        # nada al empezar
        pass

    def on_bar(self, ctx, bar: Bar) -> None:
        if not self._done:
            # acción en la barra t: pido comprar; se ejecutará al OPEN de t+1
            ctx.buy(self.qty, tag="first_entry")
            self._done = True
        else:
            # NO hago nada: no llamo ni a buy() ni a sell()
            pass

    def on_stop(self, ctx) -> None:
        # nada al terminar
        pass
