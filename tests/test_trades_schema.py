# tests/test_trades_schema.py
import os
import glob
import math
import pandas as pd
import pytest

REQUIRED_COLS = [
    "ts", "symbol", "side", "qty", "price", "fee",
    "cash_after", "qty_after", "equity_after",
    "realized_pnl", "cum_realized_pnl", "note",
    "intended_price", "exec_price_raw", "price_round_diff",
    "qty_raw", "qty_rounded", "qty_round_diff", "slippage_bps",
    "notional_before_round", "notional_after_round", "rule_check",
    "run_id", "fee_bps", "schema_version",
    "tickSize_used", "stepSize_used", "minNotional_used",
]

def find_trades_path():
    # Preferimos el último CSV dentro de reports/*
    candidates = glob.glob("reports/*/trades.csv")
    candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    if candidates:
        return candidates[0]
    # fallback: raíz del proyecto
    if os.path.exists("trades.csv"):
        return "trades.csv"
    return None

@pytest.mark.skipif(find_trades_path() is None, reason="No se encontró trades.csv. Ejecuta un backtest primero.")
def test_schema_and_integrity():
    path = find_trades_path()
    df = pd.read_csv(path)

    # 1) columnas obligatorias
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    assert not missing, f"Faltan columnas en trades.csv: {missing}"

    # 2) no vacío
    assert len(df) > 0, "trades.csv está vacío"

    # 3) run_id presente y consistente (al menos que no sea nulo)
    assert df["run_id"].notna().all() and (df["run_id"].astype(str) != "").all(), "run_id vacío o NaN"
    # Si todo es un único run, run_id único; si no, al menos no debe haber NaN
    # (No forzamos unicidad por si concatenas varios runs a propósito)

    # 4) schema_version correcto (esperamos 1)
    assert df["schema_version"].notna().all(), "schema_version con NaN"
    assert (df["schema_version"] == 1).all(), "schema_version distinto de 1"

    # 5) reglas Binance presentes (no NaN)
    for col in ["tickSize_used", "stepSize_used", "minNotional_used"]:
        assert df[col].notna().all(), f"{col} tiene NaN"

    # 6) coherencia fee_bps ≈ 1e4 * fee / notional_after_round (tolerancia)
    #    evitamos divisiones por cero y filtramos filas con notional_after_round > 0
    sub = df[df["notional_after_round"] > 0].copy()
    assert len(sub) > 0, "No hay filas con notional_after_round > 0 para verificar fee_bps"

    calc_fee_bps = 1e4 * (sub["fee"] / sub["notional_after_round"])
    # tolerancia de 1e-3 bps por redondeos
    diff = (sub["fee_bps"] - calc_fee_bps).abs().max()
    assert diff < 1e-3, f"fee_bps inconsistente; max |diff| = {diff}"

    # 7) tipos básicos/valores razonables
    assert (df["qty"] >= 0).all(), "qty negativa"
    assert (df["price"] > 0).all(), "price <= 0"
    assert (df["notional_after_round"] >= 0).all(), "notional_after_round negativa"
    # slippage_bps puede ser 0 o positivo (en tu modelo actual es constante por lado)
    assert df["slippage_bps"].notna().all(), "slippage_bps con NaN"
