# src/volmicro/settings.py
"""
Módulo de configuración del proyecto.

Objetivos clave:
- Centralizar parámetros de backtest/ejecución (símbolo, intervalo, límites, costes, sizing).
- Permitir sobreescritura vía variables de entorno (Docker, CI, CLI, .env).
- Gestionar rutas (raíz del proyecto, reports/, rules/) de forma consistente.
- Proveer utilidades para crear subcarpetas de reportes reproducibles (<SYMBOL>_<STRATEGY>_<YYYY-MM-DD>_runXX).
- Exponer flags para métricas y slippage.
- Añadir validaciones ligeras (intervalos válidos, límites, rangos) para evitar fallos silenciosos.

Decisiones:
- Se fuerzan ciertos parámetros a rangos razonables (p.ej., LIMIT en [1,1000], ALLOC_PCT en [0,1]).
- Se usa UTC en el nombre de las carpetas de reportes para consistencia entre zonas horarias.
- Se crea reports/ y rules/ bajo demanda (o al importar, según prefieras).
"""

import os
from pathlib import Path
from datetime import datetime
from typing import Iterable
import re

# ---------------------------
# Helpers de entorno
# ---------------------------
def _f(name: str, default: float) -> float:
    """
    Lee una variable de entorno y la castea a float.
    Si no existe o falla el casteo, devuelve el valor por defecto.
    """
    try:
        return float(os.getenv(name, default))
    except Exception:
        return float(default)

def _i(name: str, default: int) -> int:
    """
    Lee una variable de entorno y la castea a int.
    Si no existe o falla el casteo, devuelve el valor por defecto.
    """
    try:
        return int(os.getenv(name, default))
    except Exception:
        return int(default)

def _b(name: str, default: bool) -> bool:
    """
    Lee una variable de entorno booleana, admitiendo varios formatos comunes:
    "1", "true", "yes", "y", "on" (case-insensitive) => True
    Cualquier otro valor => False
    """
    val = str(os.getenv(name, str(default))).lower()
    return val in {"1", "true", "yes", "y", "on"}


# ---------------------------
# Config principal del backtest
# ---------------------------

# Símbolo del instrumento (ej. "BTCUSDT"); lo normalizamos a mayúsculas para coherencia.
SYMBOL = os.getenv("SYMBOL", "BTCUSDT").upper()

# Intervalos válidos de Binance (puedes ampliar si activas otros en tu feed).
_VALID_INTERVALS: set[str] = {
    "1s", "1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h",
    "12h", "1d", "3d", "1w", "1M",
}
# Si el usuario define un intervalo inválido, hacemos fallback a "1h" para no romper la descarga.
_INTER = os.getenv("INTERVAL", "1h")
INTERVAL = _INTER if _INTER in _VALID_INTERVALS else "1h"

# Límite de klines a pedir; acotamos a [1, 1000] que es el máximo típico.
_LIMIT_RAW = _i("LIMIT", 200)
LIMIT = max(1, min(1000, _LIMIT_RAW))

# Modo red/testnet por defecto en True (más seguro para pruebas).
TESTNET = _b("TESTNET", True)

# Coste explícito (comisión) en basis points (bps):
# 1 bp = 0.01%; 100 bps = 1%. Forzamos a no-negativo.
_FEE_BPS = _f("FEE_BPS", 1.0)
FEE_BPS = max(0.0, _FEE_BPS)

# Tamaño de orden como proporción del cash disponible.
# Se fuerza a [0,1] para evitar valores imposibles.
_ALLOC = _f("ALLOC_PCT", 0.10)
ALLOC_PCT = min(1.0, max(0.0, _ALLOC))

# Si el realized PnL en el ledger ya viene neto de fees (afecta al reporting).
REALIZED_NET_FEES = _b("REALIZED_NET_FEES", False)

# Frecuencia de logging del motor (cada cuántas barras loguear en nivel INFO).
# 0 => desactiva logs intermedios (solo el primero y eventos clave).
LOG_EVERY = max(0, _i("LOG_EVERY", 10))


# ---------------------------
# Rutas de proyecto (fuera de src/)
# ---------------------------

# Raíz del proyecto (carpeta padre de src/). Ej.:
# settings.py => .../volmicro/src/volmicro/settings.py
# parents[2]  => .../volmicro/
try:
    PROJECT_ROOT = Path(__file__).resolve().parents[2]
