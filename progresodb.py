"""
progreso_db.py — Sistema de pausa y reanudación con persistencia SQLite
=======================================================================
"""

import hashlib
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# ── Atributos de módulo — mantenidos por compatibilidad nominal ───────────────
# Mismos nombres que progreso.py. No se usan internamente (la DB es SQLite),
# pero se exponen por si algún código externo los referencia.
ARCHIVO_PROGRESO: str = "progreso.json"
_ARCHIVO_TMP:     str = "progreso.tmp"

# ── Configuración de la DB ─────────────────────────────────────────────────────
# Configurable via variable de entorno DB_PROGRESO_PATH en .env.
# Default: "progreso.db" en el directorio de trabajo actual.
_DB_DEFAULT: str = os.environ.get("DB_PROGRESO_PATH", "progreso.db")

# ── Schema SQL ─────────────────────────────────────────────────────────────────
_DDL_SESIONES: str = """
CREATE TABLE IF NOT EXISTS sesiones (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    inicio       TEXT,
    excel_path   TEXT,
    excel_hash   TEXT,
    carpeta_pdfs TEXT,
    url          TEXT,
    modo         TEXT,
    umbral       INTEGER DEFAULT 70,
    total        INTEGER,
    activa       INTEGER DEFAULT 1
);
"""

_DDL_PROCESADOS: str = """
CREATE TABLE IF NOT EXISTS procesados (
    sesion_id  INTEGER REFERENCES sesiones(id),
    cobro      TEXT,
    resultado  TEXT,
    ts         TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    PRIMARY KEY (sesion_id, cobro)
);
"""


# ── Helpers internos ───────────────────────────────────────────────────────────

