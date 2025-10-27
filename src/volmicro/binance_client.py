# src/volmicro/binance_client.py
from __future__ import annotations
import os
import pandas as pd
from binance.spot import Spot


def _to_ms(ts: pd.Timestamp | None) -> int | None:
    """Convierte un pd.Timestamp (con o sin tz) a milisegundos desde epoch (UTC)."""
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return int(ts.timestamp() * 1000)


def get_client() -> Spot:
    """
    Crea el cliente Spot (Testnet o Live) leyendo variables de entorno:
      BINANCE_API_KEY, BINANCE_API_SECRET, BINANCE_BASE_URL (para testnet).
    """
    api_key = os.getenv("BINANCE_API_KEY", "")
    api_secret = os.getenv("BINANCE_API_SECRET", "")
    base_url = os.getenv("BINANCE_BASE_URL")  

    if base_url:
        return Spot(api_key=api_key, api_secret=api_secret, base_url=base_url)
    return Spot(api_key=api_key, api_secret=api_secret)


def get_klines_df(
    symbol: str,
    interval: str,
    limit: int = 500,
    start_time: pd.Timestamp | None = None,
    end_time: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """
    Descarga velas de Binance y devuelve un DataFrame con índice datetime(UTC)
    y columnas: open, high, low, close, volume (float).

    Args:
        symbol: 'BTCUSDT', etc.
        interval: '1m','5m','1h','4h','1d', etc. (formato Binance nativo)
        limit: nº de velas (<=1000 en Binance)
        start_time: pd.Timestamp opcional (UTC recomendado; si naive se asume UTC)
        end_time: pd.Timestamp opcional
    """
    client = get_client()
    start_ms = _to_ms(start_time)
    end_ms = _to_ms(end_time)

    # Llamada nativa a klines
    raw = client.klines(
        symbol=symbol,
        interval=interval,
        startTime=start_ms,
        endTime=end_ms,
        limit=limit,
    )

    # Columnas que devuelve Binance:
    # [0] open time, [1] open, [2] high, [3] low, [4] close, [5] volume,
    # [6] close time, [7] quote asset volume, [8] number of trades,
    # [9] taker buy base vol, [10] taker buy quote vol, [11] ignore
    if not raw:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    df = pd.DataFrame(raw, columns=[
        "openTime", "open", "high", "low", "close", "volume",
        "closeTime", "quoteVol", "nTrades", "takerBuyBase", "takerBuyQuote", "ignore"
    ])

    # Índice datetime (UTC) con openTime en ms
    df["openTime"] = pd.to_datetime(df["openTime"], unit="ms", utc=True)
    df = df.set_index("openTime")

    # Tipos numéricos limpios
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Solo las columnas que usaremos
    return df[["open", "high", "low", "close", "volume"]]
