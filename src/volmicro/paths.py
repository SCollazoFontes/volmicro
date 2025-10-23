# src/volmicro/paths.py
from pathlib import Path

# Ruta raíz del proyecto (sube desde src/volmicro hasta el repo principal)
ROOT_DIR = Path(__file__).resolve().parents[2]

# Rutas base
SRC_DIR = ROOT_DIR / "src"
DATA_DIR = ROOT_DIR / "data"
NOTEBOOKS_DIR = ROOT_DIR / "notebooks"

# Subcarpetas de datos
DATA_RAW_DIR = DATA_DIR / "raw"
DATA_PROCESSED_DIR = DATA_DIR / "processed"

# Crear las carpetas si no existen
for d in [DATA_DIR, DATA_RAW_DIR, DATA_PROCESSED_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Exportables
__all__ = [
    "ROOT_DIR",
    "SRC_DIR",
    "DATA_DIR",
    "DATA_RAW_DIR",
    "DATA_PROCESSED_DIR",
    "NOTEBOOKS_DIR",
]
