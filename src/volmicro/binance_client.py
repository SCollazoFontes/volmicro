# src/volmicro/binance_client.py
"""
Cliente mínimo para datos de Binance Spot (testnet/mainnet).

Objetivos:
- Proporcionar una interfaz sencilla para descargar klines (OHLCV) y devolverlos
  como un DataFrame bien tipado, indexado por UTC y listo para consumir en el feed.
- Abstraer la elección del endpoint base (testnet vs mainnet).
- Mantener compatibilidad con código antiguo mediante un wrapper funcional.
- Ofrecer (opcionalmente) exchange_info para el módulo de reglas.

Notas:
- Este cliente usa binance-connector (paquete `binance-connector-python`).
- Para klines públicos no necesitas API key/secret; para otros endpoints puede ser necesario.
- El DataFrame resultante:
    * Índice: `openTime` en UTC (tz-aware).
    * Columnas: `open`, `high`, `low`, `close`, `volume` en float64.
- Validamos columnas y tipos para atrapar sorpresas tempranas.
"""

from __future__ import annotations

import logging
from typing import Optional, Any, List, Dict

import pandas as pd
from binance.spot import Spot

# Endpoints base: testnet y mainnet
_TESTNET_BASE = "https://testnet.binance.vision"
_MAINNET_BASE = "https://api.binance.com"

log = logging.getLogger(__name__)


class BinanceClient:
    """
    Pequeño envoltorio alrededor de `binance.spot.Spot`.

    Parámetros
    ----------
    testnet : bool
        True para usar el endpoint de testnet, False para mainnet.
    api_key : Optional[str]
        Clave de API (no requerida para klines públicos).
    api_secret : Optional[str]
        Secreta de API (no requerida para klines públicos).

    Atributos
    ---------
    client : Spot
        Instancia del cliente de la librería oficial (expuesto para compatibilidad
        con código que desee acceder a métodos no envueltos aquí).
    """

    def __init__(
        self,
        testnet: bool = True,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
    ):
        base_url = _TESTNET_BASE if testnet else _MAINNET_BASE

        # NOTA: para endpoints públicos (klines) puedes no pasar api_key/secret.
        # Si en el futuro quieres firmar peticiones (órdenes, account, etc.),
        # añade aquí las credenciales o léelas desde settings/.env.
        kwargs: Dict[str, Any] = {"base_url": base_url}
        if api_key:
            kwargs["api_key"] = api_key
        if api_secret:
            kwargs["api_secret"] = api_secret

        self.client: Spot = Spot(**kwargs)

    # ---------------------------------------------------------------------
    # get_klines: descarga velas y devuelve un DataFrame listo para el feed
    # ---------------------------------------------------------------------
    def get_klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 500,
        start_ms: Optional[int] = None,
        end_ms: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Descarga klines (velas) de Binance Spot y devuelve un DataFrame con:
        - Índice: `openTime` (UTC, tz-aware).
        - Columnas: `open`, `high`, `low`, `close`, `volume` (float64).

        Parámetros
        ----------
        symbol : str
            Símbolo, p. ej. "BTCUSDT".
        interval : str
            Intervalo de vela, p. ej. "1m", "1h", "1d", etc.
        limit : int
            Número máximo de velas a recuperar (típicamente hasta 1000).
        start_ms : Optional[int]
            Timestamp de inicio en milisegundos (opcional).
        end_ms : Optional[int]
            Timestamp de fin en milisegundos (opcional).

        Returns
        -------
        pd.DataFrame
            DataFrame indexado por `openTime` (UTC), con columnas OHLCV en float64.

        Raises
        ------
        ValueError
            Si faltan columnas esperadas o si el índice no es tz-aware.
        Exception
            Propaga cualquier error de red o de la API subyacente.
        """
        # Defensivo: clamp de limit (Binance suele permitir hasta 1000)
        if limit <= 0:
            limit = 1
        if limit > 1000:
            limit = 1000

        # Llamada directa al endpoint klines
        # Firmas posibles: klines(symbol, interval, **kwargs)
        data: List[List[Any]] = self.client.klines(
            symbol=symbol,
            interval=interval,
            limit=limit,
            startTime=start_ms,
            endTime=end_ms,
        )

        # La API devuelve una lista de listas con 12 campos por vela:
        # [ openTime, open, high, low, close, volume, closeTime,
        #   quoteAssetVolume, numTrades, takerBuyBase, takerBuyQuote, ignore ]
        df = pd.DataFrame(
            data,
            columns=[
                "openTime", "open", "high", "low", "close", "volume",
                "closeTime", "quoteAssetVolume", "numTrades", "takerBuyBase",
                "takerBuyQuote", "ignore",
            ],
        )

        # Convertimos `openTime` a datetime con tz UTC y lo ponemos como índice
        df["openTime"] = pd.to_datetime(df["openTime"], unit="ms", utc=True)
        df = df.set_index("openTime")[["open", "high", "low", "close", "volume"]]

        # Tipos numéricos consistentes
        df = df.astype(
            {
                "open": "float64",
                "high": "float64",
                "low": "float64",
                "close": "float64",
                "volume": "float64",
            }
        )

        # Validaciones defensivas (fallar pronto si algo inesperado ocurre)
        expected = {"open", "high", "low", "close", "volume"}
        missing = expected - set(df.columns)
        if missing:
            raise ValueError(f"Faltan columnas en klines: {missing}")
        if df.index.tz is None:
            # Debe ser tz-aware (UTC) para no mezclar husos a posteriori
            raise ValueError("El índice de klines debe ser tz-aware (UTC).")

        # opcional: eliminar duplicados y asegurar orden temporal
        df = df[~df.index.duplicated()].sort_index()

        return df

    # ---------------------------------------------------------------------
    # exchange_info: utilidad opcional para reglas del exchange
    # ---------------------------------------------------------------------
    def exchange_info(self, symbol: Optional[str] = None) -> dict:
        """
        Devuelve el `exchangeInfo` de Binance. Si `symbol` no es None, lo filtra
        al símbolo dado (según soporte del conector).

        Se expone por si `rules.py` prefiere delegar la llamada en el cliente.
        """
        # En versiones modernas de binance-connector, `Spot.exchange_info` acepta symbol=...
        # Algunas instalaciones antiguas tenían un subcliente `.spot()`. Dejamos el acceso simple.
        if symbol:
            return self.client.exchange_info(symbol=symbol)
        return self.client.exchange_info()


# --------------------------------------------------------------------------------
# Wrapper funcional de compatibilidad (API "antigua" que usaba función suelta)
# --------------------------------------------------------------------------------
def get_klines_df(
    symbol: str,
    interval: str,
    limit: int = 500,
    testnet: bool = True,
    start_ms: Optional[int] = None,
    end_ms: Optional[int] = None,
) -> pd.DataFrame:
    """
    Compatibilidad con código legado que esperaba una función en lugar de una clase.

    Internamente instancia `BinanceClient(testnet=...)` y llama a `get_klines`.

    Ejemplo:
        df = get_klines_df("BTCUSDT", "1h", limit=200, testnet=True)
    """
    client = BinanceClient(testnet=testnet)
    return client.get_klines(
        symbol=symbol,
        interval=interval,
        limit=limit,
        start_ms=start_ms,
        end_ms=end_ms,
    )
