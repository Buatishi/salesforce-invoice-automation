# =============================================================================
# file_matcher.py — Búsqueda y matching de facturas PDF en carpeta local
# =============================================================================

import logging
import re
import unicodedata
from pathlib import Path
from difflib import SequenceMatcher
from typing import Optional, List, Set, Tuple
from excel_handler import normalizar_texto
from config import UMBRAL_SIMILITUD, MAX_PDF_MB

# Límite de tamaño en bytes (calculado una vez al importar el módulo)
_MAX_PDF_BYTES: int = MAX_PDF_MB * 1024 * 1024


# =============================================================================
# PALABRAS A IGNORAR EN EL MATCHING (productos, artículos, sufijos numéricos)
# =============================================================================

_PALABRAS_IGNORAR: Set[str] = {
    "anillo", "alianzas", "alianza", "diamante", "cadena",
    "colgante", "pulsera", "aros", "aro", "pendiente", "pendientes",
    "collar", "tobillera", "gemelos",
}


# =============================================================================
# HELPERS
# =============================================================================

def _similitud(texto_a: str, texto_b: str) -> float:
    """Calcula similitud entre dos textos con SequenceMatcher. Retorna 0-100."""
    return SequenceMatcher(None, texto_a, texto_b).ratio() * 100


def _tokens_excel(nombre_oportunidad: str) -> Set[str]:
    """
    Extrae tokens significativos del nombre que viene del Excel.

    Ejemplo:
      "Sergio Macedo Ruiz - Alianzas"  →  {'sergio', 'macedo', 'ruiz'}
      "Micaela Garcia - Anillo 4"      →  {'micaela', 'garcia'}
    """
    norm: str = normalizar_texto(nombre_oportunidad)

    # Descartar todo lo que viene después del " - " (nombre del producto)
    if " - " in norm:
        norm = norm.split(" - ")[0].strip()

    tokens: Set[str] = {
        t for t in norm.split()
        if t not in _PALABRAS_IGNORAR and not t.isdigit() and len(t) > 1
    }
    return tokens


def _tokens_pdf(nombre_stem: str) -> Set[str]:
    """
    Extrae tokens significativos del stem del PDF.

    Los PDFs tienen un prefijo numérico largo antes del nombre:
      "30718891724_006_00001_00000508 MACEDO RUIZ SERGIO ALEJANDRO"
      →  {'macedo', 'ruiz', 'sergio', 'alejandro'}

    Elimina el prefijo numérico (dígitos, guiones bajos y espacios iniciales)
    antes de tokenizar.
    """
    norm: str = normalizar_texto(nombre_stem)

    # Quitar prefijo numérico: secuencia de dígitos, guiones y espacios al inicio
    norm = re.sub(r'^[\d\s_\-]+', '', norm).strip()

    tokens: Set[str] = {
        t for t in norm.split()
        if not t.isdigit() and len(t) > 1
    }
    return tokens


def _score_token(nombre_oportunidad: str, nombre_stem_pdf: str) -> float:
    """
    Calcula similitud basada en intersección de tokens de nombre.

    Insensible al orden de palabras (Excel: "Nombre Apellido",
    PDF: "APELLIDO NOMBRE SEGUNDO") y al prefijo numérico del PDF.

    Estrategia:
    - Si todos los tokens del Excel están en el PDF (nombre corto en Excel,
      nombre completo en PDF) → score = comunes / min → 100 %
    - En cualquier otro caso → score = comunes / max  (Jaccard estricto,
      evita falsos positivos cuando solo 1 token coincide por casualidad)

    Retorna 0-100.
    """
    te: Set[str] = _tokens_excel(nombre_oportunidad)
    tp: Set[str] = _tokens_pdf(nombre_stem_pdf)

    if not te or not tp:
        return 0.0

    comunes: Set[str] = te & tp

    if comunes == te:
        # Todos los tokens del Excel están presentes en el PDF
        return len(comunes) / min(len(te), len(tp)) * 100
    else:
        return len(comunes) / max(len(te), len(tp)) * 100


