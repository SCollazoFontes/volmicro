from dataclasses import dataclass

@dataclass
class DataConfig:
    # Símbolo y marco temporal por defecto
    symbol: str = "BTC-USD"     # para yfinance; para ccxt típicamente "BTC/USDT"
    timeframe: str = "1h"       # "1m", "5m", "1h", "1d"...
    tz: str = "UTC"             # zona horaria de trabajo

    # Columnas esperadas
    required_cols = ["timestamp", "open", "high", "low", "close", "volume"]

CFG = DataConfig()
