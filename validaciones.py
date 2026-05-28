# =============================================================================
# validaciones.py — Verificaciones previas al inicio del bot
# =============================================================================
# Se ejecutan ANTES de abrir el navegador.
# Si algo falla, el operador lo sabe con un mensaje claro antes de perder tiempo.
# =============================================================================

import re
import pandas as pd
from pathlib import Path
from typing import List, Tuple

from config import (
    COL_NOMBRE_OPORTUNIDAD,
    COL_COBRO,
    COL_ENVIADAS,
    FILA_ENCABEZADO,
    SALESFORCE_USERNAME,
    SALESFORCE_PASSWORD,
)


def validar_todo(url: str, excel_path: str, carpeta_pdfs: str) -> Tuple[bool, List[str]]:
    """
    Ejecuta todas las validaciones previas al inicio del bot.

    Retorna:
    - (True, [])              si todo está OK
    - (False, [lista errores]) si hay problemas, con descripción clara de cada uno
    """
    errores: List[str] = (
        _validar_credenciales()
        + _validar_url(url)
        + _validar_excel(excel_path)
        + _validar_carpeta_pdfs(carpeta_pdfs)
    )
    return len(errores) == 0, errores


# =============================================================================
# VALIDACIONES INDIVIDUALES
# =============================================================================

def _validar_credenciales() -> List[str]:
    errores: List[str] = []
    if not SALESFORCE_USERNAME or SALESFORCE_USERNAME == "COMPLETAR@email.com":
        errores.append("❌ Usuario de Salesforce no configurado en el archivo .env")
    if not SALESFORCE_PASSWORD or SALESFORCE_PASSWORD == "COMPLETAR":
        errores.append("❌ Contraseña de Salesforce no configurada en el archivo .env")
    return errores


def _validar_url(url: str) -> List[str]:
    errores: List[str] = []
    if not url or not url.strip():
        errores.append("❌ La URL de Salesforce está vacía")
        return errores

    url = url.strip()

    if not re.match(r'^https?://.+\..+', url):
        errores.append(
            f"❌ La URL no tiene formato válido: '{url}'\n"
            f"   Ejemplo correcto: https://miempresa.my.salesforce.com"
        )

    if "salesforce.com" not in url.lower():
        errores.append(
            f"⚠️  La URL no parece ser de Salesforce: '{url}'\n"
            f"   ¿Estás seguro que es correcta?"
        )

    return errores


def _validar_excel(excel_path: str) -> List[str]:
    errores: List[str] = []

    if not excel_path or not excel_path.strip():
        errores.append("❌ No seleccionaste ningún archivo Excel")
        return errores

    ruta: Path = Path(excel_path)

    if not ruta.exists():
        errores.append(f"❌ El archivo Excel no existe en: {excel_path}")
        return errores

    if ruta.suffix.lower() not in (".xlsx", ".xls"):
        errores.append(
            f"❌ El archivo no es un Excel válido: {ruta.name}\n"
            f"   Debe ser .xlsx o .xls"
        )
        return errores

    # A4: Verificar que el archivo no esté bloqueado (Excel.exe abierto)
    try:
        with open(excel_path, "r+b"):
            pass  # Apertura en modo escritura exclusivo — falla si está bloqueado
    except PermissionError:
        errores.append(
            f"❌ El archivo Excel está abierto en otro programa (Excel, LibreOffice, etc.)\n"
            f"   Cerrá el archivo antes de iniciar el bot."
        )
        return errores  # No tiene sentido seguir validando
    except OSError:
        pass  # Otros errores de OS — dejar que read_excel los capture

    try:
        df: pd.DataFrame = pd.read_excel(
            excel_path, header=FILA_ENCABEZADO - 1, dtype=str, nrows=5
        )
        columnas_requeridas: List[str] = [COL_NOMBRE_OPORTUNIDAD, COL_COBRO, COL_ENVIADAS]
        faltantes: List[str] = [c for c in columnas_requeridas if c not in df.columns]
        if faltantes:
            errores.append(
                f"❌ El Excel no tiene las columnas esperadas.\n"
                f"   Faltan: {faltantes}\n"
                f"   Encontradas: {list(df.columns)}\n"
                f"   Verificá los nombres en config.py"
            )
    except Exception as e:
        errores.append(f"❌ No se pudo leer el Excel: {e}")

    return errores


def _validar_carpeta_pdfs(carpeta_path: str) -> List[str]:
    errores: List[str] = []

    if not carpeta_path or not carpeta_path.strip():
        errores.append("❌ No seleccionaste ninguna carpeta de facturas PDF")
        return errores

    carpeta: Path = Path(carpeta_path)

    if not carpeta.exists():
        errores.append(f"❌ La carpeta de facturas no existe: {carpeta_path}")
        return errores

    if not carpeta.is_dir():
        errores.append(f"❌ La ruta seleccionada no es una carpeta: {carpeta_path}")
        return errores

    pdfs: List[Path] = list(carpeta.glob("*.pdf")) + list(carpeta.glob("*.PDF"))
    if not pdfs:
        errores.append(
            f"⚠️  La carpeta no contiene archivos PDF: {carpeta_path}\n"
            f"   ¿Es la carpeta correcta?"
        )

    return errores