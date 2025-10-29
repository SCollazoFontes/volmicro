# src/volmicro/const.py
"""
Constantes globales del paquete.

Este módulo debe contener únicamente valores **estables** que tengan impacto
en la compatibilidad entre partes del sistema (p. ej., el formato/contrato de
los CSVs de salida). Al centralizarlos aquí:

- Los tests pueden verificar expectativas claras (p. ej., schema_version).
- Cambiar una constante “de contrato” es una decisión explícita (PR dedicado).
- Evitamos “magia” o números sueltos repartidos por el código.

Convención
----------
- Usa nombres en MAYÚSCULAS.
- Añade comentarios que expliquen el propósito y consecuencias de editar la constante.
"""

# =============================================================================
# Versión del esquema de salida (CSV de trades)
# =============================================================================
# `SCHEMA_VERSION` identifica la versión del **esquema de columnas** exportado en
# `trades.csv`. Los tests (tests/test_trades_schema.py) esperan que esta constante
# valga 1 y que el CSV contenga ciertas columnas. Si en el futuro añades, renombras
# o eliminas columnas del CSV, incrementa este número y ajusta los tests para reflejar
# el nuevo contrato.
#
# Impacto:
# - Portfolio.trades_dataframe() incluye esta versión en la columna `schema_version`.
# - Los consumidores de los CSVs (scripts, dashboards) pueden actuar según esta versión.
SCHEMA_VERSION = 1