except Exception:
    # Fallback: carpeta actual si no se puede resolver (entornos raros).
    PROJECT_ROOT = Path(".").resolve()

# Directorios de salida/cache a nivel de proyecto.
REPORTS_DIR = PROJECT_ROOT / "reports"
RULES_DIR = PROJECT_ROOT / "rules"

# Puedes crear estas carpetas al importar (comodidad DX)...
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
RULES_DIR.mkdir(parents=True, exist_ok=True)
# ...o comentarlas y crearlas bajo demanda desde las funciones
# según tus preferencias.


# ---------------------------
# Subcarpetas de reports: <SYMBOL>_<STRATEGY>_<YYYY-MM-DD>_runXX
# ---------------------------

def _next_run_number(existing_dirs: Iterable[Path], prefix: str) -> int:
    """
    Dado un conjunto de directorios existentes y un prefijo, encuentra
    el mayor sufijo numérico runNN y devuelve el siguiente (NN+1).
    Evita “huecos” si se han borrado runs antiguos.

    - existing_dirs: lista de Paths tipo ".../reports/BTCUSDT_MA_2025-10-29_run03"
    - prefix      : "BTCUSDT_MA_2025-10-29_run"
    """
    pat = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    nums = []
    for p in existing_dirs:
        m = pat.match(p.name)
        if m:
            try:
                nums.append(int(m.group(1)))
            except ValueError:
                pass
    return (max(nums) + 1) if nums else 1


def generate_report_dir(symbol: str, strategy_name: str) -> Path:
    """
    Crea una subcarpeta dentro de reports/ con el patrón:
      <SYMBOL>_<STRATEGY>_<YYYY-MM-DD>_runXX

    - symbol        : símbolo del activo (se recomienda ya en mayúsculas).
    - strategy_name : nombre de la clase/estrategia; se sanea para usarlo en el path.

    Notas:
    - Se usa fecha en **UTC** para consistencia entre zonas horarias.
    - Se detecta el siguiente runXX continuo basado en carpetas existentes.
    """
    # Fecha en UTC para reproducibilidad (evita diferencias por TZ locales)
    date_str = datetime.utcnow().strftime("%Y-%m-%d")

    # Sanitizamos el nombre de estrategia para que sea path-safe (sin espacios o chars raros)
    safe_strategy = re.sub(r'[^A-Za-z0-9_-]', '', strategy_name)

    prefix = f"{symbol}_{safe_strategy}_{date_str}_run"
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)  # creación bajo demanda
    existing = [p for p in REPORTS_DIR.glob(f"{prefix}*") if p.is_dir()]

    run_number = _next_run_number(existing, prefix)
    folder_name = f"{prefix}{run_number:02d}"

    report_dir = REPORTS_DIR / folder_name
    report_dir.mkdir(parents=True, exist_ok=True)
    return report_dir


# ---------------------------
# Métricas
# ---------------------------

# Si True, se usan retornos diarios (resample 1D) para vol/Sharpe/anualización.
# Si False, se usan retornos por barra (frecuencia original de tus datos).
METRICS_USE_DAILY = _b("METRICS_USE_DAILY", True)

# Días para anualizar métricas. 252 ≈ sesiones bursátiles; 365 ≈ días naturales.
# Se fuerza a >=1 para evitar divisiones por cero.
METRICS_ANNUALIZATION_DAYS = max(1, _i("METRICS_ANNUALIZATION_DAYS", 252))


# ---------------------------
# Slippage (coste implícito de ejecución)
# ---------------------------

# Slippage en bps aplicado al precio de referencia:
# - BUY  => price * (1 + bps/10_000)
# - SELL => price * (1 - bps/10_000)
# Se fuerza a no-negativo.
_SLIP = _f("SLIPPAGE_BPS", 5.0)
SLIPPAGE_BPS = max(0.0, _SLIP)


# ---------------------------
# Reglas de Binance (caché)
# ---------------------------

# Si True, intentará leer reglas del símbolo desde cache local rules/<SYMBOL>_rules.json
RULES_USE_CACHE = _b("RULES_USE_CACHE", True)

# Si True, ignorará la cache y refrescará desde Binance.
RULES_REFRESH = _b("RULES_REFRESH", False)
