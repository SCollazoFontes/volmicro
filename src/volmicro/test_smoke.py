# src/volmicro/test_smoke.py
"""
Test de humo (smoke test) del pipeline completo.

Objetivo
--------
Verificar, con datos sintéticos muy simples, que:
1) Podemos convertir un DataFrame OHLCV en barras (`iter_bars`).
2) El `engine.run_engine` recorre las barras y llama a la estrategia.
3) La estrategia por defecto (BuySecondBarStrategy) ejecuta una compra en la 2ª barra
   y un cierre al final (venta), generando **exactamente 2 trades**.
4) La curva de equity aumenta cuando el precio sube (sanity check).

Este test NO requiere conexión a Binance ni reglas del exchange porque usa datos
sintéticos y no llama a `rules.load_symbol_rules`. Su propósito es detectar roturas
obvias en el wiring del sistema.
"""

import pandas as pd

from src.volmicro.binance_feed import iter_bars
from src.volmicro.engine import run_engine
from src.volmicro.portfolio import Portfolio
from src.volmicro.strategy import BuySecondBarStrategy


# ------------------------------------------------------------------------------
# Utilidad: genera un DataFrame OHLCV simple, con índice UTC tz-aware
# ------------------------------------------------------------------------------
def make_df(n: int = 10, start: float = 100.0, step: float = 1.0) -> pd.DataFrame:
    """
    Crea un DataFrame con n barras horarias:
      - open  = start + i*step
      - high  = open + 1
      - low   = open - 1
      - close = open
      - volume= 1.0

    Índice: pd.date_range(..., tz="UTC") para cumplir con el requisito tz-aware.
    """
    idx = pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC")
    data = {
        "open": [start + i * step for i in range(n)],
        "high": [start + i * step + 1 for i in range(n)],
        "low": [start + i * step - 1 for i in range(n)],
        "close": [start + i * step for i in range(n)],
        "volume": [1.0] * n,
    }
    return pd.DataFrame(data, index=idx)


# ------------------------------------------------------------------------------
# Test principal: el circuito corre, ejecuta 2 trades y el equity sube
# ------------------------------------------------------------------------------
def test_engine_runs_and_trades():
    # 1) Datos sintéticos crecientes ⇒ el equity debería subir si abrimos largo
    df = make_df(n=10, start=100.0, step=1.0)

    # 2) Feed → iterable de Bar (valida columnas y tz-aware)
    bars = iter_bars(df, symbol="TEST")

    # 3) Portfolio y estrategia trivial
    p = Portfolio(cash=1000.0, symbol="TEST", fee_bps=0.0)  # fee=0 para no contaminar la lógica
    strat = BuySecondBarStrategy(alloc_pct=0.10)  # compra 10% del cash en la 2ª barra

    # 4) Engine (log_every alto para no spamear logs en el test)
    p = run_engine(bars, p, strat, log_every=1000)

    # 5) Trades: debe haber exactamente 2 (BUY en barra 2 y SELL en on_finish)
    trades = p.trades_dataframe()
    assert len(trades) == 2, f"Se esperaban 2 trades (BUY y SELL), pero hay {len(trades)}"

    # 6) Equity: en serie ascendente y cerrando al final, el equity final > inicial
    assert (
        p.equity() > p.starting_cash
    ), "El equity final no es mayor que el inicial en una serie ascendente"

    # 7) Chequeos suaves: qty > 0 en BUY y SELL y side válidos
    assert set(trades["side"].unique()) <= {"BUY", "SELL"}, "Side inesperado en trades"
    assert (trades["qty"] > 0).all(), "Algún trade tiene qty <= 0"
    assert (trades["price"] > 0).all(), "Algún trade tiene price <= 0"


# ------------------------------------------------------------------------------
# (Opcional) Test adicional muy ligero: cierre sin posición si no hay compra
# ------------------------------------------------------------------------------
def test_no_trade_if_short_series():
    """
    Si la serie tiene <2 barras, la estrategia no llega a comprar (compra en la 2ª).
    Verificamos que en ese caso no hay trades y el equity == cash (MTM sin posición).
    """
    df = make_df(n=1, start=50.0, step=0.0)  # una sola barra
    bars = iter_bars(df, symbol="TEST")
    p = Portfolio(cash=500.0, symbol="TEST", fee_bps=0.0)
    strat = BuySecondBarStrategy(alloc_pct=0.50)

    p = run_engine(bars, p, strat, log_every=1000)

    trades = p.trades_dataframe()
    assert len(trades) == 0, f"No debería haber trades con 1 barra; hay {len(trades)}"
    # Equity = cash porque MTM sin posición ⇒ qty=0
    assert abs(p.equity() - p.cash) < 1e-9, "Equity debería igualar cash cuando no hay posición"
