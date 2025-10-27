# src/volmicro/strategy.py
from dataclasses import dataclass

@dataclass
class BuySecondBarStrategy:
    _count: int = 0
    _done: bool = False

    def on_start(self, portfolio) -> None:
        # opcional: logs/ inicialización
        pass

    def on_bar(self, bar, portfolio) -> None:
        """Compra 1 unidad en la segunda barra y no vuelve a operar."""
        self._count += 1
        if not self._done and self._count == 2:
            portfolio.buy(qty=1.0, price=bar.close)
            self._done = True
