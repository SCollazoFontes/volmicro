# src/volmicro/trades.py
"""
Estructura básica que representa una operación ejecutada (trade).

Cada vez que el portfolio ejecuta una orden `buy()` o `sell()`, crea un objeto
`Trade` que recoge los datos esenciales del momento de la ejecución: precio,
cantidad, fee, PnL, etc.

Los `Trade` se almacenan en `Portfolio.trades`, y luego se exportan a CSV a
través de `Portfolio.trades_dataframe()` junto con metadatos adicionales
(slippage, reglas de Binance, run_id, etc.).
"""

from dataclasses import dataclass
from typing import Literal, Optional
import pandas as pd

# Tipo literal que restringe `side` a “BUY” o “SELL”
Side = Literal["BUY", "SELL"]


@dataclass
class Trade:
    """
    Representa una transacción individual (compra o venta).

    Campos
    ------
    ts : pd.Timestamp
        Marca temporal exacta del trade (suele coincidir con bar.ts).

    symbol : str
        Símbolo del activo (por ejemplo, "BTCUSDT" o "ETHUSDT").

    side : Literal["BUY", "SELL"]
        Dirección de la operación.

    qty : float
        Cantidad ejecutada (ya ajustada a stepSize de Binance).

    price : float
        Precio de ejecución (ya ajustado a tickSize y slippage aplicados).

    fee : float
        Comisión pagada por la operación (en la misma divisa que el símbolo base).

    cash_after : float
        Efectivo disponible en el portfolio tras la operación.

    qty_after : float
        Cantidad de posición que queda abierta después del trade.

    equity_after : float
        Valor total (cash + posición mark-to-market) justo después de ejecutar.

    realized_pnl : float
        PnL realizado con esta operación (solo en ventas, normalmente).

    cum_realized_pnl : float
        PnL realizado acumulado en el portfolio hasta este momento.

    note : str
        Texto libre opcional para registrar contexto (“Second bar buy”, “Close on finish”, etc.)

    Notas
    -----
    - Esta clase **no contiene** slippage, tick/step o validaciones de exchange:
      esos datos se guardan aparte en los metadatos paralelos (`Portfolio._trade_meta`).
    - `Portfolio._record(trade, meta)` combina ambos mundos para la exportación.
    - Los tests (`tests/test_trades_schema.py`) validan que el CSV de trades
      resultante contenga todas las columnas esperadas.
    """

    ts: pd.Timestamp
    symbol: str
    side: Side
    qty: float
    price: float
    fee: float
    cash_after: float
    qty_after: float
    equity_after: float

    # Campos opcionales o derivados
    realized_pnl: float = 0.0        # PnL realizado en este trade concreto
    cum_realized_pnl: float = 0.0    # PnL realizado acumulado total
    note: str = ""                   # comentario o descripción
