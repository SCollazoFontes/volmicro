# tests/test_trades_schema.py
"""
Test de contrato del CSV de trades.

Objetivo
--------
Asegurar que `trades.csv` exportado por una ejecución de backtest contiene:
- Todas las **columnas obligatorias** (tanto las base como las de metadatos).
- Tipos/valores **razonables** (qty >= 0, price > 0, etc.).
- Coherencias derivadas como:
    fee_bps ≈ 1e4 * fee / notional_after_round   (dentro de tolerancia)

Este test asume que antes se ha ejecutado un backtest que dejó un `trades.csv`
en `reports/<...>/trades.csv` o, como fallback, en la raíz del proyecto.
"""

import os
import glob
import math
import pandas as pd
import pytest

# --------------------------------------------------------------------
# CONTRATO: columnas obligatorias que deben existir en trades.csv
# --------------------------------------------------------------------
REQUIRED_COLS = [
    # --- columnas base (Trade dataclass) ---
    "ts", "symbol", "side", "qty", "price", "fee",
    "cash_after", "qty_after", "equity_after",
    "realized_pnl", "cum_realized_pnl", "note",

    # --- metadatos de ejecución ---
    "intended_price", "exec_price_raw", "price_round_diff",
    "qty_raw", "qty_rounded", "qty_round_diff", "slippage_bps",
    "notional_before_round", "notional_after_round", "rule_check",
    "run_id", "fee_bps", "schema_version",

    # --- snapshot de reglas del exchange (para auditoría) ---
    "tickSize_used", "stepSize_used", "minNotional_used",
]


def find_trades_path() -> str | None:
    """
    Localiza el `trades.csv` más reciente.

    Preferencia:
      1) reports/*/trades.csv (el más nuevo por mtime)
      2) ./trades.csv en la raíz (fallback)
    """
    candidates = glob.glob("reports/*/trades.csv")
    candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    if candidates:
        return candidates[0]
    if os.path.exists("trades.csv"):
        return "trades.csv"
    return None


@pytest.mark.skipif(find_trades_path() is None, reason="No se encontró trades.csv. Ejecuta un backtest primero.")
def test_schema_and_integrity():
    path = find_trades_path()
    assert path is not None, "No se pudo resolver la ruta a trades.csv (find_trades_path devolvió None)"
    df = pd.read_csv(path)

    # -----------------------------
    # 1) Columnas obligatorias
    # -----------------------------
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    assert not missing, f"Faltan columnas en trades.csv: {missing}"

    # -----------------------------
    # 2) No vacío
    # -----------------------------
    assert len(df) > 0, "trades.csv está vacío"

    # -----------------------------
    # 3) run_id presente y no vacío
    # -----------------------------
    assert df["run_id"].notna().all() and (df["run_id"].astype(str) != "").all(), "run_id vacío o NaN"

    # -----------------------------
    # 4) schema_version correcto
    # -----------------------------
    assert df["schema_version"].notna().all(), "schema_version con NaN"
    assert (df["schema_version"] == 1).all(), "schema_version distinto de 1"

    # -----------------------------
    # 5) reglas Binance presentes (no NaN)
    # -----------------------------
    for col in ["tickSize_used", "stepSize_used", "minNotional_used"]:
        assert df[col].notna().all(), f"{col} tiene NaN"

    # -----------------------------
    # 6) coherencia fee_bps vs fee/notional
    # -----------------------------
    # Evitamos divisiones por cero: filtramos filas con notional_after_round > 0
    sub = df[df["notional_after_round"] > 0].copy()
    assert len(sub) > 0, "No hay filas con notional_after_round > 0 para verificar fee_bps"

    calc_fee_bps = 1e4 * (sub["fee"] / sub["notional_after_round"])
    # tolerancia pequeña por redondeos y float; 1e-3 bps es muy estricta, pero suficiente
    diff = (sub["fee_bps"] - calc_fee_bps).abs().max()
    assert diff < 1e-3, f"fee_bps inconsistente; max |diff| = {diff}"

    # -----------------------------
    # 7) tipos/valores razonables
    # -----------------------------
    assert (df["qty"] >= 0).all(), "qty negativa"
    assert (df["price"] > 0).all(), "price <= 0"
    assert (df["notional_after_round"] >= 0).all(), "notional_after_round negativa"

    # slippage_bps puede ser 0 o positivo (en el modelo actual es constante por lado)
    assert df["slippage_bps"].notna().all(), "slippage_bps con NaN"

    # (opcional) side válido
    valid_sides = set(["BUY", "SELL"])
    assert set(df["side"].unique()).issubset(valid_sides), f"Sides inesperados: {set(df['side'].unique()) - valid_sides}"
