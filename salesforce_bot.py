# =============================================================================
# salesforce_bot.py — Automatización de Salesforce con Playwright
# =============================================================================


import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from playwright.sync_api import (
    sync_playwright, Page, Browser,
    TimeoutError as PlaywrightTimeout,
)
from config import (
    SALESFORCE_USERNAME,
    SALESFORCE_PASSWORD,
    TIMEOUT_CARGA,
    PAUSA_ENTRE_ACCIONES,
    NAVEGADOR_VISIBLE,
    RETRY_MAX_INTENTOS,
    RETRY_ESPERA_BASE,
    RETRY_ESPERA_MAX,
    CIRCUIT_BREAKER_UMBRAL,
    SELECTORES_PATH,
    TIMEOUT_NAVEGACION,
    TIMEOUT_CARGA_ARCHIVO,
    TIMEOUT_ELEMENTO,
)


# =============================================================================
# EXCEPCIÓN DE CIRCUIT BREAKER
# =============================================================================

class CircuitBreakerAbierto(Exception):
    """
    Se lanza cuando el circuit breaker detecta demasiados fallos consecutivos
    de tipo estructural (no sesión expirada).
    bot_runner la captura y detiene el procesamiento de clientes.
    """
    pass


class SesionExpiradaError(Exception):
    """
    Señaliza que Salesforce cerró la sesión.
    bot_runner la captura para intentar reconexión antes de reintentar el cliente.
    Nunca incrementa el circuit breaker — es un fallo transitorio de autenticación.
    """
    pass


class AprobacionPendienteError(Exception):
    """
    Se lanza cuando Salesforce muestra una pantalla de aprobación manual
    (el admin debe aprobar el acceso antes de que el bot pueda continuar).

    Comportamiento en bot_runner:
    - NO activa el backoff exponencial ni reintentos automáticos.
    - NO incrementa el circuit breaker.
    - bot_runner debe esperar con polling activo hasta resolución.
    - Emite evento SSE APROBACION_PENDIENTE para feedback visual en el panel.
    """
    pass


# =============================================================================
# HELPERS DE MÓDULO
# =============================================================================

def _sanitizar_error(e: Exception, max_chars: int = 200) -> str:
    """
    Trunca mensajes de excepción de Playwright para evitar que HTML de
    Salesforce (potencialmente miles de caracteres) aparezca en los logs.
    """
    msg = str(e)
    if len(msg) > max_chars:
        return msg[:max_chars] + f"… [truncado, total {len(msg)} chars]"
    return msg


# =============================================================================
# MEJORA 4 — Cache de selectores.json en memoria
# =============================================================================

# Estructura del cache: (dict_cargado, mtime_en_el_momento_de_carga)
_cache_selectores: Optional[Tuple[Dict[str, Any], float]] = None

_SELECTORES_DEFAULT: Dict[str, Any] = {
    "login": {
        "campo_usuario":  'input[name="username"], input[id="username"]',
        "campo_password": 'input[name="pw"], input[id="password"]',
        "boton_login":    'input[type="submit"]',
    },
    "busqueda": {
        "barra_global": 'input[placeholder*="Buscar en Salesforce"]',
        "barra_reset":  'input[placeholder*="Buscar"]',
    },
    "archivos_adjuntos": {
        "seccion_archivos": 'div[class*="attachments"], div[title*="Archivos"], div[title*="Files"]',
        "item_archivo":     'a[class*="file"], span[class*="file-name"]',
        "boton_subir":      'button:has-text("Upload Files"), button:has-text("Subir archivos"), input[type="file"]',
        "boton_confirmar":  'button:has-text("Done"), button:has-text("Listo"), button:has-text("Guardar")',
    },
    "facturado": {
        "casilla":       'input[type="checkbox"][name*="acturado"], input[type="checkbox"][title*="acturado"]',
        "boton_guardar": 'button:has-text("Guardar"), button:has-text("Save")',
    },
}


# Ruta del archivo de sesión persistida de Playwright.
# Guarda cookies y localStorage para reutilizar entre corridas sin re-login.
# Se invalida automáticamente si las credenciales de .env cambian.
SESSION_STATE_PATH = Path("datos") / ".sf_session.json"

# =============================================================================
# DETECCIÓN DE APROBACIÓN MANUAL — textos y selectores conocidos de SF
# =============================================================================
# Salesforce muestra distintos mensajes según idioma de la org y versión.
# Se detecta por texto en el DOM (case-insensitive) o por selectores conocidos.
# Agregar variantes si se encuentran nuevas en distintas orgs.
# =============================================================================

_TEXTOS_APROBACION = [
    # Inglés
    "waiting for approval",
    "approval required",
    "access request sent",
    "your request has been sent",
    "pending approval",
    "approval pending",
    "request access",
    "access is pending",
    # Español
    "esperando aprobación",
    "aprobación requerida",
    "solicitud de acceso enviada",
    "acceso pendiente de aprobación",
    "pendiente de aprobación",
]

_SELECTORES_APROBACION = [
    # Salesforce Identity / Access Management
    '[data-key="pendingApproval"]',
    '[class*="pendingApproval"]',
    '[class*="approval-pending"]',
    '[id*="approval"]',
    # Textos genéricos en elementos de aviso
    'p:has-text("approval")',
    'div:has-text("approval required")',
    'div:has-text("waiting for approval")',
    'span:has-text("approval")',
]


def detectar_pantalla_aprobacion(page: "Page", timeout_ms: int = 3000) -> bool:
    """
    Detecta si Salesforce muestra una pantalla de aprobación manual.

    Estrategia en dos capas:
    1. Selectores CSS conocidos para pantallas de aprobación de SF.
    2. Búsqueda de texto en el body de la página (más universal).

    Args:
        page:       Instancia activa de Playwright Page.
        timeout_ms: Tiempo máximo de espera por selector (breve — 3s por defecto).

    Returns:
        True si se detecta pantalla de aprobación, False en caso contrario.
    """
    # Capa 1: selectores estructurales de SF (rápido, específico)
    for sel in _SELECTORES_APROBACION:
        try:
            if page.locator(sel).first.is_visible(timeout=timeout_ms):
                return True
        except Exception:
            continue

    # Capa 2: búsqueda en el texto visible de la página (universal)
    try:
        contenido = page.inner_text("body").lower()
        for texto in _TEXTOS_APROBACION:
            if texto.lower() in contenido:
                return True
    except Exception:
        pass

    return False


def capturar_screenshot_diagnostico(page: "Page", prefijo: str = "login_fail") -> "str | None":
    """
    Guarda un screenshot en logs/ para diagnóstico de fallos de login.
    Retorna la ruta del archivo guardado, o None si falló.
    El nombre incluye timestamp para no sobreescribir capturas anteriores.
    """
    import time as _time
    from pathlib import Path as _Path
    try:
        carpeta_logs = _Path("logs")
        carpeta_logs.mkdir(exist_ok=True)
        ts = _time.strftime("%Y%m%d_%H%M%S")
        ruta = carpeta_logs / f"{prefijo}_{ts}.png"
        page.screenshot(path=str(ruta), full_page=False)
        return str(ruta)
    except Exception:
        return None


