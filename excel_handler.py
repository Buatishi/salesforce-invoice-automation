# =============================================================================
# excel_handler.py — Lectura, filtrado y escritura del Excel
# =============================================================================
import logging
import unicodedata
import re
from pathlib import Path
from typing import Any, List, Dict, Optional, Tuple

import pandas as pd
import openpyxl
from openpyxl.workbook import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from config import (
    COL_NOMBRE_OPORTUNIDAD,
    COL_COBRO,
    COL_ENVIADAS,
    FILA_ENCABEZADO,
)


# =============================================================================
# NORMALIZACIÓN DE TEXTO
# =============================================================================

def normalizar_texto(texto: str) -> str:
    """
    Normaliza un texto para comparaciones flexibles:
    - Convierte a minúsculas
    - Elimina tildes y diacríticos
    - Elimina espacios invisibles y dobles
    - Elimina caracteres no alfanuméricos (excepto espacios)
    """
    if not isinstance(texto, str):
        return ""

    texto = texto.strip()
    texto = re.sub(r'\s+', ' ', texto)
    texto = texto.lower()
    texto = unicodedata.normalize('NFD', texto)
    texto = ''.join(c for c in texto if unicodedata.category(c) != 'Mn')
    texto = re.sub(r'[^a-z0-9 ]', ' ', texto)
    texto = re.sub(r'\s+', ' ', texto).strip()

    return texto


# =============================================================================
# ESCRITOR PERSISTENTE DEL EXCEL
# =============================================================================

