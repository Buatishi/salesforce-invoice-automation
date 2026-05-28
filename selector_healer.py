# =============================================================================
# selector_healer.py — Auto-reparación de selectores CSS por heurísticas semánticas
# =============================================================================

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from playwright.sync_api import Page, Locator, TimeoutError as PlaywrightTimeout

from config import TIMEOUT_ELEMENTO, SELECTORES_PATH
from salesforce_bot import cargar_selectores, guardar_selectores


# =============================================================================
# HEURÍSTICAS POR ELEMENTO
# Cada entrada define una lista ordenada de selectores candidatos semánticos.
# Se prueban en orden; el primero que encuentre el elemento gana.
# Separados de selectores.json porque son lógica interna, no configuración.
# =============================================================================

@dataclass
class _HeuristicaElemento:
    descripcion: str
    candidatos:  list[str] = field(default_factory=list)


_HEURISTICAS: dict[str, dict[str, _HeuristicaElemento]] = {
    "busqueda": {
        "barra_global": _HeuristicaElemento(
            descripcion="Barra de búsqueda global de Salesforce",
            candidatos=[
                # Atributo title estable en Lightning
                'input[title="Buscar en Salesforce"]',
                'input[title="Search Salesforce"]',
                # Rol ARIA + label
                '[role="searchbox"]',
                'input[aria-label*="Buscar"]',
                'input[aria-label*="Search"]',
                # Placeholder (menos estable pero como último recurso)
                'input[placeholder*="Buscar en Salesforce"]',
                'input[placeholder*="Search Salesforce"]',
            ],
        ),
        "barra_reset": _HeuristicaElemento(
            descripcion="Barra de búsqueda para limpiar estado",
            candidatos=[
                'input[title*="Buscar"]',
                'input[aria-label*="Buscar"]',
                '[role="searchbox"]',
                'input[placeholder*="Buscar"]',
            ],
        ),
    },
    "archivos_adjuntos": {
        "seccion_archivos": _HeuristicaElemento(
            descripcion="Sección de archivos adjuntos en el perfil",
            candidatos=[
                # data-component-id es más estable que clases dinámicas
                '[data-component-id*="file"]',
                '[aria-label*="Files"]',
                '[aria-label*="Archivos"]',
                'div[title="Files"]',
                'div[title="Archivos"]',
                # Encabezado de sección por texto
                'article:has(> header span:text-matches("Files|Archivos", "i"))',
            ],
        ),
        "boton_subir": _HeuristicaElemento(
            descripcion="Botón para subir archivos",
            candidatos=[
                # Texto visible — muy estable en Salesforce
                'button:has-text("Upload Files")',
                'button:has-text("Subir archivos")',
                'button:has-text("Subir")',
                # Input file directo
                'input[type="file"]',
                # Aria
                '[aria-label*="Upload"]',
                '[aria-label*="Subir"]',
            ],
        ),
        "boton_confirmar": _HeuristicaElemento(
            descripcion="Botón de confirmación post-upload",
            candidatos=[
                'button:has-text("Done")',
                'button:has-text("Listo")',
                'button:has-text("Guardar")',
                'button[aria-label="Done"]',
                '[role="dialog"] button:last-child',  # último botón en modal
            ],
        ),
        "item_archivo": _HeuristicaElemento(
            descripcion="Item de archivo adjunto existente",
            candidatos=[
                'a[href*="/sfc/servlet"]',  # URL de descarga SF estable
                '[data-component-id*="file-card"]',
                'span[class*="file-name"]',
                'a[class*="file"]',
            ],
        ),
    },
    "facturado": {
        "casilla": _HeuristicaElemento(
            descripcion="Casilla de verificación Facturado",
            candidatos=[
                # Atributos semánticos por nombre de campo SF
                'input[type="checkbox"][name*="acturado"]',
                'input[type="checkbox"][aria-label*="acturado"]',
                'input[type="checkbox"][title*="acturado"]',
                # Estructura: label con texto + checkbox adyacente
                'label:has-text("Facturado") + input[type="checkbox"]',
                'label:has-text("Facturado") ~ input[type="checkbox"]',
                # Alternativa inglés
                'input[type="checkbox"][name*="nvoiced"]',
                'input[type="checkbox"][aria-label*="nvoiced"]',
            ],
        ),
        "boton_guardar": _HeuristicaElemento(
            descripcion="Botón guardar en modo edición",
            candidatos=[
                'button[name="SaveEdit"]',          # name estable en SF
                'button:has-text("Guardar")',
                'button:has-text("Save")',
                '[aria-label="Guardar"]',
                '[aria-label="Save"]',
            ],
        ),
    },
    "login": {
        "campo_usuario": _HeuristicaElemento(
            descripcion="Campo de usuario en login",
            candidatos=[
                'input[name="username"]',
                'input[id="username"]',
                'input[autocomplete="username"]',
                'input[type="email"]',
            ],
        ),
        "campo_password": _HeuristicaElemento(
            descripcion="Campo de contraseña en login",
            candidatos=[
                'input[name="pw"]',
                'input[id="password"]',
                'input[type="password"]',
                'input[autocomplete="current-password"]',
            ],
        ),
        "boton_login": _HeuristicaElemento(
            descripcion="Botón de submit en login",
            candidatos=[
                'input[type="submit"]',
                'button[type="submit"]',
                'input[id="Login"]',
            ],
        ),
    },
}


