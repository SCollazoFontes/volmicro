# src/volmicro/metrics.py
"""
Cálculo de métricas del backtest y exportación de un `summary.json`.

Flujo general (usado desde __main__.py):
----------------------------------------
1) Leemos los CSVs exportados por el backtest:
   - equity_curve.csv  -> columna temporal + columna 'equity'
   - trades.csv        -> (opcional) para contar trades y sumar PnL
2) Construimos los **retornos** en la base adecuada:
   - Si settings.METRICS_USE_DAILY = True, intentamos **resample 1D** y usar último equity del día.
     Si no hay al menos 2 puntos diarios válidos, hacemos **fallback a per-bar** (no rompemos).
   - Si METRICS_USE_DAILY = False, usamos **per-bar** directamente (pct_change del equity_curve).
3) Calculamos métricas básicas:
   - total_return (equity_end/equity_start - 1)
   - annualized_return (potenciando por días)
   - annualized_volatility (std(ret) * sqrt(annualization_days))
   - sharpe_ratio (mean/std * sqrt(annualization_days))
   - max_drawdown (mínimo drawdown relativo sobre la curva de equity)
   - n_trades y total_pnl (si hay trades.csv con columna 'pnl')
4) Guardamos `summary.json` en el mismo directorio de salida.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import settings

# === Posibles nombres de columna temporal ===
# Permitimos varios nombres para ser tolerantes con exportaciones distintas.
TIME_CANDIDATES = ["timestamp", "ts", "time", "datetime", "openTime", "date"]


# --------------------------------------------------------------------------------------
# Lectura y normalización de equity_curve.csv
# --------------------------------------------------------------------------------------
def _read_equity_csv(equity_path: Path) -> pd.DataFrame:
    """
    Lee equity_curve.csv y normaliza:

    - Elimina columnas índice accidentales (p.ej., 'Unnamed: 0').
    - Detecta automáticamente la columna temporal entre TIME_CANDIDATES.
    - Verifica que exista 'equity'.
    - Convierte la columna temporal a datetime UTC tz-aware.
    - Ordena por tiempo de forma ascendente.

    Devuelve un DataFrame con al menos:
        ['timestamp', 'equity', ...]
    """
    df = pd.read_csv(equity_path)

    # 1) Eliminar posibles columnas-índice añadidas por pandas
    drop_cols = [c for c in df.columns if str(c).startswith("Unnamed")]
    if drop_cols:
        df = df.drop(columns=drop_cols)

    # 2) Detectar nombre de la columna temporal
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

    # 3) Equity presente
    if "equity" not in df.columns:
        raise ValueError("equity_curve.csv debe contener la columna 'equity'")

    # 4) Normalizar tipo de timestamp (coherente y tz-aware)
    df["timestamp"] = pd.to_datetime(df[time_col], utc=True, errors="coerce")
    if df["timestamp"].isna().any():
        raise ValueError("Hay timestamps inválidos en equity_curve.csv")

    # 5) Orden temporal
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


# --------------------------------------------------------------------------------------
# Construcción de retornos (daily vs per-bar) con fallback inteligente
# --------------------------------------------------------------------------------------
def _returns_from_equity(df: pd.DataFrame, use_daily: bool) -> tuple[pd.Series, str]:
    """
    Devuelve una tupla (retornos, basis_str):

      - retornos: pd.Series de pct_change() sin NaNs (índice acorde a la base)
      - basis_str: "daily" si usamos resample 1D, "per-bar" si usamos la frecuencia original

    Lógica:
      - Si use_daily=True, intentamos resample('D').last() sobre equity y cogemos pct_change.
        Si no existen >=1 retornos (es decir, no hay al menos 2 días con dato), caemos a per-bar.
      - Si use_daily=False, vamos directamente a per-bar.
    """
    if "timestamp" not in df.columns or "equity" not in df.columns:
        raise ValueError("equity_curve.csv debe contener columnas 'timestamp' y 'equity'")

    df = df.copy().sort_values("timestamp")

    if use_daily:
        # Serie diaria a partir del último valor de cada día (cierre diario de equity)
        daily_equity = df.set_index("timestamp")["equity"].resample("D").last().dropna()
        daily_ret = daily_equity.pct_change().dropna()
        if len(daily_ret) >= 1:
            return daily_ret, "daily"

        # Fallback: no hay suficientes días; usamos per-bar
        per_bar = df["equity"].pct_change().dropna()
        return per_bar, "per-bar"

    # Modo per-bar explícito
    per_bar = df["equity"].pct_change().dropna()
    return per_bar, "per-bar"


# --------------------------------------------------------------------------------------
# API principal: cálculo de métricas y guardado de summary.json
# --------------------------------------------------------------------------------------
def calculate_metrics(
    equity_curve_path: str | Path | None = None,
    trades_path: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> dict:
    """
    Calcula métricas a partir de los CSVs de equity y trades, y guarda summary.json.

    Parámetros:
      - equity_curve_path:ruta a equity_curve.csv (opcional, por defecto en reports/)
      - trades_path      :ruta a trades.csv (opcional, por defecto en reports/)
      - output_dir       :directorio donde escribir summary.json (por defecto, settings.REPORTS_DIR)

    Respeta:
      - settings.METRICS_USE_DAILY (True => intentamos base diaria con fallback)
      - settings.METRICS_ANNUALIZATION_DAYS (por defecto 252)

    Devuelve:
      - dict con métricas clave (total_return, annualized_return, volatility, sharpe, mdd, etc.)
    """
    # === 0) Rutas por defecto basadas en settings ===
    reports_dir = Path(output_dir) if output_dir is not None else settings.REPORTS_DIR
    reports_dir.mkdir(parents=True, exist_ok=True)

    equity_path = (
        Path(equity_curve_path)
        if equity_curve_path is not None
        else (reports_dir / "equity_curve.csv")
    )
    trades_file = Path(trades_path) if trades_path is not None else (reports_dir / "trades.csv")
    summary_path = reports_dir / "summary.json"

    if not equity_path.exists():
        raise FileNotFoundError(f"No se encuentra {equity_path}")
    if not trades_file.exists():
        raise FileNotFoundError(f"No se encuentra {trades_file}")

    # === 1) Leer y validar equity ===
    df = _read_equity_csv(equity_path)
    if df.empty:
        raise ValueError("equity_curve.csv está vacío")

    # === 2) Construir retornos ===
    use_daily = bool(getattr(settings, "METRICS_USE_DAILY", True))
    ret, basis = _returns_from_equity(df, use_daily=use_daily)

    # Ventana temporal del periodo (en días, al menos 1)
    t0 = pd.to_datetime(df["timestamp"].iloc[0], utc=True)
    t1 = pd.to_datetime(df["timestamp"].iloc[-1], utc=True)
    period_days = max((t1 - t0).days, 1)

    # === 3) Métricas principales basadas en la curva de equity ===
    equity0 = float(df["equity"].iloc[0])
    equity1 = float(df["equity"].iloc[-1])
    total_return = (equity1 / equity0) - 1 if equity0 > 0 else np.nan

    ann_days = int(getattr(settings, "METRICS_ANNUALIZATION_DAYS", 365))

    # Media y desviación estándar de retornos en la base elegida
    ret_std = float(ret.std()) if len(ret) > 0 else np.nan
    ret_mean = float(ret.mean()) if len(ret) > 0 else np.nan

    # Annualized return: elevamos de forma simple por días (no compuesta por número de barras)
    # Nota: esto asume que el periodo en días es la unidad de anualización a usar como exponente.
    annualized_return = (
        (1 + total_return) ** (ann_days / period_days) - 1 if np.isfinite(total_return) else np.nan
    )

    # Volatilidad anualizada: std(ret) * sqrt(ann_days)
    annualized_volatility = ret_std * np.sqrt(ann_days) if np.isfinite(ret_std) else np.nan

    # Sharpe (sin tasa libre de riesgo): mean/std * sqrt(ann_days)
    sharpe_ratio = (
        (ret_mean / ret_std) * np.sqrt(ann_days)
        if (np.isfinite(ret_mean) and ret_std and ret_std > 0)
        else np.nan
    )

    # Max Drawdown: mínimo de (equity / peak - 1)
    rolling_max = df["equity"].cummax()
    drawdown = (df["equity"] / rolling_max) - 1.0
    max_drawdown = float(drawdown.min()) if not drawdown.empty else np.nan

    # === 4) Lectura de trades para KPIs complementarios (opcional) ===
    trades_df = pd.read_csv(trades_file)
    n_trades = int(len(trades_df)) if not trades_df.empty else 0
    total_pnl = (
        float(trades_df["pnl"].sum())
        if ("pnl" in trades_df.columns and not trades_df.empty)
        else 0.0
    )

    # === 5) Componer y redondear resultados (None para no-numéricos) ===
    metrics = {
        "total_return": None if not np.isfinite(total_return) else round(total_return, 6),
        "annualized_return": (
            None if not np.isfinite(annualized_return) else round(annualized_return, 6)
        ),
        "annualized_volatility": (
            None if not np.isfinite(annualized_volatility) else round(annualized_volatility, 6)
        ),
        "sharpe_ratio": None if not np.isfinite(sharpe_ratio) else round(sharpe_ratio, 4),
        "max_drawdown": None if not np.isfinite(max_drawdown) else round(max_drawdown, 6),
        "n_trades": n_trades,
        "total_pnl": round(total_pnl, 2),
        "period_days": int(period_days),
        "equity_start": round(equity0, 2),
        "equity_end": round(equity1, 2),
        "start_timestamp": t0.isoformat(),
        "end_timestamp": t1.isoformat(),
        "returns_basis": basis,  # "daily" o "per-bar"
        "annualization_days": ann_days,  # por transparencia
    }

    # === 6) Guardar summary.json ===
    with open(summary_path, "w") as f:
        json.dump(metrics, f, indent=4)

    print(f"Resumen exportado a {summary_path}")
    return metrics


# --------------------------------------------------------------------------------------
# Ejecución directa (útil para probar fuera de __main__)
# --------------------------------------------------------------------------------------
if __name__ == "__main__":
    out = calculate_metrics()
    print(json.dumps(out, indent=4))
