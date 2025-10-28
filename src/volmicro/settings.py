import os
from pathlib import Path
from datetime import datetime
import re

# ---------------------------
# Helpers de entorno
# ---------------------------
def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except Exception:
        return float(default)

def _i(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except Exception:
        return int(default)

def _b(name: str, default: bool) -> bool:
    val = str(os.getenv(name, str(default))).lower()
    return val in {"1", "true", "yes", "y", "on"}

# ---------------------------
# Config principal del backtest
# ---------------------------
SYMBOL      = os.getenv("SYMBOL", "BTCUSDT")
INTERVAL    = os.getenv("INTERVAL", "1h")
LIMIT       = _i("LIMIT", 200)

TESTNET     = _b("TESTNET", True)

# Costes explícitos del exchange (comisión)
FEE_BPS     = _f("FEE_BPS", 1.0)        # 1 bp = 0.01%, 100 bps = 1%

# Tamaño de la orden (proporción del cash disponible)
ALLOC_PCT   = _f("ALLOC_PCT", 0.10)

# Si el realized PnL ya viene neto de fees en el ledger
REALIZED_NET_FEES = _b("REALIZED_NET_FEES", False)

LOG_EVERY   = _i("LOG_EVERY", 10)

# ---------------------------
# Rutas de proyecto (fuera de src/)
# ---------------------------
# Raíz del proyecto (carpeta padre de src/)
# settings.py => .../volmicro/src/volmicro/settings.py
# parents[2]  => .../volmicro/
try:
    PROJECT_ROOT = Path(__file__).resolve().parents[2]
except Exception:
    # Fallback: carpeta actual
    PROJECT_ROOT = Path(".").resolve()

# Carpeta de reports y rules (al nivel del proyecto)
REPORTS_DIR = PROJECT_ROOT / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

RULES_DIR = PROJECT_ROOT / "rules"
RULES_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------
# Subcarpetas de reports: <SYMBOL>_<STRATEGY>_<YYYY-MM-DD>_runXX
# ---------------------------
def generate_report_dir(symbol: str, strategy_name: str) -> Path:
    """Genera una subcarpeta con nombre <SYMBOL>_<STRATEGY>_<YYYY-MM-DD>_runXX en reports/."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    safe_strategy = re.sub(r'[^A-Za-z0-9_-]', '', strategy_name)

    prefix = f"{symbol}_{safe_strategy}_{date_str}_run"
    existing = [p for p in REPORTS_DIR.glob(f"{prefix}*") if p.is_dir()]

    run_number = len(existing) + 1
    folder_name = f"{prefix}{run_number:02d}"

    report_dir = REPORTS_DIR / folder_name
    report_dir.mkdir(parents=True, exist_ok=True)
    return report_dir

# ---------------------------
# Métricas
# ---------------------------
# True  -> usar retornos diarios (resample 1D) para vol/Sharpe/anualización
# False -> usar retornos por barra (frecuencia de tus datos)
METRICS_USE_DAILY = _b("METRICS_USE_DAILY", True)

# Días de anualización (252 = sesiones; 365 = días naturales)
METRICS_ANNUALIZATION_DAYS = _i("METRICS_ANNUALIZATION_DAYS", 252)

# ---------------------------
# Slippage (coste implícito de ejecución)
# ---------------------------
# Slippage en bps (aplicado sobre el precio de ejecución)
# Ejemplo: 5 bps = 0.05% => buy: price*(1+0.0005), sell: price*(1-0.0005)
SLIPPAGE_BPS = _f("SLIPPAGE_BPS", 5.0)

# ---------------------------
# Reglas de Binance (caché)
# ---------------------------
# Usa cache local para rules/<SYMBOL>_rules.json
RULES_USE_CACHE = _b("RULES_USE_CACHE", True)

# Fuerza refrescar desde Binance ignorando la cache
RULES_REFRESH = _b("RULES_REFRESH", False)
