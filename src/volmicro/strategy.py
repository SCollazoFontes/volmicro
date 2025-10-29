# src/volmicro/strategy.py
"""
Módulo de estrategias de trading.

La estrategia define la **lógica de decisión** en cada barra (qué hacer con el Portfolio).
El motor (`engine.run_engine`) llama:
    strategy.on_bar(bar, portfolio)
en cada barra, pasando:
    - `bar`: un objeto Bar con ts, open, high, low, close, volume, symbol.
    - `portfolio`: el estado actual de la cartera (cash, qty, etc.).

La estrategia puede ejecutar acciones como:
    portfolio.buy(...)
    portfolio.sell(...)
y opcionalmente tener un "hook" final `on_finish(portfolio)` para cerrar posiciones
o hacer limpieza.

En este archivo incluimos una estrategia trivial de ejemplo: **BuySecondBarStrategy**.
"""

from dataclasses import dataclass, field
from .portfolio import Portfolio
from .core import Bar


# ======================================================================================
# Estrategia de ejemplo: comprar en la segunda barra y cerrar al final
# ======================================================================================
@dataclass
class BuySecondBarStrategy:
    """
    Estrategia de demostración minimalista para validar el flujo completo del motor.

    Lógica:
    -------
    - Lleva un contador interno de barras (`_counter`).
    - En la segunda barra (i == 2):
        - Calcula cuánto puede comprar (`alloc_pct` del cash disponible).
        - Ejecuta un BUY a precio de cierre de la barra.
    - En el final (`on_finish`):
        - Si tiene una posición abierta, la cierra (SELL) al precio de cierre
          de la última barra procesada.

    Esta estrategia sirve como *test funcional* del motor y de los flujos
    de ejecución (buy/sell, fees, slippage, exportaciones...).
    """

    # --- Atributos internos ---
    _counter: int = field(default=0, init=False)   # contador de barras procesadas
    alloc_pct: float = 0.10                        # % del cash que se asigna al comprar
    _last_bar: Bar | None = field(default=None, init=False)  # referencia a la última barra

    # ------------------------------------------------------------------------------
    # on_bar: se ejecuta en cada barra del backtest
    # ------------------------------------------------------------------------------
    def on_bar(self, bar: Bar, portfolio: Portfolio) -> None:
        """
        Callback principal de la estrategia.

        Se llama una vez por barra con el objeto `Bar` y el `Portfolio` actual.

        Dentro puedes:
          - Inspeccionar el estado del portfolio (cash, qty, equity, etc.).
          - Tomar decisiones: comprar, vender, mantener.
          - Anotar trades con un `note` para logging y debugging.
        """
        # Incrementamos el contador de barras
        self._counter += 1
        # Guardamos la última barra vista (para poder cerrar al final)
        self._last_bar = bar

        # --- Lógica: comprar en la segunda barra ---
        if self._counter == 2:
            # Calculamos cuánta cantidad podemos comprar con alloc_pct del cash
            qty = portfolio.affordable_qty(price=bar.close, alloc_pct=self.alloc_pct)

            # Si la cantidad es positiva y no nula, ejecutamos la compra
            if qty > 0:
                portfolio.buy(
                    ts=bar.ts,
                    qty=qty,
                    price=bar.close,
                    note="Second bar buy (alloc %)",
                )

    # ------------------------------------------------------------------------------
    # on_finish: hook opcional que se ejecuta tras la última barra
    # ------------------------------------------------------------------------------
    def on_finish(self, portfolio: Portfolio) -> None:
        """
        Hook de cierre (opcional):
        Se ejecuta una sola vez tras procesar todas las barras.
        Útil para cerrar posiciones abiertas o exportar datos.

        En este caso, si aún tenemos una posición abierta, la vendemos
        al precio de cierre de la última barra.
        """
        if self._last_bar and portfolio.qty > 0:
            portfolio.sell(
                ts=self._last_bar.ts,
                qty=portfolio.qty,
                price=self._last_bar.close,
                note="Close on finish",
            )
