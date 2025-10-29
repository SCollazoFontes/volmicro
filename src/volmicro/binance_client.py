# src/volmicro/binance_client.py
"""
Cliente de Binance (testnet/mainnet) con utilidades de descarga de klines.

Características:
- `get_klines(..., start, end)` admite rango temporal por:
  * fecha ISO (YYYY-MM-DD),
  * timestamp en segundos,
  * timestamp en milisegundos.
- Paginación automática (límite de 1000 velas por llamada según Binance).
- Devuelve un DataFrame OHLCV con columnas estándar para `iter_bars`.

Notas:
- En testnet, la API no siempre expone todo el histórico. Úsalo para pruebas.
- En mainnet, se respeta el límite de 1000, por lo que se pagina cuando hace falta.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, TypedDict, cast

import pandas as pd
from binance.spot import Spot

# --------------------------------------------------------------------------------------
# Tipos y constantes
# --------------------------------------------------------------------------------------


class KlineRow(TypedDict):
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int


# Mapeo de intervalos Binance → milisegundos
_INTERVAL_TO_MS: dict[str, int] = {
    "1s": 1_000,
    "1m": 60_000,
    "3m": 3 * 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "30m": 30 * 60_000,
    "1h": 60 * 60_000,
    "2h": 2 * 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "6h": 6 * 60 * 60_000,
    "8h": 8 * 60 * 60_000,
    "12h": 12 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
    "3d": 3 * 24 * 60 * 60_000,
    "1w": 7 * 24 * 60 * 60_000,
    "1M": 30 * 24 * 60 * 60_000,  # aproximación
}


# --------------------------------------------------------------------------------------
# Clase cliente
# --------------------------------------------------------------------------------------


class BinanceClient:
    """
    Wrapper mínimo sobre `binance-connector` para separar dependencias del resto del código.

    Atributos:
      - client: instancia de Spot (testnet o mainnet)
    """

    client: Spot

    def __init__(self, testnet: bool = False) -> None:
        """
        Inicializa el cliente Spot. Usa credenciales de entorno si existen.

        Variables de entorno soportadas por binance-connector (si las usas):
        - BINANCE_API_KEY
        - BINANCE_API_SECRET
        """
        if testnet:
            self.client = Spot(base_url="https://testnet.binance.vision")
        else:
            self.client = Spot()

    # ------------------------------------------------------------------
    # exchange_info
    # ------------------------------------------------------------------

    def exchange_info(self, symbol: str | None = None) -> dict[str, Any]:
        """
        Devuelve el `exchangeInfo` de Binance. Si `symbol` no es None, lo filtra.
        """
        if symbol:
            return cast(dict[str, Any], self.client.exchange_info(symbol=symbol))
        return cast(dict[str, Any], self.client.exchange_info())

    # ------------------------------------------------------------------
    # get_klines (con rango temporal opcional y paginación)
    # ------------------------------------------------------------------

    def get_klines(
        self,
        symbol: str,
        interval: str,
        limit: int | None = None,
        start: str | int | None = None,
        end: str | int | None = None,
    ) -> pd.DataFrame:
        """
        Descarga klines (OHLCV) para `symbol` y `interval`.

        Modos de uso:
        A) Bloque simple por `limit`:
           df = get_klines("BTCUSDT", "1h", limit=500)
        B) Rango temporal (paginado auto):
           df = get_klines("BTCUSDT", "1h", start="2024-01-01", end="2024-03-01")

        - `start`/`end` aceptan: "YYYY-MM-DD", timestamp (s), timestamp (ms)
        - Si se pasa `start` o `end`, se ignora `limit` y se pagina hasta cubrir el rango.
        - Devuelve DataFrame con columnas:
          [open_time, open, high, low, close, volume, close_time]
        """
        if start is None and end is None:
            # === Modo por límite directo (una sola llamada) ===
            raw = self.client.klines(symbol=symbol, interval=interval, limit=limit or 500)
            parsed_rows: list[KlineRow] = [self._parse_kline_row(k) for k in raw]
            return self._rows_to_df(parsed_rows)

        # === Modo por rango temporal (paginación) ===
        start_ms = self._to_millis(start) if start is not None else None
        end_ms = self._to_millis(end) if end is not None else None
        step_ms = self._interval_ms(interval)

        acc_rows: list[KlineRow] = []
        cursor = (
            start_ms  # si es None, Binance traerá las últimas (no recomendado para rangos largos)
        )

        while True:
            params: dict[str, Any] = {"limit": 1000}
            if cursor is not None:
                params["startTime"] = cursor
            if end_ms is not None:
                params["endTime"] = end_ms

            chunk = self.client.klines(symbol=symbol, interval=interval, **params)
            if not chunk:
                break

            parsed_chunk: list[KlineRow] = [self._parse_kline_row(k) for k in chunk]
            acc_rows.extend(parsed_chunk)

            # Avanzamos el cursor al final del último kline + 1 intervalo
            last_open = parsed_chunk[-1]["open_time"]
            next_cursor = last_open + step_ms

            # Evitar bucles si no hay progreso
            if cursor is not None and next_cursor <= cursor:
                break
            cursor = next_cursor

            # Si ya pasamos de end_ms (si existe), paramos
            if end_ms is not None and cursor >= end_ms:
                break

            # Si el chunk trajo menos de 1000, probablemente no hay más
            if len(parsed_chunk) < 1000:
                break

        # Deduplicar por open_time por si el último chunk pisa límites
        if acc_rows:
            acc_rows.sort(key=lambda r: r["open_time"])
            dedup: dict[int, KlineRow] = {r["open_time"]: r for r in acc_rows}
            acc_rows = list(dedup.values())
            acc_rows.sort(key=lambda r: r["open_time"])

        return self._rows_to_df(acc_rows)

    # ------------------------------------------------------------------
    # Helpers internos
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_kline_row(k: list[Any]) -> KlineRow:
        """
        Formato de kline de Binance:
        [
          0 open time (ms),
          1 open,
          2 high,
          3 low,
          4 close,
          5 volume,
          6 close time (ms),
          7 quote asset vol,
          8 num trades,
          9 taker buy base,
          10 taker buy quote,
          11 ignore
        ]
        """
        return KlineRow(
            open_time=int(k[0]),
            open=float(k[1]),
            high=float(k[2]),
            low=float(k[3]),
            close=float(k[4]),
            volume=float(k[5]),
            close_time=int(k[6]),
        )

    @staticmethod
    def _rows_to_df(rows: list[KlineRow]) -> pd.DataFrame:
        """Convierte lista de KlineRow en DataFrame OHLCV ordenado por open_time."""
        if not rows:
            return pd.DataFrame(
                columns=["open_time", "open", "high", "low", "close", "volume", "close_time"]
            )
        df = pd.DataFrame(rows)
        df.sort_values("open_time", inplace=True)
        df.reset_index(drop=True, inplace=True)
        return df

    @staticmethod
    def _interval_ms(interval: str) -> int:
        """Devuelve el tamaño del intervalo en milisegundos (ValueError si no soportado)."""
        ms = _INTERVAL_TO_MS.get(interval)
        if ms is None:
            raise ValueError(f"Intervalo no soportado: {interval}")
        return ms

    @staticmethod
    def _to_millis(x: str | int) -> int:
        """
        Convierte fecha o timestamp a milisegundos (UTC).

        Acepta:
          - "YYYY-MM-DD"  → 00:00:00 UTC de ese día
          - timestamp en segundos (>= 1e10 asume ms)
          - timestamp en milisegundos
          - ISO completo (e.g., "2024-01-01T12:34:56+00:00")
        """
        if isinstance(x, int):
            # Heurística: si es "muy grande" lo tratamos como ms
            return x if x > 10_000_000_000 else x * 1_000

        s = str(x).strip()
        # ¿Solo fecha?
        if len(s) == 10 and s[4] == "-" and s[7] == "-":
            dt = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=UTC)
            return int(dt.timestamp() * 1_000)

        # Si es numérico en str
        if s.isdigit():
            val = int(s)
            return val if val > 10_000_000_000 else val * 1_000

        # Último recurso: intentar parseo completo ISO
        try:
            dt = datetime.fromisoformat(s)
        except Exception as e:
            # Ruff B904: encadenar la excepción original
            raise ValueError(f"No se reconoce formato de fecha/timestamp: {x!r}") from e
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return int(dt.timestamp() * 1_000)