def cargar_selectores(ruta: str = SELECTORES_PATH) -> Dict[str, Any]:
    """
    Carga selectores desde el archivo JSON con cache invalidado por mtime.

    La primera vez (o cuando el archivo cambia) se lee del disco y se
    actualiza el cache. En llamadas posteriores sin cambio en el archivo,
    se retorna el dict en memoria sin I/O adicional.

    Si el archivo no existe o está malformado, retorna los defaults.
    """
    global _cache_selectores

    path = Path(ruta)

    # Sin archivo → defaults directamente (sin cache)
    if not path.exists():
        return _SELECTORES_DEFAULT

    try:
        mtime_actual: float = path.stat().st_mtime

        # Cache válido: mismo archivo, misma fecha de modificación
        if _cache_selectores is not None:
            datos_cache, mtime_cache = _cache_selectores
            if mtime_actual == mtime_cache:
                return datos_cache

        # Cache inválido o primera carga: leer del disco
        with path.open(encoding="utf-8") as f:
            datos = json.load(f)

        # Merge: defaults como base + datos del archivo encima
        merged: Dict[str, Any] = {}
        for seccion, vals in _SELECTORES_DEFAULT.items():
            merged[seccion] = {**vals, **datos.get(seccion, {})}

        # Actualizar cache
        _cache_selectores = (merged, mtime_actual)
        return merged

    except (json.JSONDecodeError, OSError):
        return _SELECTORES_DEFAULT


def guardar_selectores(datos: Dict[str, Any], ruta: str = SELECTORES_PATH) -> bool:
    """
    Guarda el dict de selectores en el JSON.
    Invalida el cache para que la próxima lectura tome los nuevos valores.
    Retorna True si se guardó correctamente.
    """
    global _cache_selectores

    try:
        path = Path(ruta)
        existente: Dict[str, Any] = {}
        if path.exists():
            with path.open(encoding="utf-8") as f:
                existente = json.load(f)
        for k, v in datos.items():
            existente[k] = v
        with path.open("w", encoding="utf-8") as f:
            json.dump(existente, f, ensure_ascii=False, indent=2)

        # Invalidar cache: la próxima llamada a cargar_selectores() releerá el disco
        _cache_selectores = None

        return True
    except (OSError, json.JSONDecodeError):
        return False

# =============================================================================
# NIVEL 2 — Cascada semántica SLDS para detección automática de selectores
# =============================================================================

# Cada entrada mapea "seccion.clave" → lista de selectores Playwright ordenados
# de mayor a menor especificidad semántica (atributos SLDS estables: aria-label,
# title, data-key, name, placeholder, clase SLDS conocida).
# Variantes en español e inglés incluidas para cada elemento.
ESTRATEGIAS_BUSQUEDA: dict[str, list[str]] = {
    # ── Login ────────────────────────────────────────────────────────────────
    "login.campo_usuario": [
        'input[name="username"]',
        'input[id="username"]',
        'input[aria-label="Username"]',
        'input[aria-label="Usuario"]',
        'input[placeholder*="Username"]',
        'input[placeholder*="Usuario"]',
        'input[autocomplete="username"]',
    ],
    "login.campo_password": [
        'input[name="pw"]',
        'input[id="password"]',
        'input[type="password"]',
        'input[aria-label="Password"]',
        'input[aria-label="Contraseña"]',
        'input[placeholder*="Password"]',
        'input[placeholder*="Contraseña"]',
    ],
    "login.boton_login": [
        'input[type="submit"]',
        'button[type="submit"]',
        'button[aria-label="Log In"]',
        'button[aria-label="Iniciar sesión"]',
        'input[id="Login"]',
    ],
    # ── Búsqueda global ──────────────────────────────────────────────────────
    "busqueda.barra_global": [
        'input[placeholder*="Buscar en Salesforce"]',
        'input[placeholder*="Search Salesforce"]',
        'input[aria-label="Buscar en Salesforce"]',
        'input[aria-label="Search Salesforce"]',
        'input[data-aura-class*="searchInput"]',
        'input.slds-input[class*="search"]',
        'input[title*="Search"]',
        'input[title*="Buscar"]',
    ],
    "busqueda.barra_reset": [
        'input[placeholder*="Buscar en Salesforce"]',
        'input[placeholder*="Search Salesforce"]',
        'input[aria-label*="Buscar"]',
        'input[aria-label*="Search"]',
        'input[data-aura-class*="searchInput"]',
        'input[title*="Search"]',
        'input[title*="Buscar"]',
        '[role="searchbox"]',
    ],
    # ── Archivos adjuntos ────────────────────────────────────────────────────
    "archivos_adjuntos.seccion_archivos": [
        'div[title="Files"]',
        'div[title="Archivos"]',
        'div[data-key="Files"]',
        'div[data-key="Archivos"]',
        'div[class*="attachments"]',
        'div[aria-label*="Files"]',
        'div[aria-label*="Archivos"]',
        'article[aria-label*="Files"]',
        'article[aria-label*="Archivos"]',
    ],
    "archivos_adjuntos.item_archivo": [
        'a[class*="file-name"]',
        'span[class*="file-name"]',
        'a[class*="file"]',
        'span[class*="file"]',
        'li[class*="file"]',
    ],
    "archivos_adjuntos.boton_subir": [
        'button[title="Upload Files"]',
        'button[title="Subir archivos"]',
        'button[aria-label="Upload Files"]',
        'button[aria-label="Subir archivos"]',
        'button[name="upload"]',
        'input[type="file"]',
    ],
    "archivos_adjuntos.boton_confirmar": [
        'button[title="Done"]',
        'button[title="Listo"]',
        'button[title="Guardar"]',
        'button[title="Save"]',
        'button[aria-label="Done"]',
        'button[aria-label="Listo"]',
        'button[name="SaveEdit"]',
    ],
    # ── Facturado ────────────────────────────────────────────────────────────
    "facturado.casilla": [
        'input[type="checkbox"][name*="acturado"]',
        'input[type="checkbox"][title*="acturado"]',
        'input[type="checkbox"][aria-label*="acturado"]',
        'input[type="checkbox"][aria-label*="Invoiced"]',
        'input[type="checkbox"][data-key*="acturado"]',
        'input[type="checkbox"][title*="Invoiced"]',
    ],
    "facturado.boton_guardar": [
        'button[name="SaveEdit"]',
        'button[title="Guardar"]',
        'button[title="Save"]',
        'button[aria-label="Guardar"]',
        'button[aria-label="Save"]',
    ],
}