class ExcelWriter:
    """
    Mantiene wb / ws / col_idx abiertos en memoria durante toda la corrida.
    Solo toca el disco cuando se llama flush() o al salir del context manager.

    Ventaja: con 50 clientes se elimina la apertura/cierre/scan repetido;
    el archivo se abre una vez y se guarda una sola vez por cliente.

    Uso recomendado (context manager):
        with ExcelWriter(excel_path, logger) as writer:
            writer.marcar_ok(fila_A)
            writer.marcar_ok(fila_B)
        # flush + cierre automático al salir del with

    Uso explícito:
        writer = ExcelWriter(excel_path, logger)
        writer.marcar_ok(fila)
        writer.flush()    # persiste cambios
        writer.cerrar()   # libera workbook
    """

    def __init__(
        self,
        excel_path: str,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._path:    str                      = excel_path
        self._logger:  Optional[logging.Logger] = logger
        self._wb:      Optional[Workbook]        = None
        self._ws:      Optional[Worksheet]       = None
        self._col_idx: Optional[int]             = None
        self._dirty:   bool                      = False

    # ── Apertura lazy ────────────────────────────────────────────────────────

    def _asegurar_cargado(self) -> bool:
        """
        Carga el workbook si todavía no fue abierto (lazy).
        Retorna True si está listo para operar.
        """
        if self._wb is not None:
            return True
        try:
            self._wb      = openpyxl.load_workbook(self._path)
            self._ws      = self._wb.active
            self._col_idx = self._encontrar_columna()
            if self._col_idx is None:
                if self._logger:
                    self._logger.warning(
                        f"ExcelWriter: columna '{COL_ENVIADAS}' no encontrada "
                        f"en '{self._path}'"
                    )
                return False
            return True
        except Exception as e:
            if self._logger:
                self._logger.warning(
                    f"ExcelWriter: no se pudo abrir '{self._path}': {e}"
                )
            return False

    def _encontrar_columna(self) -> Optional[int]:
        """Retorna el índice 1-based de la columna ENVIADAS en el encabezado."""
        if self._ws is None:
            return None
        for cell in self._ws[FILA_ENCABEZADO]:
            if cell.value and str(cell.value).strip() == COL_ENVIADAS:
                return cell.column
        return None

    # ── Operaciones públicas ─────────────────────────────────────────────────

    def marcar_ok(self, fila: int) -> bool:
        """
        Escribe "OK" en la columna ENVIADAS de la fila indicada.
        Solo modifica la memoria; persiste con flush().
        Retorna True si la marca se aplicó correctamente.
        """
        if not self._asegurar_cargado():
            return False
        if self._ws is None or self._col_idx is None:
            return False
        try:
            self._ws.cell(row=fila, column=self._col_idx).value = "OK"
            self._dirty = True
            if self._logger:
                self._logger.info(
                    f"Excel (pendiente flush) — fila {fila} marcada como OK"
                )
            return True
        except Exception as e:
            if self._logger:
                self._logger.warning(
                    f"ExcelWriter: error al marcar fila {fila}: {e}"
                )
            return False

    def flush(self) -> bool:
        """
        Guarda en disco todos los cambios acumulados.
        Es un no-op si no hay cambios (_dirty == False).
        Retorna True si se guardó correctamente (o no había nada que guardar).
        """
        if not self._dirty:
            return True
        if self._wb is None:
            return False
        try:
            self._wb.save(self._path)
            self._dirty = False
            if self._logger:
                self._logger.info("Excel guardado (flush OK)")
            return True
        except Exception as e:
            if self._logger:
                self._logger.warning(
                    f"ExcelWriter: error al guardar '{self._path}': {e}"
                )
            return False

    def cerrar(self) -> None:
        """Hace flush final y libera el workbook de memoria."""
        self.flush()
        self._wb = None
        self._ws = None

    # ── Context manager ──────────────────────────────────────────────────────

    def __enter__(self) -> "ExcelWriter":
        return self

    def __exit__(self, *_: Any) -> None:
        self.cerrar()


# =============================================================================
# LECTURA Y FILTRADO DEL EXCEL
# =============================================================================

def _detectar_hoja_valida(
    excel_path: str,
    columnas_requeridas: List[str],
    logger: Optional[logging.Logger] = None,
) -> Tuple[Optional[pd.DataFrame], str]:
    """
    Itera sobre todas las hojas del Excel buscando la primera que contenga
    exactamente las columnas requeridas.

    Retorna (DataFrame, nombre_hoja) si se encontró una hoja válida,
    o (None, "") si ninguna hoja cumple el esquema.
    """
    try:
        nombres_hojas: List[str] = pd.ExcelFile(excel_path).sheet_names
    except Exception as e:
        raise Exception(f"Error al abrir el Excel para inspeccionar hojas: {e}")

    for nombre_hoja in nombres_hojas:
        try:
            df_candidata: pd.DataFrame = pd.read_excel(
                excel_path,
                sheet_name=nombre_hoja,
                header=FILA_ENCABEZADO - 1,
                dtype=str,
            )
        except Exception:
            continue  # Hoja ilegible → intentar la siguiente

        faltantes = [c for c in columnas_requeridas if c not in df_candidata.columns]
        if not faltantes:
            if logger:
                logger.info(
                    f"Excel: hoja válida encontrada — '{nombre_hoja}' "
                    f"(total hojas: {len(nombres_hojas)})."
                )
            return df_candidata, nombre_hoja

    return None, ""


def _validar_esquema(
    df: pd.DataFrame,
    columnas_requeridas: List[str],
    excel_path: str,
    nombre_hoja: str,
) -> None:
    """
    Verifica que el DataFrame tenga las columnas requeridas.
    Lanza ValueError con mensaje accionable si falta alguna.
    """
    faltantes = [c for c in columnas_requeridas if c not in df.columns]
    if faltantes:
        disponibles = list(df.columns)
        raise ValueError(
            f"Columnas no encontradas en la hoja '{nombre_hoja}' de '{excel_path}':\n"
            f"  Faltantes : {faltantes}\n"
            f"  Disponibles: {disponibles}\n"
            f"Verificá los nombres de columna en config.py o en el Excel."
        )


def cargar_clientes(
    excel_path: str,
    logger: Optional[logging.Logger] = None,
) -> List[Dict[str, Any]]:
    """
    Lee el Excel y retorna la lista de clientes pendientes de procesar.

    Soporte multi-hoja: detecta automáticamente la primera hoja que contenga
    las columnas requeridas (COL_NOMBRE_OPORTUNIDAD, COL_COBRO, COL_ENVIADAS).
    Si ninguna hoja cumple el esquema, lanza ValueError con diagnóstico claro.

    Filtra automáticamente:
    - Filas ya marcadas como "OK" en la columna ENVIADAS
    - Filas sin número de cobro válido
    - Filas completamente vacías

    Retorna lista de dicts con:
    - fila    : número de fila real en el Excel (para escribir OK después)
    - nombre  : nombre de la oportunidad (Columna A)
    - cobro   : número de cobro (Columna B) — clave de búsqueda en Salesforce
    - enviada : valor actual de la columna ENVIADAS
    """
    columnas_requeridas: List[str] = [COL_NOMBRE_OPORTUNIDAD, COL_COBRO, COL_ENVIADAS]

    # ── Apertura y detección de hoja ─────────────────────────────────────────
    if not Path(excel_path).exists():
        raise FileNotFoundError(f"No se encontró el Excel en: {excel_path}")

    df: Optional[pd.DataFrame]
    nombre_hoja: str

    try:
        # Intentar la hoja activa primero (compatibilidad con archivos de una hoja)
        df_primera: pd.DataFrame = pd.read_excel(
            excel_path, header=FILA_ENCABEZADO - 1, dtype=str
        )
        faltantes_primera = [c for c in columnas_requeridas if c not in df_primera.columns]
        if not faltantes_primera:
            df = df_primera
            nombre_hoja = "hoja activa"
        else:
            # La hoja activa no tiene el esquema → buscar en todas las hojas
            df, nombre_hoja = _detectar_hoja_valida(excel_path, columnas_requeridas, logger)
    except FileNotFoundError:
        raise
    except Exception as e:
        raise Exception(f"Error al leer el Excel: {e}")

    if df is None:
        # Ninguna hoja cumple el esquema — listar lo que hay para diagnóstico
        try:
            hojas_info: List[str] = []
            for h in pd.ExcelFile(excel_path).sheet_names:
                cols = list(pd.read_excel(excel_path, sheet_name=h, nrows=0, dtype=str).columns)
                hojas_info.append(f"  '{h}': {cols}")
            detalle = "\n".join(hojas_info)
        except Exception:
            detalle = "  (no se pudieron leer los encabezados)"
        raise ValueError(
            f"No se encontró ninguna hoja con el esquema requerido en '{excel_path}'.\n"
            f"Columnas requeridas: {columnas_requeridas}\n"
            f"Hojas encontradas:\n{detalle}\n"
            f"Verificá los nombres de columna en config.py o en el Excel."
        )

    # ── Validación de esquema (doble check, cubre edge cases de _detectar_hoja_valida) ──
    _validar_esquema(df, columnas_requeridas, excel_path, nombre_hoja)

    # ── Filtrado y construcción de lista ─────────────────────────────────────
    clientes: List[Dict[str, Any]] = []

    for idx, row in df.iterrows():
        fila_excel: int = int(idx) + FILA_ENCABEZADO + 1  # type: ignore[arg-type]

        nombre:  str = str(row[COL_NOMBRE_OPORTUNIDAD]).strip() if pd.notna(row[COL_NOMBRE_OPORTUNIDAD]) else ""
        cobro:   str = str(row[COL_COBRO]).strip()               if pd.notna(row[COL_COBRO])              else ""
        enviada: str = str(row[COL_ENVIADAS]).strip().upper()     if pd.notna(row[COL_ENVIADAS])           else ""

        # Ignorar filas sin cobro válido
        if not cobro or cobro.upper() in ("NAN", "NONE"):
            continue

        # Ignorar filas ya procesadas
        if enviada == "OK":
            continue

        clientes.append({
            "fila":    fila_excel,
            "nombre":  nombre,
            "cobro":   cobro,
            "enviada": enviada,
        })

    if logger:
        logger.info(
            f"Excel cargado ('{nombre_hoja}') — clientes pendientes: {len(clientes)}"
        )

    return clientes


# =============================================================================
# ESCRITURA DE OK — función de compatibilidad (un solo cliente)
# =============================================================================

def marcar_ok(
    excel_path: str,
    fila: int,
    logger: Optional[logging.Logger] = None,
) -> bool:
    """
    Escribe "OK" en la columna ENVIADAS para la fila indicada.

    Compatibilidad con bot_runner.py: abre, marca y guarda en una sola llamada.
    Para lotes, preferir ExcelWriter como context manager para evitar
    reabrir el archivo en cada cliente.
    """
    writer = ExcelWriter(excel_path, logger)
    if not writer.marcar_ok(fila):
        return False
    return writer.flush()