def _get_conn(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Abre conexión con Row factory, WAL journal y foreign keys."""
    path: str = db_path or _DB_DEFAULT
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _init_db(db_path: Optional[str] = None) -> None:
    """Crea las tablas si no existen. Idempotente."""
    conn = _get_conn(db_path)
    try:
        conn.execute(_DDL_SESIONES)
        conn.execute(_DDL_PROCESADOS)
        conn.commit()
    finally:
        conn.close()


def _hash_excel(excel_path: str) -> str:
    """
    SHA256 truncado de los primeros 64KB — rápido y suficientemente único.
    Implementación idéntica a progreso.py.
    """
    try:
        with open(excel_path, "rb") as f:
            return hashlib.sha256(f.read(65536)).hexdigest()[:16]
    except Exception:
        return ""


# ── API pública — interfaz 100% idéntica a progreso.py ────────────────────────

def crear_sesion(
    excel_path: str,
    carpeta_pdfs: str,
    url: str,
    modo: str,
    total: int,
    db_path: Optional[str] = None,
) -> Dict:
    """
    Crea una nueva sesión activa (Opción B: una sola sesión activa).

    Firma idéntica a progreso.py:
        crear_sesion(excel_path, carpeta_pdfs, url, modo, total)

    bot_runner.py la llama como:
        crear_sesion(excel_path, carpeta_pdf, url, 'dryrun'|'real', len(clientes))

    En la misma transacción atómica (BEGIN/COMMIT):
      1. Desactiva las sesiones activas anteriores (activa=0).
      2. Elimina sus procesados huérfanos.
      3. Inserta la nueva sesión con activa=1.

    Retorna dict con estructura idéntica al JSON de progreso.py.
    """
    _init_db(db_path)
    inicio: str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    excel_hash: str = _hash_excel(excel_path)

    conn = _get_conn(db_path)
    try:
        conn.execute("BEGIN")

        # Limpiar sesiones activas anteriores + sus procesados huérfanos
        prev_rows = conn.execute(
            "SELECT id FROM sesiones WHERE activa = 1"
        ).fetchall()
        for row in prev_rows:
            conn.execute(
                "DELETE FROM procesados WHERE sesion_id = ?", (row["id"],)
            )
        conn.execute("UPDATE sesiones SET activa = 0 WHERE activa = 1")

        # Insertar nueva sesión
        cur = conn.execute(
            """
            INSERT INTO sesiones
                (inicio, excel_path, excel_hash, carpeta_pdfs, url, modo, total, activa)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (inicio, excel_path, excel_hash, carpeta_pdfs, url, modo, total),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        conn.close()
        raise

    conn.close()

    # Estructura idéntica al dict/JSON de progreso.py
    estado: Dict = {
        "inicio":       inicio,
        "excel_path":   excel_path,
        "excel_hash":   excel_hash,
        "carpeta_pdfs": carpeta_pdfs,
        "url":          url,
        "modo":         modo,
        "total":        total,
        "procesados":   {},
    }
    return estado


def registrar_procesado(
    cobro: str,
    resultado: str,
    db_path: Optional[str] = None,
) -> None:
    """
    Registra un cobro como procesado con su resultado.
    Firma idéntica a progreso.py: registrar_procesado(cobro, resultado).

    Si no hay sesión activa, no hace nada (igual a progreso.py cuando
    _cargar() retorna None y el dict update se ignora).
    Escritura atómica via transacción SQLite.
    """
    _init_db(db_path)
    conn = _get_conn(db_path)
    try:
        sesion_row = conn.execute(
            "SELECT id FROM sesiones WHERE activa = 1 ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if sesion_row is None:
            return  # Sin sesión activa — comportamiento idéntico a progreso.py

        sesion_id: int = sesion_row["id"]
        conn.execute("BEGIN")
        conn.execute(
            """
            INSERT OR REPLACE INTO procesados (sesion_id, cobro, resultado)
            VALUES (?, ?, ?)
            """,
            (sesion_id, cobro, resultado),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        conn.close()
        raise

    conn.close()


def hay_sesion_pendiente(db_path: Optional[str] = None) -> bool:
    """
    Retorna True si existe una sesión activa en la DB.
    Firma idéntica a progreso.py: hay_sesion_pendiente().

    En progreso.py verifica si el archivo progreso.json existe.
    Aquí verifica si hay al menos una fila con activa=1.
    Semántica equivalente: True = hay sesión que puede reanudarse.
    """
    _init_db(db_path)
    conn = _get_conn(db_path)
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM sesiones WHERE activa = 1"
        ).fetchone()
        return row["c"] > 0
    finally:
        conn.close()


def cargar_sesion(db_path: Optional[str] = None) -> Optional[Dict]:
    """
    Carga la sesión guardada. Retorna None si no existe.
    Firma idéntica a progreso.py: cargar_sesion().
    Estructura del dict retornado idéntica al JSON de progreso.py.
    """
    _init_db(db_path)
    conn = _get_conn(db_path)
    try:
        row = conn.execute(
            """
            SELECT id, inicio, excel_path, excel_hash, carpeta_pdfs,
                   url, modo, umbral, total
            FROM   sesiones
            WHERE  activa = 1
            ORDER  BY id DESC LIMIT 1
            """
        ).fetchone()
        if row is None:
            return None

        sesion_id: int = row["id"]
        proc_rows = conn.execute(
            "SELECT cobro, resultado FROM procesados WHERE sesion_id = ?",
            (sesion_id,),
        ).fetchall()

        procesados: Dict[str, str] = {r["cobro"]: r["resultado"] for r in proc_rows}

        # Estructura idéntica al JSON de progreso.py
        return {
            "inicio":       row["inicio"],
            "excel_path":   row["excel_path"],
            "excel_hash":   row["excel_hash"],
            "carpeta_pdfs": row["carpeta_pdfs"],
            "url":          row["url"],
            "modo":         row["modo"],
            "umbral":       row["umbral"],
            "total":        row["total"],
            "procesados":   procesados,
        }
    finally:
        conn.close()


def obtener_pendientes(
    clientes: List[Dict],
    logger: Optional[logging.Logger] = None,
    db_path: Optional[str] = None,
) -> List[Dict]:
    """
    Determina qué clientes faltan procesar combinando dos fuentes.
    Lógica idéntica a progreso.py:

      1. SQLite (rápido): si cobro tiene resultado=="OK" → se saltea
      2. Excel (seguro): si enviada.upper()=="OK" → se saltea

    Firma idéntica a progreso.py: obtener_pendientes(clientes, logger=None).
    Cada cliente es un dict con claves "cobro" y opcionalmente "enviada".

    Nota: solo "OK" en procesados_internos saltea al cliente, exactamente
    como progreso.py que usa procesados_internos.get(cobro) == "OK".
    Otros resultados (ERROR_ID, YA_FACTURADO, etc.) se reintentarán.
    """
    _init_db(db_path)
    sesion: Optional[Dict] = cargar_sesion(db_path)
    procesados_internos: Dict[str, str] = sesion.get("procesados", {}) if sesion else {}

    pendientes: List[Dict] = []
    salteados_interno: int = 0
    salteados_excel:   int = 0

    for cliente in clientes:
        cobro:   str = cliente["cobro"]
        enviada: str = cliente.get("enviada", "")

        # Fuente 1: SQLite — solo "OK" saltea (idéntico a progreso.py)
        if procesados_internos.get(cobro) == "OK":
            salteados_interno += 1
            continue

        # Fuente 2: columna "enviada" del Excel (segunda verificación cruzada)
        if enviada.upper() == "OK":
            salteados_excel += 1
            continue

        pendientes.append(cliente)

    if logger and (salteados_interno > 0 or salteados_excel > 0):
        logger.info(
            f"Reanudación: {salteados_interno} salteados por progreso interno, "
            f"{salteados_excel} salteados por Excel — "
            f"{len(pendientes)} pendientes."
        )

    return pendientes


def limpiar_sesion(db_path: Optional[str] = None) -> None:
    """
    Desactiva la sesión activa y elimina sus procesados.
    Firma idéntica a progreso.py: limpiar_sesion().
    Escritura atómica via transacción SQLite.
    """
    _init_db(db_path)
    conn = _get_conn(db_path)
    try:
        conn.execute("BEGIN")
        rows = conn.execute(
            "SELECT id FROM sesiones WHERE activa = 1"
        ).fetchall()
        for row in rows:
            conn.execute(
                "DELETE FROM procesados WHERE sesion_id = ?", (row["id"],)
            )
        conn.execute("UPDATE sesiones SET activa = 0 WHERE activa = 1")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        conn.close()
        raise

    conn.close()


def resumen_sesion(db_path: Optional[str] = None) -> Dict:
    """
    Retorna estadísticas de la sesión actual.
    Firma y estructura de retorno idénticas a progreso.py:
        {total, procesados, ok, errores, inicio, pendientes}
    Retorna {} si no hay sesión activa.
    """
    estado: Optional[Dict] = cargar_sesion(db_path)
    if not estado:
        return {}

    procesados: Dict[str, str] = estado.get("procesados", {})
    return {
        "total":      estado.get("total", 0),
        "procesados": len(procesados),
        "ok":         sum(1 for v in procesados.values() if v == "OK"),
        "errores":    sum(1 for v in procesados.values() if v != "OK"),
        "inicio":     estado.get("inicio", ""),
        "pendientes": (estado.get("total", 0) or 0) - len(procesados),
    }