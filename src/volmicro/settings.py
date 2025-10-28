import os

def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except Exception:
        return float(default)

SYMBOL      = os.getenv("SYMBOL", "BTCUSDT")
INTERVAL    = os.getenv("INTERVAL", "1h")
LIMIT       = int(os.getenv("LIMIT", "200"))
TESTNET     = os.getenv("TESTNET", "true").lower() in {"1","true","yes","y"}
FEE_BPS     = _f("FEE_BPS", 1.0)
ALLOC_PCT   = _f("ALLOC_PCT", 0.10)
REALIZED_NET_FEES = os.getenv("REALIZED_NET_FEES", "false").lower() in {"1","true","yes","y"}
LOG_EVERY   = int(os.getenv("LOG_EVERY", "10"))
