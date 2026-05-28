# =============================================================================
# config.py — Configuración central del bot (Pydantic BaseSettings)
# =============================================================================

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Configuración global del bot.
    Pydantic lee automáticamente desde el archivo .env y variables de entorno.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Credenciales Salesforce ──────────────────────────────────────────────
    salesforce_username: str = Field(default="", alias="SALESFORCE_USERNAME")
    salesforce_password: str = Field(default="", alias="SALESFORCE_PASSWORD")

    # ── Columnas del Excel ───────────────────────────────────────────────────
    col_nombre_oportunidad: str = Field(
        default="Nombre de la oportunidad", alias="COL_NOMBRE_OPORTUNIDAD"
    )
    col_cobro:       str = Field(default="Cobro",    alias="COL_COBRO")
    col_enviadas:    str = Field(default="ENVIADAS", alias="COL_ENVIADAS")
    fila_encabezado: int = Field(default=1,          alias="FILA_ENCABEZADO")

    # ── Matching fuzzy ───────────────────────────────────────────────────────
    umbral_similitud: int = Field(default=70, ge=0, le=100, alias="UMBRAL_SIMILITUD")

    # ── Comportamiento del bot ───────────────────────────────────────────────
    timeout_carga:        int   = Field(default=30,  ge=1,   alias="TIMEOUT_CARGA")
    pausa_entre_acciones: float = Field(default=1.5, ge=0.0, alias="PAUSA_ENTRE_ACCIONES")
    navegador_visible:    bool  = Field(default=True,         alias="NAVEGADOR_VISIBLE")

    # ── Retry logic ──────────────────────────────────────────────────────────
    retry_max_intentos:     int   = Field(default=3,    ge=1,   alias="RETRY_MAX_INTENTOS")
    retry_espera_base:      float = Field(default=2.0,  ge=0.0, alias="RETRY_ESPERA_BASE")
    retry_espera_max:       float = Field(default=10.0, ge=0.0, alias="RETRY_ESPERA_MAX")
    circuit_breaker_umbral: int   = Field(default=5,    ge=1,   alias="CIRCUIT_BREAKER_UMBRAL")

    # ── Logs ─────────────────────────────────────────────────────────────────
    carpeta_logs:       str = Field(default="logs", alias="CARPETA_LOGS")
    log_retention_dias: int = Field(default=30, ge=1, alias="LOG_RETENTION_DIAS")

    # ── Notificación email ───────────────────────────────────────────────────
    email_destinatario: str = Field(default="", alias="EMAIL_DESTINATARIO")
    email_remitente:    str = Field(default="", alias="EMAIL_REMITENTE")
    email_app_password: str = Field(default="", alias="EMAIL_APP_PASSWORD")

    # ── Selectores de Salesforce ─────────────────────────────────────────────
    selectores_path: str = Field(default="selectores.json", alias="SELECTORES_PATH")

    # ── Validación de archivos PDF ───────────────────────────────────────────
    max_pdf_mb: int = Field(default=20, ge=1, alias="MAX_PDF_MB")

    # ── Validadores ──────────────────────────────────────────────────────────
    @field_validator("salesforce_username", "salesforce_password", mode="before")
    @classmethod
    def no_placeholder(cls, v: object) -> object:
        """Rechaza los valores placeholder que el usuario olvidó reemplazar."""
        if v in ("COMPLETAR", "COMPLETAR@email.com", "COMPLETAR@gmail.com"):
            return ""
        return v


# =============================================================================
# INSTANCIA GLOBAL — única fuente de verdad en todo el proyecto
# =============================================================================

settings = Settings()

# =============================================================================
# ALIASES EN MAYÚSCULA — mantienen compatibilidad con el resto del proyecto
# sin cambiar ningún import existente en salesforce_bot, notificacion, etc.
# =============================================================================

SALESFORCE_USERNAME:     str   = settings.salesforce_username
SALESFORCE_PASSWORD:     str   = settings.salesforce_password

COL_NOMBRE_OPORTUNIDAD:  str   = settings.col_nombre_oportunidad
COL_COBRO:               str   = settings.col_cobro
COL_ENVIADAS:            str   = settings.col_enviadas
FILA_ENCABEZADO:         int   = settings.fila_encabezado

UMBRAL_SIMILITUD:        int   = settings.umbral_similitud

TIMEOUT_CARGA:           int   = settings.timeout_carga
PAUSA_ENTRE_ACCIONES:    float = settings.pausa_entre_acciones
NAVEGADOR_VISIBLE:       bool  = settings.navegador_visible

RETRY_MAX_INTENTOS:      int   = settings.retry_max_intentos
RETRY_ESPERA_BASE:       float = settings.retry_espera_base
RETRY_ESPERA_MAX:        float = settings.retry_espera_max
CIRCUIT_BREAKER_UMBRAL:  int   = settings.circuit_breaker_umbral

CARPETA_LOGS:            str   = settings.carpeta_logs
LOG_RETENTION_DIAS:      int   = settings.log_retention_dias

EMAIL_DESTINATARIO:      str   = settings.email_destinatario
EMAIL_REMITENTE:         str   = settings.email_remitente
EMAIL_APP_PASSWORD:      str   = settings.email_app_password

SELECTORES_PATH:         str   = settings.selectores_path

MAX_PDF_MB:              int   = settings.max_pdf_mb

# =============================================================================
# TIMEOUTS DERIVADOS — calculados una vez desde TIMEOUT_CARGA
# Definidos aquí (módulo neutral) para que selector_healer.py los importe
# sin crear un ciclo con salesforce_bot.py.
# =============================================================================

# Navegación y espera de carga de página (configurable por el usuario)
TIMEOUT_NAVEGACION:    int = settings.timeout_carga * 1000

# Subida de archivos PDF: operación lenta, 3× el timeout de navegación
TIMEOUT_CARGA_ARCHIVO: int = settings.timeout_carga * 3 * 1000

# Visibilidad de elementos simples (barra búsqueda, botones): siempre rápido
TIMEOUT_ELEMENTO:      int = 10_000