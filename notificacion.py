# =============================================================================
# notificacion.py — Envío de mail al finalizar el bot
# =============================================================================
# Usa Gmail con contraseña de aplicación (App Password).
# No requiere librerías externas — smtplib y email vienen con Python.
#
# Cómo obtener la App Password de Gmail:
#   1. Ir a myaccount.google.com → Seguridad
#   2. Activar verificación en dos pasos (requerido)
#   3. Ir a "Contraseñas de aplicaciones"
#   4. Generar una para "Correo" → copiar los 16 caracteres
#   5. Pegarla en EMAIL_APP_PASSWORD del archivo .env
# =============================================================================

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from config import EMAIL_DESTINATARIO, EMAIL_REMITENTE, EMAIL_APP_PASSWORD


# =============================================================================
# FUNCIÓN PRINCIPAL
# =============================================================================

def enviar_resumen(
    modo: str,
    totales: Dict[str, int],
    errores_detalle: List[Dict],
    ruta_log: Optional[str] = None,
    logger: Optional[logging.Logger] = None,
) -> bool:
    """
    Envía un mail con el resumen de la corrida al finalizar.

    Parámetros:
    - modo           : "dryrun" o "real"
    - totales        : dict con keys ok, ya_facturado, errores
    - errores_detalle: lista de dicts con keys cobro, nombre, estado, detalle
    - ruta_log       : ruta al archivo de log (se adjunta si existe)
    - logger         : logger del bot (opcional)

    Retorna True si se envió correctamente, False si hubo un error.
    """

    # Verificar que las credenciales estén configuradas
    if not EMAIL_REMITENTE or EMAIL_REMITENTE == "COMPLETAR@gmail.com":
        if logger:
            logger.warning("Email no configurado en .env — se omite notificación.")
        return False

    if not EMAIL_APP_PASSWORD or EMAIL_APP_PASSWORD == "COMPLETAR":
        if logger:
            logger.warning("App Password de Gmail no configurada — se omite notificación.")
        return False

    try:
        asunto:      str = _construir_asunto(modo, totales)
        cuerpo_html: str = _construir_cuerpo(modo, totales, errores_detalle)

        msg: MIMEMultipart = MIMEMultipart("mixed")
        msg["From"]    = EMAIL_REMITENTE
        msg["To"]      = EMAIL_DESTINATARIO
        msg["Subject"] = asunto

        # Cuerpo HTML
        msg.attach(MIMEText(cuerpo_html, "html", "utf-8"))

        # Adjuntar log si existe
        if ruta_log and Path(ruta_log).exists():
            with open(ruta_log, "rb") as f:
                adjunto: MIMEBase = MIMEBase("application", "octet-stream")
                adjunto.set_payload(f.read())
            encoders.encode_base64(adjunto)
            nombre_log: str = Path(ruta_log).name
            adjunto.add_header(
                "Content-Disposition",
                f'attachment; filename="{nombre_log}"'
            )
            msg.attach(adjunto)

        # Enviar via Gmail SMTP
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as servidor:
            servidor.login(EMAIL_REMITENTE, EMAIL_APP_PASSWORD)
            servidor.sendmail(EMAIL_REMITENTE, EMAIL_DESTINATARIO, msg.as_string())

        if logger:
            logger.info(f"Notificación enviada a {EMAIL_DESTINATARIO}")

        return True

    except smtplib.SMTPAuthenticationError:
        if logger:
            logger.warning(
                "Error de autenticación Gmail. "
                "Verificá que EMAIL_APP_PASSWORD sea una App Password válida, "
                "no la contraseña normal de tu cuenta."
            )
        return False

    except Exception as e:
        if logger:
            logger.warning(f"No se pudo enviar el mail de notificación: {e}")
        return False


# =============================================================================
# HELPERS INTERNOS
# =============================================================================

def _construir_asunto(modo: str, totales: Dict[str, int]) -> str:
    modo_txt: str = "DRY-RUN" if modo == "dryrun" else "REAL"
    ok:       int = totales.get("ok", 0)
    errores:  int = totales.get("errores", 0)
    estado:   str = "✅ Sin errores" if errores == 0 else f"⚠️ {errores} con error"
    return f"InvoiceFlow Bot [{modo_txt}] — {estado} · {ok} procesados"


