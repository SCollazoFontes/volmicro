# src/volmicro/binance_feed.py
"""
Módulo de *feed* (fuente de datos) que convierte un DataFrame de OHLCV en una
secuencia de objetos `Bar` (inmutables) consumibles por el `engine`.

¿Por qué este paso intermedio?
- Aísla el formato "crudo" de la descarga (DataFrame) del formato "operativo" (Bar).
- Permite validar y normalizar **una sola vez** (tipos, índice, orden, duplicados).
- Hace el loop del motor (`engine.run_engine`) más limpio y predecible.

Interfaz:
---------
- `iter_bars(df: pd.DataFrame, symbol: str) -> Iterator[Bar]`

  * df: DataFrame con índice de tiempo (tz-aware, UTC) y columnas:
        ["open", "high", "low", "close", "volume"] en float.
        Este df es el que devuelve `BinanceClient.get_klines(...)`.
  * symbol: símbolo del activo (e.g., "BTCUSDT") que se grabará en cada Bar.

Validaciones:
-------------
- Índice debe ser **tz-aware UTC** (evita errores de huso horario aguas abajo).
- Columnas requeridas presentes.
- Orden temporal ascendente y sin duplicados.
- Cast explícito a float64 por consistencia numérica.

Salida:
-------
- Genera objetos `Bar` (dataclass inmutable con campos: ts, open, high, low, close, volume, symbol)
  uno por cada fila del DataFrame, *iterando en orden temporal*.
"""

from __future__ import annotations

from typing import Iterator, Iterable
import pandas as pd

from .core import Bar


# --------------------------------------------------------------------------------------
# Utilidades internas (pequeñas comprobaciones defensivas para robustez del pipeline)
# --------------------------------------------------------------------------------------

_REQUIRED_COLS = {"open", "high", "low", "close", "volume"}


def _ensure_required_columns(df: pd.DataFrame) -> None:
    """
    Verifica que el DataFrame contiene las columnas OHLCV mínimas.
    Lanza ValueError con detalle si falta algo.
    """
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"El DataFrame del feed no tiene columnas requeridas: {sorted(missing)}")


def _ensure_tz_aware_utc(df: pd.DataFrame) -> None:
    """
    Exige que el índice sea tz-aware (idealmente UTC). Si no lo es, avisamos.
    """
    if df.index.tz is None:  # pandas marca tz-aware en .tz
        raise ValueError("El índice del DataFrame debe ser tz-aware (UTC).")


def _ensure_sorted_unique_index(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ordena por índice temporal de forma ascendente y elimina duplicados.
    Devuelve una *vista* (o copia) ordenada y sin duplicados.
    """
    # Elimina duplicados (si un openTime aparece dos veces, nos quedamos con la primera)
    df2 = df[~df.index.duplicated(keep="first")]
    # Ordena temporalmente por las dudas (el cliente ya lo suele traer ordenado)
    df2 = df2.sort_index()
    return df2


def _ensure_float64(df: pd.DataFrame) -> pd.DataFrame:
    """
    Fuerza dtypes float64 en las columnas OHLCV, para consistencia en cálculos/formatos.
    """
    return df.astype(
        {
            "open": "float64",
            "high": "float64",
            "low": "float64",
            "close": "float64",
            "volume": "float64",
        },
        copy=False,
    )


# ------------------------------------------------------
# API pública: generador de barras a partir de un DataFrame
# ------------------------------------------------------

def iter_bars(df: pd.DataFrame, symbol: str) -> Iterator[Bar]:
    """
    Itera un DataFrame OHLCV y va generando `Bar` uno a uno.

    Parámetros
    ----------
    df : pd.DataFrame
        DataFrame con índice temporal tz-aware (UTC) y columnas
        ["open","high","low","close","volume"] en float.
        Suele provenir de `BinanceClient.get_klines(...)`.
    symbol : str
        Símbolo del activo (ej., "BTCUSDT"). Se incrusta en cada Bar.

    Yields
    ------
    Bar
        Dataclass inmutable con:
          - ts:   pd.Timestamp (UTC)
          - open, high, low, close, volume: float
          - symbol: str
    """
    # 1) Validaciones básicas
    _ensure_required_columns(df)
    _ensure_tz_aware_utc(df)

    # 2) Normalizaciones de seguridad
    df = _ensure_sorted_unique_index(df)
    df = _ensure_float64(df)

    # 3) Iteración en orden temporal, creando `Bar` por fila
    #    - iterrows() devuelve (index, row)
    #    - row["col"] es un escalar; convertimos a float explícito
    for ts, row in df.iterrows():
        yield Bar(
            ts=ts,                       # pd.Timestamp tz-aware (UTC)
            symbol=symbol,               # "BTCUSDT" u otro
            open=float(row["open"]),     # cast defensivo
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
        )
