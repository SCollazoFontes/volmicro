import json
from pathlib import Path
import numpy as np
import pandas as pd
from . import settings

# === Posibles nombres de columna temporal ===
TIME_CANDIDATES = ["timestamp", "ts", "time", "datetime", "openTime", "date"]

def _read_equity_csv(equity_path: Path) -> pd.DataFrame:
    """
    Lee equity_curve.csv y:
      - elimina columnas índice tipo 'Unnamed: 0'
      - auto-detecta la columna temporal
      - valida que exista 'equity'
    Devuelve DataFrame ordenado con columnas ['timestamp','equity',...]
    """
    df = pd.read_csv(equity_path)

    # Eliminar posibles columnas índice
    drop_cols = [c for c in df.columns if str(c).startswith("Unnamed")]
    if drop_cols:
        df = df.drop(columns=drop_cols)

    # Detectar columna temporal
    time_col = None
    for c in TIME_CANDIDATES:
        if c in df.columns:
            time_col = c
            break
    if time_col is None:
        raise ValueError(
            f"No se encontró columna temporal en {equity_path}. "
            f"Intenta exportar con alguna de: {TIME_CANDIDATES}"
        )

    if "equity" not in df.columns:
        raise ValueError("equity_curve.csv debe contener la columna 'equity'")

    # Normalizar nombre y tipo de timestamp
    df["timestamp"] = pd.to_datetime(df[time_col], utc=True, errors="coerce")
    if df["timestamp"].isna().any():
        raise ValueError("Hay timestamps inválidos en equity_curve.csv")

    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def _returns_from_equity(df: pd.DataFrame, use_daily: bool) -> tuple[pd.Series, str]:
    """
    Devuelve (retornos, basis_str):
      - retornos: pd.Series de pct_change sin NaNs
      - basis_str: "daily" si usa resample 1D, "per-bar" si usa frecuencia original
    Si use_daily=True pero no hay >=2 días distintos, cae a per-bar.
    """
    if "timestamp" not in df.columns or "equity" not in df.columns:
        raise ValueError("equity_curve.csv debe contener columnas 'timestamp' y 'equity'")

    df = df.copy()
    df = df.sort_values("timestamp")

    if use_daily:
        daily_equity = (
            df.set_index("timestamp")["equity"]
              .resample("D")
              .last()
              .dropna()
        )
        daily_ret = daily_equity.pct_change().dropna()
        if len(daily_ret) >= 1:
            return daily_ret, "daily"

        # fallback si no hay suficientes días
        per_bar = df["equity"].pct_change().dropna()
        return per_bar, "per-bar"

    # modo per-bar explícito
    per_bar = df["equity"].pct_change().dropna()
    return per_bar, "per-bar"


def calculate_metrics(
    equity_curve_path: str | Path | None = None,
    trades_path: str | Path | None = None,
    output_dir: str | Path | None = None
) -> dict:
    """
    Calcula métricas desde equity_curve.csv y trades.csv y guarda summary.json.
    Si no se pasan rutas, usa settings.REPORTS_DIR por defecto.
    Respeta settings.METRICS_USE_DAILY para el cálculo de retornos.
    """
    # === Defaults basados en settings ===
    reports_dir = Path(output_dir) if output_dir is not None else settings.REPORTS_DIR
    reports_dir.mkdir(parents=True, exist_ok=True)

    equity_path = Path(equity_curve_path) if equity_curve_path is not None else (reports_dir / "equity_curve.csv")
    trades_file = Path(trades_path) if trades_path is not None else (reports_dir / "trades.csv")
    summary_path = reports_dir / "summary.json"

    if not equity_path.exists():
        raise FileNotFoundError(f"No se encuentra {equity_path}")
    if not trades_file.exists():
        raise FileNotFoundError(f"No se encuentra {trades_file}")

    # === Leer equity ===
    df = _read_equity_csv(equity_path)
    if df.empty:
        raise ValueError("equity_curve.csv está vacío")

    # === Retornos (diarios o por barra, según settings) ===
    use_daily = bool(getattr(settings, "METRICS_USE_DAILY", True))
    ret, basis = _returns_from_equity(df, use_daily=use_daily)

    # Fechas del periodo
    t0 = pd.to_datetime(df["timestamp"].iloc[0], utc=True)
    t1 = pd.to_datetime(df["timestamp"].iloc[-1], utc=True)
    period_days = max((t1 - t0).days, 1)

    # === Métricas principales ===
    equity0 = float(df["equity"].iloc[0])
    equity1 = float(df["equity"].iloc[-1])
    total_return = (equity1 / equity0) - 1 if equity0 > 0 else np.nan

    ann_days = int(getattr(settings, "METRICS_ANNUALIZATION_DAYS", 365))
    annualized_return = (1 + total_return) ** (ann_days / period_days) - 1 if np.isfinite(total_return) else np.nan

    ret_std = float(ret.std()) if len(ret) > 0 else np.nan
    ret_mean = float(ret.mean()) if len(ret) > 0 else np.nan
    annualized_volatility = ret_std * np.sqrt(ann_days) if np.isfinite(ret_std) else np.nan
    sharpe_ratio = (ret_mean / ret_std * np.sqrt(ann_days)) if (np.isfinite(ret_mean) and ret_std and ret_std > 0) else np.nan

    # Max Drawdown sobre equity original
    rolling_max = df["equity"].cummax()
    drawdown = (df["equity"] / rolling_max) - 1.0
    max_drawdown = float(drawdown.min()) if not drawdown.empty else np.nan

    # === Trades ===
    trades_df = pd.read_csv(trades_file)
    n_trades = int(len(trades_df)) if not trades_df.empty else 0
    total_pnl = float(trades_df["pnl"].sum()) if ("pnl" in trades_df.columns and not trades_df.empty) else 0.0

    metrics = {
        "total_return": None if not np.isfinite(total_return) else round(total_return, 6),
        "annualized_return": None if not np.isfinite(annualized_return) else round(annualized_return, 6),
        "annualized_volatility": None if not np.isfinite(annualized_volatility) else round(annualized_volatility, 6),
        "sharpe_ratio": None if not np.isfinite(sharpe_ratio) else round(sharpe_ratio, 4),
        "max_drawdown": None if not np.isfinite(max_drawdown) else round(max_drawdown, 6),
        "n_trades": n_trades,
        "total_pnl": round(total_pnl, 2),
        "period_days": int(period_days),
        "equity_start": round(equity0, 2),
        "equity_end": round(equity1, 2),
        "start_timestamp": t0.isoformat(),
        "end_timestamp": t1.isoformat(),
        "returns_basis": basis,
        "annualization_days": ann_days,
    }

    # === Guardar summary.json ===
    with open(summary_path, "w") as f:
        json.dump(metrics, f, indent=4)

    print(f"Resumen exportado a {summary_path}")
    return metrics


if __name__ == "__main__":
    out = calculate_metrics()
    print(json.dumps(out, indent=4))
