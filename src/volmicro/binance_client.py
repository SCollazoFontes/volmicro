# src/volmicro/binance_client.py
from __future__ import annotations
import pandas as pd
from binance.spot import Spot

_TESTNET_BASE = "https://testnet.binance.vision"
_MAINNET_BASE = "https://api.binance.com"

class BinanceClient:
    """
    Cliente mínimo para klines de Spot (Testnet/Mainnet).
    Devuelve DataFrames con índice UTC y OHLCV en float.
    """
    def __init__(self, testnet: bool = True):
        base_url = _TESTNET_BASE if testnet else _MAINNET_BASE
        self.client = Spot(base_url=base_url)

    def get_klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 500,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> pd.DataFrame:
        data = self.client.klines(symbol, interval, limit=limit, startTime=start_ms, endTime=end_ms)
        df = pd.DataFrame(
            data,
            columns=[
                "openTime","open","high","low","close","volume",
                "closeTime","quoteAssetVolume","numTrades","takerBuyBase",
                "takerBuyQuote","ignore"
            ],
        )
        df["openTime"] = pd.to_datetime(df["openTime"], unit="ms", utc=True)
        df = df.set_index("openTime")[["open","high","low","close","volume"]].astype(float)
        
        # Validación defensiva
        expected = {"open","high","low","close","volume"}
        missing = expected - set(df.columns)
        if missing:
            raise ValueError(f"Faltan columnas en klines: {missing}")
        if df.index.tz is None:
            raise ValueError("El índice de klines debe ser tz-aware (UTC).")
        # Cast explícito a float64 (consistencia numérica)
        df = df.astype({"open":"float64","high":"float64","low":"float64","close":"float64","volume":"float64"})
        return df
    
    def get_klines_df(symbol: str, interval: str, limit: int = 500,
                  testnet: bool = True, start_ms: int | None = None, end_ms: int | None = None):
        """
        Wrapper de compatibilidad para código antiguo que esperaba una función.
        Usa internamente la clase BinanceClient.
        """
        client = BinanceClient(testnet=testnet)
        return client.get_klines(symbol=symbol, interval=interval, limit=limit, start_ms=start_ms, end_ms=end_ms)
