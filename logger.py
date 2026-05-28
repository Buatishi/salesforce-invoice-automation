# =============================================================================
# logger.py — Log estructurado con timestamp y rotación automática
# =============================================================================

import logging
import os
import time as _time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from config import CARPETA_LOGS, LOG_RETENTION_DIAS


# =============================================================================
# ROTACIÓN DE LOGS
# =============================================================================

def _limpiar_logs_viejos(
    carpeta:  str = CARPETA_LOGS,
    max_dias: int = LOG_RETENTION_DIAS,
) -> None:
    """
    Elimina archivos log_*.txt con mtime anterior a max_dias días.
    Silencioso ante errores — nunca interrumpe el proceso.
    """
    umbral: float = _time.time() - (max_dias * 86400)
    try:
        for log_file in Path(carpeta).glob("log_*.txt"):
            try:
                if log_file.stat().st_mtime < umbral:
                    log_file.unlink(missing_ok=True)
            except Exception:
                pass
    except Exception:
        pass


# =============================================================================
# INICIALIZACIÓN DEL LOGGER
# =============================================================================

def inicializar_logger(
    dryrun:   bool = False,
    carpeta:  str  = CARPETA_LOGS,
) -> logging.Logger:
    """
    Crea y configura el logger para una corrida del bot.

    - Escribe en archivo: logs/log_YYYYMMDD_HHMMSS[_dryrun].txt
    - Formato: [YYYY-MM-DD HH:MM:SS] LEVEL — mensaje
    - Nivel: INFO para corridas reales, DEBUG para dry-run
    - Ejecuta rotación de logs viejos al inicio de cada corrida

    Retorna el logger configurado.
    """
    os.makedirs(carpeta, exist_ok=True)

    # Rotar logs viejos antes de crear el nuevo
    _limpiar_logs_viejos(carpeta)

    # Nombre del archivo de log
    timestamp: str = datetime.now().strftime("%Y%m%d_%H%M%S")
    sufijo:    str = "_dryrun" if dryrun else ""
    ruta_log:  str = os.path.join(carpeta, f"log_{timestamp}{sufijo}.txt")

    # Logger con nombre único por corrida (evita handlers duplicados en reinicios)
    nombre_logger: str = f"invoiceflow_{timestamp}"
    logger:        logging.Logger = logging.getLogger(nombre_logger)
    logger.setLevel(logging.DEBUG if dryrun else logging.INFO)

    # Evitar handlers duplicados si el logger ya existe (no debería ocurrir
    # con nombres únicos por timestamp, pero por seguridad)
    if logger.handlers:
        logger.handlers.clear()

    # Handler de archivo
    fmt = logging.Formatter(
        fmt="[%(asctime)s] %(levelname)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = logging.FileHandler(ruta_log, encoding="utf-8")
    file_handler.setFormatter(fmt)
    file_handler.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)

    # Handler de consola (para desarrollo local)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)
    console_handler.setLevel(logging.INFO)
    logger.addHandler(console_handler)

    logger.info(f"Logger inicializado — {'DRY-RUN' if dryrun else 'MODO REAL'}")
    logger.info(f"Archivo de log: {ruta_log}")

    return logger


# =============================================================================
# HELPER DE REGISTRO ESTRUCTURADO
# =============================================================================

def registrar(
    logger:   logging.Logger,
    cobro:    str,
    nombre:   str,
    estado:   str,
    detalle:  str = "",
) -> None:
    """
    Registra el resultado de procesar un cliente en formato estructurado.

    Formato: [COBRO] NOMBRE → ESTADO | detalle
    Usado por bot_runner.py para uniformidad en los logs.
    """
    mensaje: str = f"[{cobro}] {nombre} → {estado}"
    if detalle:
        mensaje += f" | {detalle}"

    if estado == "OK" or estado == "YA_FACTURADO":
        logger.info(mensaje)
    else:
        logger.warning(mensaje)