# =============================================================================
# CLASE PRINCIPAL
# =============================================================================

class SelectorHealer:
    """
    Capa de auto-reparación sobre selectores.json.

    Uso en salesforce_bot.py:
        healer = SelectorHealer(self.page, self.logger)

        # Reemplaza: self.page.locator(self._sel["busqueda"]["barra_global"]).first
        elemento = healer.localizar("busqueda", "barra_global",
                                    self._sel["busqueda"]["barra_global"])

    Si el selector original falla, prueba heurísticas semánticas.
    Si una heurística tiene éxito, persiste el selector ganador en selectores.json.
    Si todo falla, retorna None y registra screenshot de diagnóstico.
    """

    def __init__(
        self,
        page:    Page,
        logger:  Optional[logging.Logger] = None,
        ruta_selectores: str = SELECTORES_PATH,
    ) -> None:
        self._page:   Page                       = page
        self._logger: Optional[logging.Logger]   = logger
        self._ruta:   str                        = ruta_selectores
        # Acumula reparaciones de la sesión para un único flush al final
        self._reparaciones_pendientes: dict[str, dict[str, str]] = {}

    # ── API pública ──────────────────────────────────────────────────────────

    def localizar(
        self,
        seccion:           str,
        clave:             str,
        selector_actual:   str,
        timeout:           int = TIMEOUT_ELEMENTO,
    ) -> Optional[Locator]:
        """
        Localiza el elemento usando selector_actual primero.
        Si falla, activa heurísticas semánticas.

        Retorna el Locator listo para usar, o None si no se encontró.
        """
        # Intento 1: selector guardado (comportamiento normal, sin overhead)
        locator = self._intentar_selector(selector_actual, timeout)
        if locator is not None:
            return locator

        self._log_warn(
            f"[Healer] Selector fallido para [{seccion}][{clave}]: "
            f"'{selector_actual}'. Activando heurísticas..."
        )

        # Intento 2: heurísticas semánticas
        locator = self._aplicar_heuristicas(seccion, clave, timeout)
        if locator is not None:
            return locator

        # Sin solución — captura de pantalla para diagnóstico
        self._capturar_screenshot_diagnostico(seccion, clave)
        self._log_warn(
            f"[Healer] No se encontró '{clave}' en sección '{seccion}'. "
            f"Screenshot guardado en logs/. Revisá el panel de Selectores SF."
        )
        return None

    def persistir_reparaciones(self) -> None:
        """
        Guarda en selectores.json todas las reparaciones acumuladas durante la sesión.
        Llamar al final de la corrida (o tras cada cliente si se prefiere).
        Invalida el cache automáticamente via guardar_selectores().
        """
        if not self._reparaciones_pendientes:
            return

        self._log(
            f"[Healer] Persistiendo {sum(len(v) for v in self._reparaciones_pendientes.values())} "
            f"selector(es) reparado(s) en selectores.json."
        )
        selectores_actuales = cargar_selectores(self._ruta)
        for seccion, claves in self._reparaciones_pendientes.items():
            if seccion not in selectores_actuales:
                selectores_actuales[seccion] = {}
            selectores_actuales[seccion].update(claves)

        guardar_selectores(selectores_actuales, self._ruta)
        self._reparaciones_pendientes.clear()

    # ── Internos ─────────────────────────────────────────────────────────────

    def _intentar_selector(self, selector: str, timeout: int) -> Optional[Locator]:
        """Retorna el Locator si es visible en timeout, None si no."""
        try:
            loc = self._page.locator(selector).first
            loc.wait_for(state="visible", timeout=timeout)
            return loc
        except (PlaywrightTimeout, Exception):
            return None

    def _aplicar_heuristicas(
        self, seccion: str, clave: str, timeout: int
    ) -> Optional[Locator]:
        """Prueba cada candidato semántico en orden; persiste el ganador."""
        heuristica = _HEURISTICAS.get(seccion, {}).get(clave)
        if heuristica is None:
            self._log_warn(
                f"[Healer] Sin heurísticas definidas para [{seccion}][{clave}]."
            )
            return None

        for candidato in heuristica.candidatos:
            locator = self._intentar_selector(candidato, timeout // 2)
            if locator is not None:
                self._log(
                    f"[Healer] Reparación exitosa [{seccion}][{clave}]: "
                    f"nuevo selector → '{candidato}'"
                )
                # Acumular para persistencia diferida
                if seccion not in self._reparaciones_pendientes:
                    self._reparaciones_pendientes[seccion] = {}
                self._reparaciones_pendientes[seccion][clave] = candidato
                return locator

        return None

    def _capturar_screenshot_diagnostico(self, seccion: str, clave: str) -> None:
        """Guarda screenshot en logs/ para facilitar diagnóstico manual."""
        try:
            ruta = Path("logs") / f"healer_fallo_{seccion}_{clave}.png"
            ruta.parent.mkdir(exist_ok=True)
            self._page.screenshot(path=str(ruta), full_page=True)
        except Exception:
            pass  # No interrumpir el flujo por fallo de diagnóstico

    def _log(self, mensaje: str) -> None:
        if self._logger:
            self._logger.info(mensaje)

    def _log_warn(self, mensaje: str) -> None:
        if self._logger:
            self._logger.warning(mensaje)