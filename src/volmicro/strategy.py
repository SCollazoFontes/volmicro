from dataclasses import dataclass, field
from .portfolio import Portfolio
from .core import Bar

@dataclass
class BuySecondBarStrategy:
    _counter: int = field(default=0, init=False)
    alloc_pct: float = 0.10
    _last_bar: Bar | None = field(default=None, init=False)

    def on_bar(self, bar: Bar, portfolio: Portfolio) -> None:
        self._counter += 1
        self._last_bar = bar
        if self._counter == 2:
            qty = portfolio.affordable_qty(price=bar.close, alloc_pct=self.alloc_pct)
            if qty > 0:
                portfolio.buy(ts=bar.ts, qty=qty, price=bar.close, note="Second bar buy (alloc %)")

    # Hook opcional
    def on_finish(self, portfolio: Portfolio) -> None:
        if self._last_bar and portfolio.qty > 0:
            portfolio.sell(ts=self._last_bar.ts, qty=portfolio.qty, price=self._last_bar.close, note="Close on finish")
