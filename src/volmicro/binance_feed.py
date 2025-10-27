# src/volmicro/binance_feed.py
from __future__ import annotations
import pandas as pd

from src.volmicro.core import Bar
from src.volmicro.binance_client import get_klines_df


def iter_bars(
    symbol: str,
    interval: str,
    limit: int = 500,
    start: pd.Timestamp | None = None,
    start_str: str | None = None,
):
    """
    Generador de barras OHLCV a partir de Binance.

    Puedes llamar con:
      - start=pd.Timestamp("2025-10-26 00:00:00", tz="UTC")
      - o start_str="2025-10-26 00:00:00" (se asume UTC si no trae tz)
    """
    # Normaliza argumento de inicio
    if start is None and start_str is not None:
        ts = pd.Timestamp(start_str)
        start = ts if ts.tzinfo is not None else ts.tz_localize("UTC")

    # Descarga DataFrame de klines (openTime como índice UTC, columnas numéricas)
    df = get_klines_df(symbol=symbol, interval=interval, limit=limit, start_time=start)

    # Garantiza índice datetime si viniera sin él
    if not pd.api.types.is_datetime64_any_dtype(df.index):
        df.index = pd.to_datetime(df.index, unit="ms", utc=True)

    # Rinde barras
    for row in df.itertuples():
        yield Bar(
            symbol=symbol,
            ts=row.Index,
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            volume=float(row.volume),
        )
