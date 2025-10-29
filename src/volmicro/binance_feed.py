# src/volmicro/binance_feed.py
"""
Generador de barras (`Bar`) a partir de un DataFrame OHLCV.

Novedad:
- Robustez del índice temporal: si el DataFrame llega con RangeIndex o sin tz,
  se convierte a `DatetimeIndex` en UTC a partir de `open_time` (ms) o `time`.
- Esto evita errores tipo: AttributeError: 'RangeIndex' object has no attribute 'tz'

Contrato esperado del DataFrame de entrada (mínimo):
- Columnas numéricas: open, high, low, close, volume
- Marca temporal: preferiblemente índice DatetimeIndex UTC; si no,
  se usará la columna `open_time` (milisegundos desde epoch) o `time`.

Salida:
- Iterador de objetos `Bar` (definidos en core.py) en orden cronológico.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd

from .core import Bar

# --------------------------------------------------------------------------------------
# Helpers de normalización temporal
# --------------------------------------------------------------------------------------


def _ensure_datetime_index_utc(df: pd.DataFrame) -> pd.DataFrame:
    """
    Garantiza que `df`:
      1) Tiene un DatetimeIndex.
      2) Está en zona horaria UTC.
      3) Está ordenado por índice.

    Estrategia:
    - Si el índice YA es DatetimeIndex:
        - Si no tiene tz, localizamos a UTC.
        - Si tiene tz, convertimos a UTC.
    - Si NO es DatetimeIndex:
        - Si existe 'open_time' → interpretamos como milisegundos desde epoch.
        - Si existe 'time'      → intentamos parsear como datetime.
        - Si no existe ninguna → error claro.
    """
    if isinstance(df.index, pd.DatetimeIndex):
        # Asegurar tz UTC
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        else:
            df.index = df.index.tz_convert("UTC")
        return df.sort_index()

    # No es DatetimeIndex: intentamos construirlo
    if "open_time" in df.columns:
        idx = pd.to_datetime(df["open_time"].astype(np.int64), unit="ms", utc=True)
        df = df.set_index(idx)
    elif "time" in df.columns:
        # Si 'time' ya viene como datetime64[ns], lo respetamos; si es str, parseamos.
        idx = pd.to_datetime(df["time"], utc=True, errors="coerce")
        if idx.isna().any():
            raise ValueError("No se pudo parsear 'time' a datetime (contiene valores inválidos).")
        df = df.set_index(idx)
    else:
        raise ValueError(
            "El DataFrame no tiene DatetimeIndex ni columnas 'open_time' o 'time' "
            "para construir el índice temporal."
        )

    # Asegurar orden y tz
    if not isinstance(df.index, pd.DatetimeIndex):
        raise AssertionError("Fallo interno: no se pudo construir DatetimeIndex.")
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    return df.sort_index()


def _validate_ohlcv_columns(df: pd.DataFrame) -> None:
    """Valida que existan las columnas mínimas para OHLCV."""
    required = {"open", "high", "low", "close", "volume"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"Faltan columnas OHLCV requeridas: {sorted(missing)}")


# --------------------------------------------------------------------------------------
# Iterador principal
# --------------------------------------------------------------------------------------


def iter_bars(df: pd.DataFrame, symbol: str, tz_aware_required: bool = True) -> Iterable[Bar]:
    """
    Convierte un DataFrame OHLCV en un iterador de `Bar`.

    Parámetros:
      - df: DataFrame con columnas [open, high, low, close, volume] y marca temporal.
      - symbol: símbolo asociado a las barras (ej. 'BTCUSDT').
      - tz_aware_required: si True, fuerza índice tz-aware UTC (por defecto True).

    Comportamiento:
      - Si el índice no es DatetimeIndex (o no tiene tz), se normaliza a UTC.
      - Valida columnas OHLCV.
      - Emite Bar ordenadas cronológicamente.
    """
    df_local = df.copy()

    # 1) Normalizar índice temporal
    if tz_aware_required:
        df_local = _ensure_datetime_index_utc(df_local)
    else:
        # Aun si no forzamos tz-aware, si no es DatetimeIndex lo intentamos construir
        if not isinstance(df_local.index, pd.DatetimeIndex):
            df_local = _ensure_datetime_index_utc(df_local)

    # 2) Validar columnas OHLCV
    _validate_ohlcv_columns(df_local)

    # 3) Iterar en orden cronológico
    #    Usamos .itertuples para minimizar overhead.
    for ts, row in df_local.sort_index().iterrows():
        yield Bar(
            symbol=symbol,
            ts=ts.to_pydatetime(),  # datetime (tz-aware UTC)
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
        )
