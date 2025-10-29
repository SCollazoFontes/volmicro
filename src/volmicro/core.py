# src/volmicro/core.py
"""
Tipos de datos “núcleo” compartidos por varios módulos.

Por ahora incluye:
- `Bar`: estructura inmutable que representa una vela/barra de mercado normalizada
         (timestamp + OHLCV + symbol). Es el tipo que recorre el engine y
         consumen las estrategias.
"""

from dataclasses import dataclass
from typing import Any
from pandas import Timestamp


@dataclass(frozen=True)
class Bar:
    """
    Vela/Barra de datos normalizada y **inmutable**.

    Campos
    ------
    ts     : Timestamp (pandas.Timestamp tz-aware, idealmente UTC).
             *Suele venir del índice del DataFrame de klines.*
    open   : float  – precio de apertura de la barra.
    high   : float  – máximo de la barra.
    low    : float  – mínimo de la barra.
    close  : float  – cierre de la barra (se usa para MTM y ejecuciones simuladas).
    volume : float  – volumen de la barra.
    symbol : str    – símbolo del activo (ej. "BTCUSDT").

    Notas de diseño
    ---------------
    - `frozen=True` ⇒ inmutable: evita mutaciones accidentales durante el backtest
      y hace más seguro el paso por capas (engine/estrategia).
    - `ts` está tipado como `Any` para flexibilizar (p. ej., objetos Timestamp),
      pero en la práctica **debería** ser `pandas.Timestamp` tz-aware (UTC).
      En el feed (`binance_feed.iter_bars`) nos aseguramos de eso.
    """
    ts: Any            # preferiblemente: pandas.Timestamp (tz-aware, UTC)
    open: float
    high: float
    low: float
    close: float
    volume: float
    symbol: str