def _score_combinado(nombre_oportunidad: str, pdf: Path) -> float:
    """
    Score final = max(score_token, score_sequence_matcher_base).

    - score_token: maneja inversión de orden y prefijo numérico (nuevo).
    - score_sequence: fallback para PDFs sin prefijo numérico que sí matchean bien
      con el algoritmo original.
    """
    nombre_norm: str = normalizar_texto(nombre_oportunidad)
    nombre_base: str = nombre_norm.split(" - ")[0].strip() if " - " in nombre_norm else nombre_norm

    nombre_pdf_norm: str = normalizar_texto(pdf.stem)
    nombre_pdf_base: str = nombre_pdf_norm.split(" - ")[0].strip() if " - " in nombre_pdf_norm else nombre_pdf_norm

    score_seq_completo: float = _similitud(nombre_norm, nombre_pdf_norm)
    score_seq_base:     float = _similitud(nombre_base, nombre_pdf_base)
    score_tok:          float = _score_token(nombre_oportunidad, pdf.stem)

    return max(score_seq_completo, score_seq_base, score_tok)


def _listar_pdfs(carpeta: str) -> List[Path]:
    """
    Lista todos los archivos PDF en la carpeta indicada.
    Acepta extensiones .pdf y .PDF (case-insensitive en Windows).
    """
    ruta: Path = Path(carpeta)

    if not ruta.exists():
        raise FileNotFoundError(f"La carpeta de facturas no existe: {carpeta}")

    if not ruta.is_dir():
        raise NotADirectoryError(f"La ruta no es una carpeta: {carpeta}")

    pdfs: List[Path] = list(ruta.glob("*.pdf")) + list(ruta.glob("*.PDF"))
    pdfs = list({p.name.lower(): p for p in pdfs}.values())
    return pdfs


# =============================================================================
# BÚSQUEDA PRINCIPAL
# =============================================================================