def detectar_selector(
    page: "Page",
    clave: str,
    timeout_ms: int = TIMEOUT_ELEMENTO,
) -> "str | None":
    """
    Prueba en cascada los selectores de ESTRATEGIAS_BUSQUEDA[clave] y retorna
    el primero cuyo locator.first sea visible dentro de timeout_ms.

    Args:
        page:       Instancia activa de Playwright Page (debe estar logueada).
        clave:      Clave en formato "seccion.subclave" (ej. "login.campo_usuario").
        timeout_ms: Tiempo máximo por selector en ms (default: TIMEOUT_ELEMENTO).

    Returns:
        El selector ganador como string, o None si ninguno funcionó.
    """
    estrategias: list[str] = ESTRATEGIAS_BUSQUEDA.get(clave, [])
    if not estrategias:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "[SF] detectar_selector: '%s' no tiene estrategias definidas.", clave
        )
        return None

    for selector in estrategias:
        try:
            loc = page.locator(selector).first
            loc.wait_for(state="visible", timeout=timeout_ms)
            return selector
        except PlaywrightTimeout:
            continue
        except Exception:
            continue

    return None


# =============================================================================
# CLASE PRINCIPAL
# =============================================================================

class SalesforceBot:
    """
    Maneja toda la interacción con Salesforce.
    Se instancia una vez y se reutiliza para todos los clientes del Excel.

    Mejora 4: selectores en cache (mtime-based) — sin I/O en reconexiones.
    Mejora 5: timeouts diferenciados (TIMEOUT_NAVEGACION / CARGA_ARCHIVO / ELEMENTO).
    Retry logic + Circuit Breaker (v1.1, sin cambios).
    """

    def __init__(
        self,
        logger: Optional[logging.Logger] = None,
        salesforce_url: str = "",
    ) -> None:
        self.logger:         Optional[logging.Logger] = logger
        self.salesforce_url: str                      = salesforce_url.rstrip("/")
        self.playwright      = None
        self.browser:        Optional[Browser]         = None
        self.page:           Optional[Page]            = None

        # Mejora 4: carga con cache; si el archivo no cambió desde la
        # última instancia, no toca el disco.
        self._sel: Dict[str, Any] = cargar_selectores()

        # Integración SelectorHealer (se instancia cuando la `page` existe)
        # Type hint como string para evitar NameError (clase definida en módulo externo)
        self._healer: "Optional[Any]" = None

        # Circuit breaker
        self._fallos_consecutivos: int = 0

    # =========================================================================
    # INICIO Y CIERRE
    # =========================================================================

    def iniciar(self) -> None:
        """
        Abre el navegador e inicia sesión en Salesforce.

        A2 — Sesión persistida entre corridas:
        Si existe un archivo de sesión válido (.sf_session.json) del mismo usuario,
        lo carga en el contexto de Playwright para evitar el re-login.
        Si la sesión cargada ya no es válida (expiró), descarta el archivo y hace
        login completo. Si el login requiere aprobación manual, lanza
        AprobacionPendienteError (nunca activa retry automático).
        """
        if not self.salesforce_url:
            raise ValueError("URL de Salesforce no configurada.")

        self.playwright = sync_playwright().start()
        self.browser    = self.playwright.chromium.launch(headless=not NAVEGADOR_VISIBLE)

        # ── A2: Intentar reutilizar sesión guardada ──────────────────────────
        sesion_cargada = False
        if SESSION_STATE_PATH.exists():
            try:
                self._log("Sesión guardada encontrada — intentando reutilizar...")
                context   = self.browser.new_context(storage_state=str(SESSION_STATE_PATH))
                self.page = context.new_page()
                self._registrar_handlers_pagina(self.page)  # C3: dialogs y popups
                self.page.goto(self.salesforce_url, timeout=TIMEOUT_NAVEGACION)
                self._esperar_carga()

                if self._verificar_sesion() and not detectar_pantalla_aprobacion(self.page):
                    self._log("✅ Sesión reutilizada — sin necesidad de login.")
                    sesion_cargada = True
                else:
                    # Sesión expirada o pantalla de aprobación — descartar y re-login
                    self._log("Sesión guardada expirada — iniciando sesión de nuevo.")
                    try:
                        self.page.close()
                        context.close()
                    except Exception:
                        pass
                    SESSION_STATE_PATH.unlink(missing_ok=True)
                    sesion_cargada = False
            except Exception as e:
                self._log(f"No se pudo cargar sesión guardada ({_sanitizar_error(e)}) — login normal.")
                SESSION_STATE_PATH.unlink(missing_ok=True)
                sesion_cargada = False

        # ── Fallback: página nueva sin sesión guardada ───────────────────────
        if not sesion_cargada:
            self.page = self.browser.new_page()
            self._registrar_handlers_pagina(self.page)  # C3: dialogs y popups

        # Instanciar SelectorHealer aquí (page ya existe). Import local para evitar
        # import circular a nivel de módulo.
        try:
            from selector_healer import SelectorHealer
            self._healer = SelectorHealer(self.page, self.logger)
        except Exception:
            # Si por alguna razón falla la carga del healer, seguir sin él.
            self._healer = None

        if not sesion_cargada:
            self._log("Abriendo Salesforce...")
            self.page.goto(self.salesforce_url, timeout=TIMEOUT_NAVEGACION)
            self._esperar_carga()
            self._iniciar_sesion()

    def cerrar(self) -> None:
        """
        Cierra el navegador de forma segura.
        A2: Guarda el storage_state (cookies/localStorage) antes de cerrar
        para que la próxima corrida pueda reutilizar la sesión sin re-login.
        Solo guarda si la sesión sigue activa al momento de cerrar.
        """
        try:
            # Persistir reparaciones del SelectorHealer antes de cerrar (si existe)
            try:
                if getattr(self, "_healer", None) is not None:
                    self._healer.persistir_reparaciones()
            except Exception:
                pass

            # A2 — Guardar sesión activa para reutilizar en próxima corrida
            if self.page and self._verificar_sesion():
                try:
                    SESSION_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
                    self.page.context.storage_state(path=str(SESSION_STATE_PATH))
                    self._log("Sesión guardada para la próxima corrida (sin re-login).")
                except Exception as e:
                    self._log(f"No se pudo guardar sesión: {_sanitizar_error(e)}")
            else:
                # Si la sesión expiró o no existe, eliminar archivo viejo
                SESSION_STATE_PATH.unlink(missing_ok=True)

            if self.browser:
                self.browser.close()
            if self.playwright:
                self.playwright.stop()
        except Exception:
            pass
        self._log("Navegador cerrado.")

    @staticmethod
    def limpiar_sesion_guardada() -> None:
        """
        Elimina el archivo de sesión persistida.
        Llamar cuando el usuario cambia credenciales en el wizard para que
        la próxima corrida haga login completo con las nuevas credenciales.
        """
        SESSION_STATE_PATH.unlink(missing_ok=True)

    def _iniciar_sesion(self) -> None:
        """
        Completa el formulario de login y verifica el estado resultante.

        Estados detectados post-submit:
        - Home de SF (éxito)               → continúa normalmente
        - Pantalla de aprobación pendiente → lanza AprobacionPendienteError
        - URL sigue en /login              → credenciales incorrectas
        - Timeout / error de red           → re-lanza con mensaje claro

        La detección de aprobación se hace ANTES de asumir error de credenciales:
        evita que el loop de retry genere múltiples solicitudes al admin.
        """
        try:
            sel_login = self._sel["login"]
            self._log("Ingresando credenciales en Salesforce...")
            self.page.fill(sel_login["campo_usuario"],  SALESFORCE_USERNAME)
            self.page.fill(sel_login["campo_password"], SALESFORCE_PASSWORD)
            self._log("Enviando formulario de login...")
            self.page.click(sel_login["boton_login"])
            self._esperar_carga()

            # ── Capa 1: detectar pantalla de aprobación manual ANTES de cualquier
            #            otro check — así no se activan reintentos por error falso.
            if detectar_pantalla_aprobacion(self.page):
                screenshot = capturar_screenshot_diagnostico(self.page, "aprobacion_pendiente")
                msg = (
                    "Salesforce requiere que un administrador apruebe tu acceso. "
                    "Avisale a tu admin para que apruebe la solicitud y el bot podrá continuar."
                )
                if screenshot:
                    self._log(f"[Login] Captura de pantalla guardada: {screenshot}")
                self._log_warn(f"[Login] Aprobación manual requerida. {msg}")
                raise AprobacionPendienteError(msg)

            # ── Capa 2: URL todavía en /login → credenciales incorrectas
            if "login" in self.page.url.lower() or "secur/login" in self.page.url.lower():
                screenshot = capturar_screenshot_diagnostico(self.page, "login_fail")
                msg = (
                    "Usuario o contraseña incorrectos en Salesforce. "
                    "Verificá las credenciales en el archivo .env o usando el botón 'Credenciales'."
                )
                if screenshot:
                    self._log(f"[Login] Captura de pantalla guardada en logs/ para diagnóstico.")
                raise RuntimeError(msg)

            self._log("✅ Sesión iniciada correctamente en Salesforce.")
        except (RuntimeError, AprobacionPendienteError):
            raise
        except PlaywrightTimeout:
            raise RuntimeError(
                "No se pudo cargar Salesforce (timeout). "
                "Verificá la URL y tu conexión a internet."
            )
        except Exception as e:
            raise RuntimeError(f"Error al iniciar sesión en Salesforce: {_sanitizar_error(e)}")

    # =========================================================================
    # HELPERS INTERNOS
    # =========================================================================

    def _esperar_carga(self) -> None:
        """
        Espera a que la página cargue completamente.
        Usa TIMEOUT_NAVEGACION (configurable).
        """
        try:
            self.page.wait_for_load_state("networkidle", timeout=TIMEOUT_NAVEGACION)
        except PlaywrightTimeout:
            self._log("⚠️  Timeout esperando carga completa — continuando con carga parcial.")
            self.page.wait_for_load_state("domcontentloaded", timeout=TIMEOUT_NAVEGACION)

    def _verificar_sesion(self) -> bool:
        """
        Verifica si la sesión de Salesforce sigue activa.

        Tres capas de detección (C2):
        1. URL: redireccionó a login, logout o secur/
        2. Texto DOM: SF muestra modal de sesión expirada sin cambiar la URL
        3. Elemento de home: la barra de búsqueda de SF no está presente

        Retorna True solo si las 3 capas confirman que la sesión está activa.
        Silenciosa y rápida — usa timeouts cortos para no bloquear el scraping.
        """
        try:
            url = self.page.url.lower()

            # ── Capa 1: URL indica login o logout ───────────────────────────
            _urls_sesion_muerta = (
                "login",
                "secur/login",
                "secur/logout",
                "/apex/logout",
                "logout.jsp",
                "/logoutconfirm",
            )
            if any(p in url for p in _urls_sesion_muerta):
                self._log_warn("Sesión expirada — SF redirigió a login/logout.")
                return False

            # ── Capa 2: Modal de sesión expirada en DOM (sin redirección) ───
            # SF Lightning a veces muestra un overlay con texto de timeout
            # sin cambiar la URL. Detección por texto, timeout muy corto.
            _textos_sesion_expirada = [
                "your session has expired",
                "session has timed out",
                "tu sesión ha expirado",
                "sesión caducada",
                "session expired",
                "log in again",
                "volver a iniciar sesión",
                "inicia sesión de nuevo",
            ]
            try:
                cuerpo = self.page.inner_text("body", timeout=2000).lower()
                if any(t in cuerpo for t in _textos_sesion_expirada):
                    self._log_warn("Sesión expirada — SF muestra modal de timeout (sin redirección).")
                    return False
            except Exception:
                pass  # Fallo al leer body — no bloquear, continuar con capa 3

            # ── Capa 3: Barra de búsqueda global de SF Lightning presente ───
            # Si la sesión está activa el home de Lightning siempre tiene
            # el input de búsqueda global. Timeout muy corto: 2s.
            _sel_home = self._sel.get("busqueda", {}).get(
                "barra_global",
                'input[placeholder*="Buscar en Salesforce"], input[placeholder*="Search"]',
            )
            try:
                visible = self.page.locator(_sel_home).first.is_visible(timeout=2000)
                if not visible:
                    self._log_warn("Sesión posiblemente expirada — barra de búsqueda de SF no visible.")
                    return False
            except Exception:
                # Si no se encuentra el selector tampoco es un error fatal —
                # puede estar en una página de perfil sin la barra visible.
                # Solo reportamos, no bloqueamos.
                pass

        except Exception as e:
            # Error inesperado al verificar — asumir sesión activa para no
            # interrumpir corridas por falsos negativos.
            self._log_warn(f"Error al verificar sesión (se asume activa): {_sanitizar_error(e)}")

        return True

    def _registrar_handlers_pagina(self, page: "Page") -> None:
        """
        C3: Registra handlers de eventos de Playwright para la página activa.

        - dialog: cierra automáticamente cualquier alert/confirm/prompt que SF
          muestre durante el scraping. Sin este handler, un dialog inesperado
          (notificación de nueva versión, confirmación de salida, aviso de sesión)
          congela al bot indefinidamente hasta que vence el siguiente timeout.
          Se logea con _log_warn para que el empleado sepa que SF mostró un popup.

        - popup: cierra ventanas emergentes que SF pueda abrir (links "Abrir en nueva
          pestaña", previsualizaciones de archivos). El bot opera en una sola pestaña.

        Llamar cada vez que se crea una nueva Page.
        """
        def _on_dialog(dialog: "Dialog") -> None:
            tipo    = dialog.type      # alert | confirm | prompt | beforeunload
            mensaje = dialog.message[:120] if dialog.message else ""
            self._log_warn(
                f"Salesforce mostró un aviso inesperado ({tipo}): [{mensaje}] — "
                f"cerrado automáticamente para que el bot pueda continuar."
            )
            try:
                dialog.dismiss()
            except Exception:
                pass

        def _on_popup(popup: "Page") -> None:
            self._log_warn("Salesforce abrió una ventana emergente — cerrada automáticamente.")
            try:
                popup.close()
            except Exception:
                pass

        page.on("dialog", _on_dialog)
        page.on("popup",  _on_popup)

    def _log(self, mensaje: str) -> None:
        if self.logger:
            self.logger.info(f"[SF] {mensaje}")

    def _log_warn(self, mensaje: str) -> None:
        if self.logger:
            self.logger.warning(f"[SF] {mensaje}")

    # =========================================================================
    # CIRCUIT BREAKER
    # =========================================================================

    # Códigos de resultado que NO deben inflar el circuit breaker:
    # son fallos por datos del cliente (no hay factura, ya existe, ID inválido)
    # o errores de sesión gestionados por reconexión — no indican degradación SF.
    _ERRORES_NO_ESTRUCTURALES: frozenset = frozenset({
        "ERROR_SESION_EXPIRADA",
        "ERROR_FACTURA_NO_ENCONTRADA",
        "ERROR_MULTIPLES_FACTURAS",
        "ERROR_ARCHIVO_CORRUPTO",
        "YA_FACTURADO",
        "ERROR_ID",
    })

    def _registrar_resultado(self, exito: bool, codigo: str = "") -> None:
        """
        Actualiza el contador del circuit breaker.

        Solo incrementa ante errores estructurales de SF
        (adjunto fallido, casilla bloqueada, timeouts de infraestructura).
        Los errores no estructurales (sesión, datos del cliente) se ignoran.
        """
        if exito:
            if self._fallos_consecutivos > 0:
                self._log(
                    f"Circuit breaker: contador reseteado "
                    f"(había {self._fallos_consecutivos} fallos)."
                )
            self._fallos_consecutivos = 0
            return

        if codigo in self._ERRORES_NO_ESTRUCTURALES:
            self._log(
                f"Circuit breaker: '{codigo}' no computa como fallo estructural — "
                f"contador en {self._fallos_consecutivos}."
            )
            return

        self._fallos_consecutivos += 1
        self._log_warn(
            f"Circuit breaker: fallo estructural #{self._fallos_consecutivos} "
            f"(código: '{codigo}', umbral: {CIRCUIT_BREAKER_UMBRAL})."
        )
        if self._fallos_consecutivos >= CIRCUIT_BREAKER_UMBRAL:
            msg = (
                f"Circuit breaker ABIERTO — {self._fallos_consecutivos} fallos "
                f"estructurales consecutivos. Revisá la conexión o el estado de Salesforce."
            )
            self._log_warn(msg)
            raise CircuitBreakerAbierto(msg)

    # =========================================================================
    # RETRY LOGIC
    # =========================================================================

    def _con_reintento(self, operacion_nombre: str, func: Any, *args: Any, **kwargs: Any) -> str:
        """
        Ejecuta func con hasta RETRY_MAX_INTENTOS intentos y backoff exponencial.
        Backoff: espera = min(base * 2^(intento-1), max)

        - Si el resultado es ERROR_SESION_EXPIRADA lanza SesionExpiradaError
          inmediatamente (sin consumir reintentos): bot_runner gestiona la reconexión.
        - El código de resultado se pasa al circuit breaker para discriminar
          fallos estructurales de fallos por datos del cliente.
        """
        ultimo_resultado: str = "ERROR"

        for intento in range(1, RETRY_MAX_INTENTOS + 1):
            try:
                resultado: str = func(*args, **kwargs)
            except (CircuitBreakerAbierto, SesionExpiradaError):
                raise
            except Exception as e:
                resultado = f"ERROR_EXCEPCION: {e}"

            # Sesión expirada detectada dentro del intento → escalar de inmediato
            if resultado == "ERROR_SESION_EXPIRADA":
                raise SesionExpiradaError(
                    f"{operacion_nombre}: sesión expirada en intento {intento}."
                )

            if resultado == "OK":
                if intento > 1:
                    self._log(
                        f"{operacion_nombre}: éxito en intento {intento}/{RETRY_MAX_INTENTOS}."
                    )
                self._registrar_resultado(exito=True, codigo="OK")
                return "OK"

            ultimo_resultado = resultado
            if intento < RETRY_MAX_INTENTOS:
                espera: float = min(
                    RETRY_ESPERA_BASE * (2 ** (intento - 1)), RETRY_ESPERA_MAX
                )
                self._log_warn(
                    f"{operacion_nombre}: intento {intento}/{RETRY_MAX_INTENTOS} falló "
                    f"({resultado}). Reintentando en {espera:.0f}s..."
                )
                time.sleep(espera)
            else:
                self._log_warn(
                    f"{operacion_nombre}: agotados {RETRY_MAX_INTENTOS} intentos. "
                    f"Último resultado: {resultado}."
                )

        self._registrar_resultado(exito=False, codigo=ultimo_resultado)
        return ultimo_resultado

    # =========================================================================
    # RESET DE ESTADO
    # =========================================================================

    def reset_estado(self) -> None:
        """Vuelve al home de Salesforce antes del siguiente cliente."""
        try:
            self._log("Reset de estado...")
            self.page.keyboard.press("Escape")
            # Mejora 5: TIMEOUT_NAVEGACION para la navegación al home
            self.page.goto(self.salesforce_url, timeout=TIMEOUT_NAVEGACION)
            self._esperar_carga()

            try:
                sel_reset = self._sel["busqueda"]["barra_reset"]
                if self._healer is not None:
                    barra = self._healer.localizar("busqueda", "barra_reset", sel_reset)
                    if barra is not None:
                        barra.clear()
                else:
                    barra = self.page.locator(sel_reset).first
                    if barra.is_visible(timeout=TIMEOUT_ELEMENTO):
                        barra.clear()
            except Exception:
                pass

        except Exception as e:
            self._log_warn(f"Error en reset (se continúa de todas formas): {e}")

    # =========================================================================
    # BÚSQUEDA DE CLIENTE
    # =========================================================================

    def buscar_cliente(self, cobro: str) -> str:
        """
        Busca el número de cobro en Salesforce y entra al perfil.

        Retorna:
        - "ENCONTRADO"            si entró al perfil correcto
        - "ERROR_ID"              si no encontró resultados o hay ambigüedad
        - "ERROR_SESION_EXPIRADA" si detectó pantalla de login
        """
        if not self._verificar_sesion():
            return "ERROR_SESION_EXPIRADA"

        try:
            self._log(f"Buscando cobro: {cobro}")

            sel_barra = self._sel["busqueda"]["barra_global"]

            # Usar SelectorHealer si está disponible (reparación automática de selectores).
            # localizar() incluye el wait_for internamente en ambos paths.
            if self._healer is not None:
                barra = self._healer.localizar("busqueda", "barra_global", sel_barra)
            else:
                loc = self.page.locator(sel_barra).first
                loc.wait_for(state="visible", timeout=TIMEOUT_ELEMENTO)
                barra = loc

            if barra is None:
                self._log_warn(f"Cobro '{cobro}' no encontrado: barra de búsqueda ausente.")
                self._registrar_resultado(exito=False, codigo="ERROR_ID")
                return "ERROR_ID"

            barra.click()
            barra.fill(cobro)  # fill() limpia el campo antes de escribir (comportamiento Playwright)
            self.page.keyboard.press("Enter")

            # Mejora 5: TIMEOUT_NAVEGACION para esperar resultados de búsqueda
            self._esperar_carga()

            if not self._verificar_sesion():
                return "ERROR_SESION_EXPIRADA"

            try:
                resultado = self.page.locator(f'a[title="{cobro}"]').first
                resultado.wait_for(state="visible", timeout=TIMEOUT_ELEMENTO)
                resultado.click()
            except PlaywrightTimeout:
                try:
                    resultado = self.page.locator(f'text="{cobro}"').first
                    resultado.wait_for(state="visible", timeout=TIMEOUT_ELEMENTO)
                    resultado.click()
                except PlaywrightTimeout:
                    self._log_warn(
                        f"Cobro '{cobro}' no encontrado en Salesforce. "
                        f"Verificá que el número de cobro exista y sea exacto."
                    )
                    self._registrar_resultado(exito=False, codigo="ERROR_ID")
                    return "ERROR_ID"

            self._esperar_carga()
            self._log(f"Perfil abierto para cobro: {cobro}")
            return "ENCONTRADO"

        except CircuitBreakerAbierto:
            raise
        except Exception as e:
            self._log_warn(f"Error inesperado al buscar '{cobro}': {_sanitizar_error(e)}")
            self._registrar_resultado(exito=False, codigo="ERROR_ID")
            return "ERROR_ID"

    # =========================================================================
    # VERIFICACIÓN DE FACTURA EXISTENTE
    # =========================================================================

    def verificar_factura_existente(self) -> bool:
        """
        Verifica si el cliente ya tiene una factura adjunta.
        Retorna True si ya tiene, False si no o si no se pudo verificar.
        """
        try:
            sel_seccion = self._sel["archivos_adjuntos"]["seccion_archivos"]
            if self._healer is not None:
                seccion = self._healer.localizar(
                    "archivos_adjuntos", "seccion_archivos", sel_seccion
                )
            else:
                seccion = self.page.locator(sel_seccion).first
                seccion.wait_for(state="visible", timeout=TIMEOUT_ELEMENTO)

            if seccion is None:
                return False

            sel_items = self._sel["archivos_adjuntos"]["item_archivo"]
            archivos = self.page.locator(sel_items).all()

            if archivos:
                self._log("El cliente ya tiene factura adjunta — se omite.")
                return True
            return False

        except PlaywrightTimeout:
            return False
        except Exception as e:
            self._log_warn(
                f"No se pudo verificar factura existente: {e}. Se asume que no tiene."
            )
            return False

    # =========================================================================
    # ADJUNTAR FACTURA — con retry
    # =========================================================================

    def adjuntar_factura(self, ruta_pdf: Path) -> str:
        """
        Adjunta el PDF en el perfil del cliente.
        Reintenta automáticamente con backoff exponencial.

        Retorna: "OK" | "ERROR_ADJUNTO_FALLIDO"
        Lanza:   SesionExpiradaError si la sesión expiró (para reconexión en bot_runner)
        """
        if not self._verificar_sesion():
            raise SesionExpiradaError("adjuntar_factura: sesión expirada antes de iniciar.")

        return self._con_reintento(
            "adjuntar_factura",
            self._adjuntar_factura_intento,
            ruta_pdf,
        )

    def reconectar(self) -> bool:
        """
        Intenta reconectar la sesión de Salesforce sin reabrir el navegador.
        Navega a la URL base e inicia sesión nuevamente.

        Retorna True si la reconexión fue exitosa, False en caso contrario.
        Lanza AprobacionPendienteError si SF requiere aprobación manual mid-run.
        Llamar desde bot_runner al capturar SesionExpiradaError.
        """
        self._log("Intentando reconexión automática de sesión...")
        try:
            self.page.goto(self.salesforce_url, timeout=TIMEOUT_NAVEGACION)
            self._esperar_carga()
            if not self._verificar_sesion():
                # _iniciar_sesion lanza AprobacionPendienteError si es necesario
                self._iniciar_sesion()
            if self._verificar_sesion():
                self._log("Reconexión exitosa.")
                return True
            self._log_warn("Reconexión fallida: sigue en pantalla de login.")
            return False
        except AprobacionPendienteError:
            # Propagar hacia bot_runner — no es un error de red, es espera de admin
            raise
        except Exception as e:
            self._log_warn(f"Reconexión fallida con excepción: {e}")
            return False

