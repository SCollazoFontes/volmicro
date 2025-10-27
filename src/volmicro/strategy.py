# src/volmicro/strategy.py
from dataclasses import dataclass, field
from .portfolio import Portfolio
from .core import Bar

@dataclass
class BuySecondBarStrategy:
    _counter: int = field(default=0, init=False)

    def on_bar(self, bar: Bar, portfolio: Portfolio) -> None:
        self._counter += 1
        if self._counter == 2:
            # compra 1 unidad al close de la 2ª barra
            portfolio.buy(ts=bar.ts, qty=1.0, price=bar.close, note="Second bar buy")