def _construir_cuerpo(
    modo: str,
    totales: Dict[str, int],
    errores_detalle: List[Dict],
) -> str:
    """Construye el cuerpo del mail en HTML con diseño limpio."""

    modo_txt:  str = "Simulación (Dry-run)" if modo == "dryrun" else "Ejecución real"
    ok:        int = totales.get("ok", 0)
    ya_fact:   int = totales.get("ya_facturado", 0)
    errores:   int = totales.get("errores", 0)
    timestamp: str = datetime.now().strftime("%d/%m/%Y %H:%M")
    color_modo: str = "#0070d2" if modo == "dryrun" else "#c0392b"

    # Sección de errores detallados
    tabla_errores: str = ""
    if errores_detalle:
        filas: str = ""
        for i, e in enumerate(errores_detalle):
            bg: str = "#f9f9f9" if i % 2 == 0 else "#ffffff"
            filas += f"""
            <tr style="background:{bg}">
                <td style="padding:8px 12px;border-bottom:1px solid #eee;font-size:13px">{e.get('cobro','')}</td>
                <td style="padding:8px 12px;border-bottom:1px solid #eee;font-size:13px">{e.get('nombre','')}</td>
                <td style="padding:8px 12px;border-bottom:1px solid #eee;font-size:13px;color:#c0392b;font-weight:600">{e.get('estado','')}</td>
                <td style="padding:8px 12px;border-bottom:1px solid #eee;font-size:12px;color:#666">{e.get('detalle','')}</td>
            </tr>"""

        tabla_errores = f"""
        <div style="margin-top:24px">
            <p style="font-size:14px;font-weight:600;color:#333;margin-bottom:10px">
                Clientes que requieren atención ({len(errores_detalle)})
            </p>
            <table style="width:100%;border-collapse:collapse;font-family:Arial,sans-serif">
                <thead>
                    <tr style="background:#0070d2">
                        <th style="padding:9px 12px;text-align:left;color:white;font-size:12px">Cobro</th>
                        <th style="padding:9px 12px;text-align:left;color:white;font-size:12px">Cliente</th>
                        <th style="padding:9px 12px;text-align:left;color:white;font-size:12px">Estado</th>
                        <th style="padding:9px 12px;text-align:left;color:white;font-size:12px">Detalle</th>
                    </tr>
                </thead>
                <tbody>{filas}</tbody>
            </table>
        </div>"""

    nota_dryrun: str = ""
    if modo == "dryrun":
        nota_dryrun = """
        <div style="background:#e8f4ff;border-left:3px solid #0070d2;padding:10px 14px;
                    margin-top:20px;border-radius:0 6px 6px 0;font-size:13px;color:#0070d2">
            <b>Modo Simulación:</b> no se modificó ningún dato en Salesforce.
            Este informe muestra el estado previo a una ejecución real.
        </div>"""

    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f4f6f9;font-family:Arial,sans-serif">

<div style="max-width:640px;margin:32px auto;background:white;
            border-radius:10px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08)">

    <!-- Header -->
    <div style="background:#0070d2;padding:22px 28px">
        <p style="margin:0;color:rgba(255,255,255,0.75);font-size:11px;letter-spacing:1px">
            INVOICEFLOW BOT — NOTIFICACIÓN AUTOMÁTICA
        </p>
        <h1 style="margin:6px 0 0;color:white;font-size:20px;font-weight:700">
            Corrida finalizada
        </h1>
    </div>

    <!-- Cuerpo -->
    <div style="padding:26px 28px">

        <!-- Modo y timestamp -->
        <div style="display:flex;justify-content:space-between;align-items:center;
                    margin-bottom:20px">
            <span style="background:{color_modo};color:white;padding:4px 12px;
                          border-radius:20px;font-size:12px;font-weight:600">
                {modo_txt}
            </span>
            <span style="color:#999;font-size:12px">{timestamp}</span>
        </div>

        <!-- Métricas -->
        <table style="width:100%;border-collapse:collapse;margin-bottom:6px">
            <tr>
                <td style="width:33%;padding:14px;text-align:center;
                           background:#eafaf1;border-radius:8px">
                    <div style="font-size:28px;font-weight:700;color:#1e8449">{ok}</div>
                    <div style="font-size:12px;color:#666;margin-top:3px">
                        {"PDFs listos" if modo == "dryrun" else "Procesados OK"}
                    </div>
                </td>
                <td style="width:4%"></td>
                <td style="width:33%;padding:14px;text-align:center;
                           background:#fef9e7;border-radius:8px">
                    <div style="font-size:28px;font-weight:700;color:#b7770d">{ya_fact}</div>
                    <div style="font-size:12px;color:#666;margin-top:3px">Ya facturados</div>
                </td>
                <td style="width:4%"></td>
                <td style="width:33%;padding:14px;text-align:center;
                           background:{"#eafaf1" if errores == 0 else "#fef0ef"};border-radius:8px">
                    <div style="font-size:28px;font-weight:700;
                                color:{"#1e8449" if errores == 0 else "#c0392b"}">{errores}</div>
                    <div style="font-size:12px;color:#666;margin-top:3px">
                        {"Sin errores ✓" if errores == 0 else "Con errores"}
                    </div>
                </td>
            </tr>
        </table>

        {nota_dryrun}
        {tabla_errores}

    </div>

    <!-- Footer -->
    <div style="background:#f4f6f9;padding:14px 28px;border-top:1px solid #eee">
        <p style="margin:0;font-size:11px;color:#999">
            Este mail fue generado automáticamente por InvoiceFlow Bot.
            El log completo está adjunto a este correo.
        </p>
    </div>

</div>
</body>
</html>"""