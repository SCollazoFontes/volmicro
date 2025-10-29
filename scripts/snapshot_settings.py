# scripts/snapshot_settings.py
import glob
import importlib.util
import json
import os

import pandas as pd

# 1) Intentamos primero en raíz; si no, buscamos el último trades.csv en reports/*
DEFAULT_TRADES = "trades.csv"


def find_trades_path():
    if os.path.exists(DEFAULT_TRADES):
        return DEFAULT_TRADES
    candidates = glob.glob("reports/*/trades.csv")
    if not candidates:
        raise SystemExit(
            "No existe trades.csv. Ejecuta un backtest o coloca el archivo en reports/*/trades.csv"
        )
    # Elegimos el más reciente por fecha de modificación
    candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return candidates[0]


SETTINGS_PATH = "src/volmicro/settings.py"


def import_settings():
    spec = importlib.util.spec_from_file_location("volmicro_settings", SETTINGS_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def to_jsonable(obj):
    try:
        json.dumps(obj)
        return obj
    except Exception:
        return str(obj)


def main():
    trades_path = find_trades_path()
    print(f"[snapshot] usando trades.csv: {trades_path}")

    df = pd.read_csv(trades_path)
    if "run_id" not in df.columns or df.empty:
        raise SystemExit("El trades.csv no tiene run_id o está vacío.")

    run_ids = sorted(df["run_id"].unique().tolist())

    settings = import_settings()
    snapshot = {k: to_jsonable(getattr(settings, k)) for k in dir(settings) if k.isupper()}

    os.makedirs("artifacts", exist_ok=True)
    for run_id in run_ids:
        outdir = os.path.join("artifacts", str(run_id))
        os.makedirs(outdir, exist_ok=True)
        out_path = os.path.join(outdir, "settings_snapshot.json")
        with open(out_path, "w") as f:
            json.dump(snapshot, f, indent=2)
        print(f"  -> escrito {out_path}")

    print(f"OK: snapshots creados para {len(run_ids)} run(s)")


if __name__ == "__main__":
    main()
