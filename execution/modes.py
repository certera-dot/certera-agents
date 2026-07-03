"""
MODOS DE OPERACIÓN
==================
MANUAL   → solo alertas, cero ejecución automática
SEMI_AUTO → propone orden, espera confirmación Telegram
AUTO      → ejecuta dentro de parámetros de risk_manager
"""
from enum import Enum

class OperationMode(str, Enum):
    MANUAL    = "manual"
    SEMI_AUTO = "semi"
    AUTO      = "auto"