def buscar_factura(
    nombre_oportunidad: str,
    logger: Optional[logging.Logger] = None,
    carpeta: str = "",
    umbral: Optional[int] = None,
) -> Tuple[Optional[Path], str]:
    """
    Busca el PDF que mejor coincida con el nombre de la oportunidad.

    Estrategia de matching (de mayor a menor prioridad):
    1. Score por tokens (insensible al orden y al prefijo numérico del PDF)
    2. Score por SequenceMatcher sobre el nombre base (fallback para PDFs sin prefijo)
    3. Score por SequenceMatcher sobre el nombre completo (fallback general)

    Parámetros:
    - nombre_oportunidad : nombre del cliente desde el Excel
    - logger             : logger del bot (opcional)
    - carpeta            : ruta a la carpeta de PDFs (elegida desde la GUI)
    - umbral             : umbral de similitud 0-100 (si None usa UMBRAL_SIMILITUD del config)

    Retorna:
    - (Path, "OK")                         si encontró una única coincidencia válida
    - (None, "ERROR_FACTURA_NO_ENCONTRADA") si no encontró ningún PDF similar
    - (None, "ERROR_MULTIPLES_FACTURAS")    si hay empate entre dos o más PDFs
    - (None, "ERROR_ARCHIVO_CORRUPTO")      si el archivo pesa 0 bytes
    """

    umbral_efectivo: int = umbral if umbral is not None else UMBRAL_SIMILITUD

    if not carpeta:
        if logger:
            logger.warning(f"No se especificó carpeta de facturas para '{nombre_oportunidad}'.")
        return None, "ERROR_FACTURA_NO_ENCONTRADA"

    nombre_normalizado: str = normalizar_texto(nombre_oportunidad)
    nombre_base: str = nombre_normalizado.split(" - ")[0].strip() if " - " in nombre_normalizado else nombre_normalizado

    try:
        pdfs: List[Path] = _listar_pdfs(carpeta)
    except (FileNotFoundError, NotADirectoryError) as e:
        if logger:
            logger.warning(str(e))
        return None, "ERROR_FACTURA_NO_ENCONTRADA"

    if not pdfs:
        if logger:
            logger.warning(f"La carpeta de facturas está vacía: {carpeta}")
        return None, "ERROR_FACTURA_NO_ENCONTRADA"

    # ── Calcular score combinado para TODOS los PDFs
    todos: List[Tuple[float, Path]] = []

    for pdf in pdfs:
        score_final: float = _score_combinado(nombre_oportunidad, pdf)
        todos.append((score_final, pdf))

    todos.sort(key=lambda x: x[0], reverse=True)

    # PDFs que superan el umbral
    candidatos: List[Tuple[float, Path]] = [(s, p) for s, p in todos if s >= umbral_efectivo]

    # ── Sin ningún candidato
    if not candidatos:
        if logger:
            mas_cercanos: List[Tuple[float, Path]] = todos[:3]
            logger.warning(f"No se encontró factura para '{nombre_oportunidad}' (umbral: {umbral_efectivo}%)")
            logger.warning("─" * 56)
            logger.warning(f"  DETALLE MATCHING FALLIDO")
            logger.warning(f"  Cliente en Excel   : '{nombre_oportunidad}'")
            logger.warning(f"  Normalizado        : '{nombre_normalizado}'")
            logger.warning(f"  Base (sin producto): '{nombre_base}'")
            logger.warning(f"  Tokens nombre      : {_tokens_excel(nombre_oportunidad)}")
            logger.warning(f"  Motivo del error   : Ningún PDF superó el umbral de {umbral_efectivo}%")
            logger.warning(f"  PDFs más cercanos (no alcanzaron el umbral):")
            for score, pdf in mas_cercanos:
                logger.warning(f"    {score:5.1f}%  →  {pdf.name}")
            logger.warning(f"  → Solución: bajá el umbral en el panel (sección Ajustes avanzados)")
            logger.warning("─" * 56)
        return None, "ERROR_FACTURA_NO_ENCONTRADA"

    # ── Empate entre los dos primeros (diferencia menor a 5 puntos)
    if len(candidatos) > 1 and (candidatos[0][0] - candidatos[1][0]) < 5:
        if logger:
            logger.warning(f"Múltiples facturas similares para '{nombre_oportunidad}'")
            logger.warning("─" * 56)
            logger.warning(f"  DETALLE MATCHING FALLIDO")
            logger.warning(f"  Cliente en Excel   : '{nombre_oportunidad}'")
            logger.warning(f"  Normalizado        : '{nombre_normalizado}'")
            logger.warning(f"  Base (sin producto): '{nombre_base}'")
            logger.warning(f"  Motivo del error   : Empate — diferencia menor a 5% entre candidatos")
            logger.warning(f"  PDFs empatados:")
            for score, pdf in candidatos[:3]:
                logger.warning(f"    {score:5.1f}%  →  {pdf.name}")
            logger.warning(f"  → Solución: renombrá uno de los PDFs para diferenciarlo mejor")
            logger.warning("─" * 56)
        return None, "ERROR_MULTIPLES_FACTURAS"

    # ── Candidato único ganador
    _, archivo = candidatos[0]

    # Archivo corrupto (0 bytes)
    if archivo.stat().st_size == 0:
        if logger:
            logger.warning(f"Archivo corrupto (0 bytes): '{archivo.name}'")
            logger.warning("─" * 56)
            logger.warning(f"  DETALLE MATCHING FALLIDO")
            logger.warning(f"  Cliente en Excel   : '{nombre_oportunidad}'")
            logger.warning(f"  PDF encontrado     : '{archivo.name}'")
            logger.warning(f"  Similitud          : {candidatos[0][0]:.1f}%")
            logger.warning(f"  Motivo del error   : El archivo existe pero pesa 0 bytes (corrupto)")
            logger.warning(f"  → Solución: reemplazá el PDF en la carpeta de facturas")
            logger.warning("─" * 56)
        return None, "ERROR_ARCHIVO_CORRUPTO"

    # Archivo demasiado grande — WARNING no-bloqueante (continúa con la subida)
    tamano_bytes: int = archivo.stat().st_size
    if tamano_bytes > _MAX_PDF_BYTES:
        if logger:
            logger.warning(
                f"⚠️  PDF grande ({tamano_bytes / 1024 / 1024:.1f} MB > {MAX_PDF_MB} MB): "
                f"'{archivo.name}'. Puede causar timeout en la subida a Salesforce."
            )

    # ── Todo OK — log limpio de una línea
    if logger:
        logger.info(
            f"Factura encontrada: '{archivo.name}' "
            f"para '{nombre_oportunidad}' "
            f"(similitud: {candidatos[0][0]:.1f}%)"
        )

    return archivo, "OK"