# =========================================================================
    # EXPLORACIÓN AUTOMÁTICA DE SELECTORES — Nivel 3
    # =========================================================================

    def explorar_instancia(self) -> dict[str, "str | None"]:
        """
        Explora la instancia de Salesforce actualmente abierta y detecta
        automáticamente los selectores disponibles usando ESTRATEGIAS_BUSQUEDA.

        Requisito previo: self.page debe existir (bot iniciado y logueado).
        Guarda en selectores.json SOLO las claves detectadas exitosamente
        (no sobreescribe las que no se detectaron).

        Returns:
            Dict {"seccion.clave": selector_ganador | None, ...}
        """
        if self.page is None:
            raise RuntimeError(
                "explorar_instancia() requiere que el bot esté iniciado. "
                "Llamá a iniciar() antes de explorar."
            )

        resultados: dict[str, "str | None"] = {}
        encontrados: dict[str, dict[str, str]] = {}

        for clave in ESTRATEGIAS_BUSQUEDA:
            ganador = detectar_selector(self.page, clave, timeout_ms=TIMEOUT_ELEMENTO)
            resultados[clave] = ganador

            seccion, subclave = clave.split(".", 1)
            if ganador is not None:
                self._log(f"[explorar] ✅ {clave} → {ganador}")
                if seccion not in encontrados:
                    encontrados[seccion] = {}
                encontrados[seccion][subclave] = ganador
            else:
                self._log_warn(f"[explorar] ✗  {clave} — ningún selector detectado.")

        if encontrados:
            guardado = guardar_selectores(encontrados)
            if guardado:
                self._log(
                    f"[explorar] Selectores detectados guardados en selectores.json "
                    f"({sum(len(v) for v in encontrados.values())} claves)."
                )
            else:
                self._log_warn("[explorar] No se pudieron persistir los selectores detectados.")

        return resultados

    def calibrar_instancia(self, cobro_prueba: str, on_paso=None) -> dict:
        """
        Calibración guiada de selectores usando un registro real de Salesforce.
 
        A diferencia de explorar_instancia() —que solo detecta elementos
        visibles en el HOME—, este método abre el perfil de un cliente real
        y detecta los selectores contextuales que solo existen dentro de
        un registro: sección de archivos, botón de subida, casilla Facturado
        y botón Guardar.
 
        Args:
            cobro_prueba: Número de cobro de un cliente real en Salesforce.
                          Se usa para navegar al perfil correcto.
                          El registro NO se modifica — solo se inspecciona.
            on_paso: Callback opcional on_paso(n: int, estado: str) llamado
                     en cada transición de paso. Estados: 'activo', 'ok', 'error'.
 
        Returns:
            dict con claves:
                "ok"          (bool)   — True si al menos 1 selector fue detectado
                "detectados"  (int)    — cantidad de selectores encontrados
                "total"       (int)    — cantidad de selectores intentados
                "detalle"     (dict)   — {"seccion.clave": selector | None, ...}
                "error"       (str)    — mensaje de error si ok=False, else ""
 
        Comportamiento ante errores:
            - Si el cobro no se encuentra: retorna ok=False con "error".
            - Si un selector no se detecta: lo registra como None y continúa.
            - Siempre guarda en selectores.json los que sí se detectaron.
            - No modifica datos en Salesforce (no hace click en Guardar real).
        """
        def _paso(n, estado):
            if on_paso:
                try:
                    on_paso(n, estado)
                except Exception:
                    pass
        if self.page is None:
            _paso(1, 'error')
            return {
                "ok": False, "detectados": 0, "total": 0,
                "detalle": {}, "error": "Bot no iniciado. Llamá a iniciar() primero.",
            }
 
        self._log(f"[Calibrar] Iniciando calibración con cobro de prueba: '{cobro_prueba}'")
 
        detalle: dict[str, "str | None"] = {}
        encontrados: dict[str, dict[str, str]] = {}
 
        # ── PASO 1: Detectar selectores del HOME (mismos que explorar_instancia) ──
        _paso(1, 'activo')
        self._log("[Calibrar] Paso 1/3 — Detectando selectores del HOME...")
        for clave in ESTRATEGIAS_BUSQUEDA:
            seccion, subclave = clave.split(".", 1)
            # Los selectores de archivos_adjuntos y facturado requieren contexto real.
            # Los de login y busqueda se detectan aquí en el HOME.
            if seccion in ("archivos_adjuntos", "facturado"):
                continue
            ganador = detectar_selector(self.page, clave, timeout_ms=TIMEOUT_ELEMENTO)
            detalle[clave] = ganador
            if ganador is not None:
                self._log(f"[Calibrar] ✅ {clave} → {ganador}")
                if seccion not in encontrados:
                    encontrados[seccion] = {}
                encontrados[seccion][subclave] = ganador
            else:
                self._log_warn(f"[Calibrar] ✗  {clave} — no detectado en HOME.")
 
        # ── PASO 2: Navegar al perfil del cobro de prueba ──────────────────────
        _paso(1, 'ok')
        _paso(2, 'activo')
        self._log(f"[Calibrar] Paso 2/3 — Navegando al perfil '{cobro_prueba}'...")
        resultado_busqueda = self.buscar_cliente(cobro_prueba)
 
        if resultado_busqueda != "ENCONTRADO":
            msg = (
                f"No se encontró el cobro '{cobro_prueba}' en Salesforce "
                f"(resultado: {resultado_busqueda}). "
                f"Verificá que el número exista y sea exacto."
            )
            self._log_warn(f"[Calibrar] ✗ {msg}")
            _paso(2, 'error')
            # Guardar lo que se detectó en el HOME antes de retornar
            if encontrados:
                guardar_selectores(encontrados)
            return {
                "ok": False,
                "detectados": sum(1 for v in detalle.values() if v is not None),
                "total": len(ESTRATEGIAS_BUSQUEDA),
                "detalle": detalle,
                "error": msg,
            }
 
        self._log(f"[Calibrar] ✅ Perfil abierto. Detectando selectores contextuales...")
        _paso(2, 'ok')
 
        # ── PASO 3: Detectar selectores contextuales dentro del perfil ─────────
        _paso(3, 'activo')
        self._log("[Calibrar] Paso 3/3 — Detectando selectores en perfil del cliente...")
 
        claves_contextuales = [
            clave for clave in ESTRATEGIAS_BUSQUEDA
            if clave.split(".", 1)[0] in ("archivos_adjuntos", "facturado")
        ]
 
        for clave in claves_contextuales:
            seccion, subclave = clave.split(".", 1)
 
            # Para "boton_subir": hacer click en la sección archivos primero
            # si ya detectamos dónde está, para que el botón aparezca.
            if subclave == "boton_subir":
                sel_seccion = (encontrados.get("archivos_adjuntos") or {}).get("seccion_archivos")
                if sel_seccion:
                    try:
                        self.page.locator(sel_seccion).first.click(timeout=TIMEOUT_ELEMENTO)
                        self._esperar_carga()
                    except Exception:
                        pass  # Si no se puede hacer click, intentar detectar de todas formas
 
            ganador = detectar_selector(self.page, clave, timeout_ms=TIMEOUT_ELEMENTO)
            detalle[clave] = ganador
 
            if ganador is not None:
                self._log(f"[Calibrar] ✅ {clave} → {ganador}")
                if seccion not in encontrados:
                    encontrados[seccion] = {}
                encontrados[seccion][subclave] = ganador
            else:
                self._log_warn(f"[Calibrar] ✗  {clave} — no detectado en perfil.")
 
        # ── Volver al HOME para dejar el bot en estado limpio ──────────────────
        try:
            self.page.keyboard.press("Escape")
            self.page.goto(self.salesforce_url, timeout=TIMEOUT_NAVEGACION)
            self._esperar_carga()
        except Exception:
            pass
 
        # ── Persistir todo lo detectado ────────────────────────────────────────
        n_detectados = sum(1 for v in detalle.values() if v is not None)
        n_total = len(ESTRATEGIAS_BUSQUEDA)
        _paso(3, 'ok' if n_detectados > 0 else 'error')
        _paso(4, 'activo')
 
        if encontrados:
            guardado = guardar_selectores(encontrados)
            if guardado:
                self._log(
                    f"[Calibrar] ✅ Calibración completada: {n_detectados}/{n_total} "
                    f"selectores detectados y guardados en selectores.json."
                )
            else:
                self._log_warn("[Calibrar] ✗  No se pudo persistir selectores.json.")
        else:
            self._log_warn("[Calibrar] ✗  No se detectó ningún selector. Revisá la instancia.")

        _paso(4, 'ok' if n_detectados > 0 else 'error')
        _paso(5, 'ok' if n_detectados > 0 else 'error')
 
        return {
            "ok": n_detectados > 0,
            "detectados": n_detectados,
            "total": n_total,
            "detalle": detalle,
            "error": "" if n_detectados > 0 else "No se detectó ningún selector.",
        }

    def _adjuntar_factura_intento(self, ruta_pdf: Path) -> str:
        """Un único intento de adjuntar la factura."""
        try:
            self._log(f"Adjuntando: {ruta_pdf.name}")

            sel_subir = self._sel["archivos_adjuntos"]["boton_subir"]
            if self._healer is not None:
                boton = self._healer.localizar("archivos_adjuntos", "boton_subir", sel_subir)
            else:
                boton = self.page.locator(sel_subir).first
                boton.wait_for(state="visible", timeout=TIMEOUT_ELEMENTO)

            if boton is None:
                self._log_warn(f"No se encontró el botón de subida para '{ruta_pdf.name}'.")
                return "ERROR_ADJUNTO_FALLIDO"

            if boton.get_attribute("type") == "file":
                boton.set_input_files(str(ruta_pdf))
            else:
                boton.click()
                self.page.locator('input[type="file"]').first.set_input_files(str(ruta_pdf))

            # TIMEOUT_CARGA_ARCHIVO para esperar que el PDF se suba
            self.page.wait_for_load_state("networkidle", timeout=TIMEOUT_CARGA_ARCHIVO)

            try:
                sel_confirmar = self._sel["archivos_adjuntos"]["boton_confirmar"]
                if self._healer is not None:
                    btn_confirmar = self._healer.localizar(
                        "archivos_adjuntos", "boton_confirmar", sel_confirmar
                    )
                    if btn_confirmar is not None:
                        btn_confirmar.click()
                        self._esperar_carga()
                else:
                    btn_confirmar = self.page.locator(sel_confirmar).first
                    if btn_confirmar.is_visible(timeout=TIMEOUT_ELEMENTO):
                        btn_confirmar.click()
                        self._esperar_carga()
            except PlaywrightTimeout:
                pass

            if self._verificar_adjunto_guardado(ruta_pdf.name):
                self._log(f"Adjunto verificado OK: {ruta_pdf.name}")
                return "OK"
            else:
                self._log_warn(
                    f"El archivo '{ruta_pdf.name}' no aparece en Salesforce. "
                    f"Puede ser un problema de selector o carga lenta."
                )
                return "ERROR_ADJUNTO_FALLIDO"

        except Exception as e:
            self._log_warn(f"Error al adjuntar '{ruta_pdf.name}': {_sanitizar_error(e)}")
            return "ERROR_ADJUNTO_FALLIDO"

    def _verificar_adjunto_guardado(self, nombre_archivo: str) -> bool:
        """Verifica que el archivo aparezca en Salesforce tras subirlo."""
        try:
            self.page.locator(f'text="{nombre_archivo}"').first.wait_for(
                state="visible", timeout=TIMEOUT_ELEMENTO
            )
            return True
        except PlaywrightTimeout:
            return False

    # =========================================================================
    # MARCAR COMO FACTURADO — con retry
    # =========================================================================

    def marcar_facturado(self) -> str:
        """
        Tilda la casilla de Facturado en el perfil del cliente.
        Reintenta automáticamente con backoff exponencial.

        Comportamiento actual (v1.3): solo marca el checkbox "Facturado".
        No escribe número de factura — pendiente de decisión del cliente
        (ver T-09 en PLAN_MAESTRO). Implementar cuando se confirme el campo
        destino en la instancia real de Salesforce.

        Retorna: "OK" | "ERROR_CASILLA_BLOQUEADA"
        Lanza:   SesionExpiradaError si la sesión expiró
        """
        if not self._verificar_sesion():
            raise SesionExpiradaError("marcar_facturado: sesión expirada antes de iniciar.")

        return self._con_reintento(
            "marcar_facturado",
            self._marcar_facturado_intento,
        )

    def _marcar_facturado_intento(self) -> str:
        """Un único intento de marcar la casilla Facturado."""
        try:
            self._log("Marcando casilla Facturado...")

            sel_casilla = self._sel["facturado"]["casilla"]
            if self._healer is not None:
                casilla = self._healer.localizar("facturado", "casilla", sel_casilla)
            else:
                casilla = self.page.locator(sel_casilla).first
                casilla.wait_for(state="visible", timeout=TIMEOUT_ELEMENTO)

            if casilla is None:
                self._log_warn(
                    "No se encontró la casilla Facturado. "
                    "Verificá el selector con F12 en tu instancia."
                )
                return "ERROR_CASILLA_BLOQUEADA"

            if not casilla.is_enabled():
                self._log_warn(
                    "La casilla Facturado está visible pero no editable. "
                    "Puede haber un campo requerido sin completar en el perfil."
                )
                return "ERROR_CASILLA_BLOQUEADA"

            if not casilla.is_checked():
                casilla.check()
                casilla.wait_for(state="visible", timeout=TIMEOUT_ELEMENTO)

            try:
                sel_guardar = self._sel["facturado"]["boton_guardar"]
                if self._healer is not None:
                    btn_guardar = self._healer.localizar("facturado", "boton_guardar", sel_guardar)
                    if btn_guardar is not None:
                        btn_guardar.click()
                        self._esperar_carga()
                else:
                    btn_guardar = self.page.locator(sel_guardar).first
                    if btn_guardar.is_visible(timeout=TIMEOUT_ELEMENTO):
                        btn_guardar.click()
                        self._esperar_carga()
            except PlaywrightTimeout:
                pass

            if casilla.is_checked():
                self._log("Casilla Facturado marcada y guardada correctamente.")
                return "OK"
            else:
                self._log_warn(
                    "La casilla no quedó marcada después de guardar. "
                    "Puede ser un problema de permisos o de selector."
                )
                return "ERROR_CASILLA_BLOQUEADA"

        except PlaywrightTimeout:
            self._log_warn(
                "No se encontró la casilla Facturado. "
                "Verificá el selector con F12 en tu instancia."
            )
            return "ERROR_CASILLA_BLOQUEADA"
        except Exception as e:
            self._log_warn(f"Error inesperado al marcar Facturado: {_sanitizar_error(e)}")
            return "ERROR_CASILLA_BLOQUEADA"