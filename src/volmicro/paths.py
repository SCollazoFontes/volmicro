from pathlib import Path

# Raíz del proyecto: asume que este archivo vive en src/volmicro/paths.py
ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
NOTEBOOKS_DIR = ROOT / "notebooks"
SRC_DIR = ROOT / "src"
