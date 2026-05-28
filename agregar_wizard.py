"""
agregar_wizard.py -- Agrega el wizard de configuracion inicial a app.py
=======================================================================
Ejecutar UNA sola vez desde la carpeta raiz del proyecto:
    python agregar_wizard.py

Que hace:
  1. Backup de app.py -> app.py.bak2
  2. Agrega endpoint GET /estado_credenciales  (verifica si .env esta completo)
  3. Agrega endpoint POST /guardar_credenciales (escribe el .env)
  4. Inyecta el modal wizard en el HTML del panel
  5. Inyecta el boton en el header
  6. Inyecta el JS del wizard

Seguro de correr multiples veces: detecta si el wizard ya fue agregado.
"""

import shutil
import sys
from pathlib import Path

APP = Path("app.py")
BAK = Path("app.py.bak2")
ENV = Path(".env")

MARKER = "__WIZARD_INSTALADO__"

# =============================================================================
# ENDPOINTS FLASK A INSERTAR
# Se insertan justo antes de la linea: @app.route("/")
# =============================================================================

ENDPOINTS = r'''
# =============================================================================
# __WIZARD_INSTALADO__
# WIZARD DE CONFIGURACION -- endpoints
# =============================================================================

import re as _re
import concurrent.futures as _cf
from pathlib import Path

def _leer_env_actual() -> dict:
    """Lee el .env actual y retorna dict con los valores."""
    vals = {
        "sf_user": "", "sf_pass": "",
        "email_dest": "", "email_rem": "", "email_pass": "",
    }
    env_path = Path(".env")
    if not env_path.exists():
        return vals
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip()
        if k == "SALESFORCE_USERNAME":  vals["sf_user"]    = v
        if k == "SALESFORCE_PASSWORD":  vals["sf_pass"]    = v
        if k == "EMAIL_DESTINATARIO":   vals["email_dest"] = v
        if k == "EMAIL_REMITENTE":      vals["email_rem"]  = v
        if k == "EMAIL_APP_PASSWORD":   vals["email_pass"] = v
    return vals

def _credenciales_completas(vals: dict) -> bool:
    PLACEHOLDERS = {"COMPLETAR", "COMPLETAR@email.com", "COMPLETAR@gmail.com", ""}
    return (
        vals["sf_user"]  not in PLACEHOLDERS and
        vals["sf_pass"]  not in PLACEHOLDERS
    )

@app.route("/estado_credenciales")
def estado_credenciales() -> Any:
    """Informa al panel si el .env tiene credenciales completas."""
    vals = _leer_env_actual()
    return jsonify({
        "completas": _credenciales_completas(vals),
        "sf_user":    vals["sf_user"]    if vals["sf_user"]    not in {"COMPLETAR", "COMPLETAR@email.com", ""} else "",
        "email_rem":  vals["email_rem"]  if vals["email_rem"]  not in {"COMPLETAR@gmail.com", ""}             else "",
        "email_dest": vals["email_dest"] if vals["email_dest"] not in {"COMPLETAR@gmail.com", ""}             else "",
        "tiene_email": vals["email_rem"] not in {"COMPLETAR@gmail.com", ""},
    })

@app.route("/guardar_credenciales", methods=["POST"])
def guardar_credenciales() -> Any:
    """Escribe las credenciales en el archivo .env sin perder otras variables."""
    data = request.json or {}
    sf_url     = data.get("sf_url",     "").strip()
    sf_user    = data.get("sf_user",    "").strip()
    sf_pass    = data.get("sf_pass",    "").strip()
    email_dest = data.get("email_dest", "").strip()
    email_rem  = data.get("email_rem",  "").strip()
    email_pass = data.get("email_pass", "").strip()

    if not sf_user or not sf_pass:
        return jsonify({"ok": False, "error": "Usuario y contrasena de Salesforce son obligatorios."})

    env_path = Path(".env")

    # Leer contenido actual o plantilla
    if env_path.exists():
        lineas = env_path.read_text(encoding="utf-8").splitlines()
    else:
        lineas = [
            "# InvoiceFlow Bot -- Credenciales",
            "SALESFORCE_USERNAME=",
            "SALESFORCE_PASSWORD=",
            "SALESFORCE_URL=",
            "EMAIL_DESTINATARIO=",
            "EMAIL_REMITENTE=",
            "EMAIL_APP_PASSWORD=",
        ]

    # Mapeo clave -> nuevo valor
    cambios = {
        "SALESFORCE_USERNAME": sf_user,
        "SALESFORCE_PASSWORD": sf_pass,
    }
    if sf_url:     cambios["SALESFORCE_URL"]      = sf_url
    if email_rem:  cambios["EMAIL_REMITENTE"]      = email_rem
    if email_dest: cambios["EMAIL_DESTINATARIO"]   = email_dest
    if email_pass: cambios["EMAIL_APP_PASSWORD"]   = email_pass

    # Reemplazar o agregar cada clave
    claves_presentes = set()
    nuevas_lineas = []
    for linea in lineas:
        if "=" in linea and not linea.strip().startswith("#"):
            k = linea.split("=", 1)[0].strip()
            if k in cambios:
                nuevas_lineas.append(f"{k}={cambios[k]}")
                claves_presentes.add(k)
                continue
        nuevas_lineas.append(linea)

    # Agregar claves que no estaban en el archivo
    for k, v in cambios.items():
        if k not in claves_presentes:
            nuevas_lineas.append(f"{k}={v}")

    try:
        env_path.write_text("\n".join(nuevas_lineas) + "\n", encoding="utf-8")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route("/verificar_sf", methods=["POST"])
def verificar_sf() -> Any:
    """
    Verifica credenciales Salesforce con un login headless real.
    Body JSON: {"url": "...", "username": "...", "password": "..."}
    Retorna: {"ok": bool, "error": str}
    Timeout: 90s (ampliado para cuentas con aprobación manual). No guarda nada — solo verifica.
    """
    data = request.json or {}
    url  = data.get("url",      "").strip()
    user = data.get("username", "").strip()
    pwd  = data.get("password", "").strip()

    if not url or not user or not pwd:
        return jsonify({"ok": False, "error": "Completa URL, usuario y contrasena antes de verificar."})

    if runner.corriendo:
        return jsonify({"ok": False, "error": "El bot esta en ejecucion. Intentar al terminar."})

    def _verificar():
        from salesforce_bot import SalesforceBot as _SF, AprobacionPendienteError as _APE
        import logging as _lg
        _logger = _lg.getLogger("verificar_sf")
        bot = _SF(logger=_logger, salesforce_url=url)
        # Sobreescribir credenciales para esta verificacion puntual
        bot._sf_username = user
        bot._sf_password = pwd
        try:
            bot.iniciar()
            return {"ok": True}
        except _APE:
            # La cuenta requiere aprobacion manual — las credenciales SON correctas
            # pero el admin debe aprobar el acceso. No es un error de credenciales.
            return {
                "ok": True,
                "advertencia": (
                    "Las credenciales son correctas, pero tu cuenta requiere que un "
                    "administrador apruebe tu acceso en Salesforce antes de operar. "
                    "Avisale al admin ahora para que el bot pueda correr sin interrupciones."
                )
            }
        except Exception as exc:
            msg = str(exc)[:300]
            if "pass" in msg.lower() or "login" in msg.lower() or "incorrect" in msg.lower():
                return {"ok": False, "error": "Usuario o contrasena incorrectos."}
            if "timeout" in msg.lower() or "net::" in msg.lower():
                return {"ok": False, "error": "No se pudo conectar a Salesforce. Verificar URL y conexion a internet."}
            return {"ok": False, "error": f"Error al conectar: {msg}"}
        finally:
            try:
                bot.cerrar()
            except Exception:
                pass

    executor = _cf.ThreadPoolExecutor(max_workers=1, thread_name_prefix="verificar_sf")
    future = executor.submit(_verificar)
    try:
        result = future.result(timeout=90)
    except _cf.TimeoutError:
        result = {
            "ok": False,
            "error": (
                "Tiempo de espera agotado (90 seg). "
                "Verificá la URL y tu conexión a internet. "
                "Si tu cuenta requiere aprobación del administrador, "
                "pedile que te apruebe el acceso y volvé a verificar."
            )
        }
    except Exception as exc:
        result = {"ok": False, "error": str(exc)[:200]}
    finally:
        executor.shutdown(wait=False)

    return jsonify(result)

'''

# =============================================================================
# BLOQUE HTML DEL MODAL -- se inserta justo despues de <body>
# =============================================================================

MODAL_HTML = r'''
<!-- --- WIZARD DE CONFIGURACION INICIAL --- -->
<div id="wiz-overlay" style="display:none;position:fixed;inset:0;background:rgba(15,20,30,0.72);z-index:9999;align-items:center;justify-content:center;">
  <div style="background:#fff;border-radius:10px;width:420px;max-width:94vw;box-shadow:0 8px 40px rgba(0,0,0,0.22);overflow:hidden;">

    <!-- Header del modal -->
    <div style="background:#2f5d8a;padding:18px 22px 14px;">
      <div style="color:rgba(255,255,255,0.7);font-size:10px;letter-spacing:.08em;text-transform:uppercase;margin-bottom:4px">InvoiceFlow Bot v1.4</div>
      <div style="color:#fff;font-size:16px;font-weight:600" id="wiz-titulo">Configuracion inicial</div>
      <!-- Indicador de pasos -->
      <div style="display:flex;gap:6px;margin-top:12px">
        <div id="wiz-dot-1" style="height:4px;flex:1;border-radius:2px;background:rgba(255,255,255,0.9)"></div>
        <div id="wiz-dot-2" style="height:4px;flex:1;border-radius:2px;background:rgba(255,255,255,0.3)"></div>
      </div>
    </div>

    <!-- Cuerpo del modal -->
    <div style="padding:20px 22px">

      <!-- PASO 1: Salesforce -->
      <div id="wiz-paso-1">
        <div style="font-size:12px;color:#4a5568;margin-bottom:14px;line-height:1.6">
          Ingresa tus credenciales de Salesforce. Se guardan localmente en el archivo <code style="background:#f0f0f0;padding:1px 5px;border-radius:3px">.env</code>.
        </div>
        <div style="margin-bottom:12px">
          <label style="font-size:11px;font-weight:600;color:#6d737a;display:block;margin-bottom:4px">URL de Salesforce</label>
          <input type="text" id="wiz-sf-url" placeholder="https://miempresa.my.salesforce.com"
            style="width:100%;padding:8px 10px;border:1px solid #d1d5db;border-radius:5px;font-size:13px;box-sizing:border-box">
        </div>
        <div style="margin-bottom:12px">
          <label style="font-size:11px;font-weight:600;color:#6d737a;display:block;margin-bottom:4px">Usuario de Salesforce</label>
          <input type="text" id="wiz-sf-user" placeholder="tu_usuario@empresa.com"
            style="width:100%;padding:8px 10px;border:1px solid #d1d5db;border-radius:5px;font-size:13px;box-sizing:border-box">
        </div>
        <div style="margin-bottom:10px">
          <label style="font-size:11px;font-weight:600;color:#6d737a;display:block;margin-bottom:4px">Contrasena de Salesforce</label>
          <div style="position:relative">
            <input type="password" id="wiz-sf-pass" placeholder="Tu contrasena"
              style="width:100%;padding:8px 36px 8px 10px;border:1px solid #d1d5db;border-radius:5px;font-size:13px;box-sizing:border-box">
            <span onclick="wizTogglePass('wiz-sf-pass',this)"
              style="position:absolute;right:10px;top:50%;transform:translateY(-50%);cursor:pointer;font-size:14px;color:#9aa3ad;user-select:none">[O]</span>
          </div>
        </div>
        <div style="margin-bottom:4px">
          <button id="wiz-btn-verificar" onclick="wizVerificarSF()"
            style="width:100%;padding:8px;background:#f0f6ff;border:1px solid #b8d0f0;border-radius:5px;font-size:12px;color:#2f5d8a;cursor:pointer;font-weight:600">
            Verificar conexion con Salesforce
          </button>
          <div id="wiz-verificar-estado" style="display:none;margin-top:6px;padding:6px 10px;border-radius:4px;font-size:11px"></div>
        </div>
        <div id="wiz-err-1" style="display:none;background:#fdecea;border-left:3px solid #b4232c;padding:7px 10px;border-radius:4px;font-size:11px;margin-top:10px;color:#7a1a1a"></div>
      </div>

      <!-- PASO 2: Email -->
      <div id="wiz-paso-2" style="display:none">
        <div style="font-size:12px;color:#4a5568;margin-bottom:14px;line-height:1.6">
          Opcional: el bot puede enviarte un resumen por email al finalizar cada corrida.
          Deja en blanco para omitir esta funcion.
        </div>
        <div style="margin-bottom:12px">
          <label style="font-size:11px;font-weight:600;color:#6d737a;display:block;margin-bottom:4px">Email remitente <span style="font-weight:400;color:#9aa3ad">(Gmail)</span></label>
          <input type="text" id="wiz-email-rem" placeholder="tucuenta@gmail.com"
            style="width:100%;padding:8px 10px;border:1px solid #d1d5db;border-radius:5px;font-size:13px;box-sizing:border-box">
        </div>
        <div style="margin-bottom:12px">
          <label style="font-size:11px;font-weight:600;color:#6d737a;display:block;margin-bottom:4px">Email destinatario</label>
          <input type="text" id="wiz-email-dest" placeholder="destino@empresa.com"
            style="width:100%;padding:8px 10px;border:1px solid #d1d5db;border-radius:5px;font-size:13px;box-sizing:border-box">
        </div>
        <div style="margin-bottom:6px">
          <label style="font-size:11px;font-weight:600;color:#6d737a;display:block;margin-bottom:4px">
            App Password de Gmail
            <a href="https://myaccount.google.com/apppasswords" target="_blank"
              style="font-weight:400;color:#2f5d8a;margin-left:6px">Como obtenerla?</a>
          </label>
          <div style="position:relative">
            <input type="password" id="wiz-email-pass" placeholder="xxxx xxxx xxxx xxxx"
              style="width:100%;padding:8px 36px 8px 10px;border:1px solid #d1d5db;border-radius:5px;font-size:13px;font-family:monospace;box-sizing:border-box">
            <span onclick="wizTogglePass('wiz-email-pass',this)"
              style="position:absolute;right:10px;top:50%;transform:translateY(-50%);cursor:pointer;font-size:14px;color:#9aa3ad;user-select:none">[O]</span>
          </div>
          <div style="font-size:10px;color:#9aa3ad;margin-top:3px">No es tu contrasena normal de Gmail. Requiere verificacion en dos pasos activada.</div>
        </div>
        <div id="wiz-err-2" style="display:none;background:#fdecea;border-left:3px solid #b4232c;padding:7px 10px;border-radius:4px;font-size:11px;margin-top:10px;color:#7a1a1a"></div>
      </div>

    </div><!-- fin cuerpo -->

    <!-- Footer con botones -->
    <div style="padding:14px 22px 18px;display:flex;justify-content:space-between;align-items:center;border-top:1px solid #e5e7eb">
      <button id="wiz-btn-omitir" onclick="wizOmitirEmail()"
        style="background:none;border:none;color:#9aa3ad;font-size:12px;cursor:pointer;padding:4px">
        Omitir email por ahora
      </button>
      <div style="display:flex;gap:8px">
        <button id="wiz-btn-atras" onclick="wizAtras()" style="display:none;padding:8px 16px;border:1px solid #d1d5db;border-radius:5px;background:#fff;font-size:12px;cursor:pointer;font-weight:600">
          Atras
        </button>
        <button id="wiz-btn-siguiente" onclick="wizSiguiente()"
          style="padding:8px 20px;background:#2f5d8a;color:#fff;border:none;border-radius:5px;font-size:12px;font-weight:600;cursor:pointer">
          Siguiente
        </button>
        <button id="wiz-btn-guardar" onclick="wizGuardar()" style="display:none;padding:8px 20px;background:#2e7d32;color:#fff;border:none;border-radius:5px;font-size:12px;font-weight:600;cursor:pointer">
          Guardar y comenzar
        </button>
      </div>
    </div>

  </div>
</div>
<!-- --- FIN WIZARD --- -->

'''

# =============================================================================
# BOTON EN EL HEADER -- se inserta reemplazando el cierre </header>
# Como el panel no tiene <header> explicito se inyecta como div fijo
# Se agrega justo antes del cierre del </style> del panel
# =============================================================================

BTN_HEADER_CSS = r'''
/* Boton wizard en header */
.wiz-btn-header{position:fixed;top:10px;right:14px;z-index:100;background:#fff;border:1px solid #d1d5db;border-radius:5px;padding:5px 11px;font-size:11px;font-weight:600;color:#4a5568;cursor:pointer;display:flex;align-items:center;gap:5px;box-shadow:0 1px 4px rgba(0,0,0,0.08);}
.wiz-btn-header:hover{background:#f6f8fa;}
.wiz-btn-header.alerta{border-color:#e53e3e;color:#e53e3e;background:#fff5f5;}
'''

BTN_HEADER_HTML = r'''
<button class="wiz-btn-header" id="btn-abrir-wizard" onclick="abrirWizard()" style="display:none">
  [cfg] Credenciales
</button>
'''

# =============================================================================
# JS DEL WIZARD -- se inserta antes del </script> final
# =============================================================================

WIZARD_JS = r'''

// --- WIZARD DE CONFIGURACION -------------------------------------------------
let _wizPaso = 1;
let _wizSFVerificado = false;

function abrirWizard() {
  _wizPaso = 1;
  _wizSFVerificado = false;
  _wizMostrarPaso(1);
  document.getElementById('wiz-overlay').style.display = 'flex';
  // Pre-llenar URL desde el campo principal del panel si existe
  const urlPanel = document.getElementById('url');
  const urlWiz   = document.getElementById('wiz-sf-url');
  if (urlPanel && urlWiz && !urlWiz.value && urlPanel.value)
    urlWiz.value = urlPanel.value;
}

function _wizMostrarPaso(n) {
  _wizPaso = n;
  document.getElementById('wiz-paso-1').style.display = n === 1 ? 'block' : 'none';
  document.getElementById('wiz-paso-2').style.display = n === 2 ? 'block' : 'none';
  document.getElementById('wiz-btn-siguiente').style.display = n === 1 ? 'inline-block' : 'none';
  document.getElementById('wiz-btn-guardar').style.display   = n === 2 ? 'inline-block' : 'none';
  document.getElementById('wiz-btn-atras').style.display     = n === 2 ? 'inline-block' : 'none';
  document.getElementById('wiz-btn-omitir').style.display    = n === 2 ? 'inline-block' : 'none';
  document.getElementById('wiz-titulo').textContent = n === 1
    ? 'Configuracion inicial (1 de 2)'
    : 'Notificacion por email (2 de 2)';
  document.getElementById('wiz-dot-1').style.background = 'rgba(255,255,255,0.9)';
  document.getElementById('wiz-dot-2').style.background = n === 2 ? 'rgba(255,255,255,0.9)' : 'rgba(255,255,255,0.3)';
  document.getElementById('wiz-err-1').style.display = 'none';
  document.getElementById('wiz-err-2').style.display = 'none';
}

function wizTogglePass(inputId, btn) {
  const inp = document.getElementById(inputId);
  if (inp.type === 'password') { inp.type = 'text';     btn.textContent = '[X]'; }
  else                          { inp.type = 'password'; btn.textContent = '[O]'; }
}

function wizAtras() { _wizMostrarPaso(1); }

// M1 — Verificacion de credenciales SF con login headless real
async function wizVerificarSF() {
  const url  = document.getElementById('wiz-sf-url').value.trim();
  const user = document.getElementById('wiz-sf-user').value.trim();
  const pass = document.getElementById('wiz-sf-pass').value.trim();
  const estado = document.getElementById('wiz-verificar-estado');
  const btn    = document.getElementById('wiz-btn-verificar');
  const err    = document.getElementById('wiz-err-1');

  err.style.display = 'none';
  if (!url || !user || !pass) {
    err.textContent = 'Completa URL, usuario y contrasena antes de verificar.';
    err.style.display = 'block';
    return;
  }

  btn.textContent = 'Verificando... (puede tardar hasta 90 seg)';
  btn.disabled = true;
  estado.style.display = 'block';
  estado.style.background = '#f0f6ff';
  estado.style.color = '#2f5d8a';
  estado.textContent = 'Conectando con Salesforce...';
  _wizSFVerificado = false;

  try {
    const r = await fetch('/verificar_sf', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, username: user, password: pass })
    });
    const d = await r.json();
    if (d.ok) {
      _wizSFVerificado = true;
      // Sincronizar URL con el panel principal
      const urlPanel = document.getElementById('url');
      const urlCal   = document.getElementById('cal-url');
      if (urlPanel) urlPanel.value = url;
      if (urlCal)   urlCal.value   = url;
      if (d.advertencia) {
        // Credenciales OK pero cuenta requiere aprobacion manual de admin
        estado.style.background = '#fef9e7';
        estado.style.border     = '1px solid #f6bf26';
        estado.style.color      = '#7a5800';
        estado.style.padding    = '8px 10px';
        estado.style.lineHeight = '1.5';
        estado.innerHTML = '<strong>Credenciales correctas</strong><br>' + d.advertencia;
      } else {
        estado.style.background = '#eafaf1';
        estado.style.border     = '';
        estado.style.color      = '#2e7d32';
        estado.style.padding    = '';
        estado.style.lineHeight = '';
        estado.textContent = 'Conexion verificada correctamente.';
      }
    } else {
      estado.style.background = '#fdecea';
      estado.style.border     = '';
      estado.style.color      = '#b4232c';
      estado.style.padding    = '';
      estado.style.lineHeight = '';
      estado.textContent = d.error || 'Error al verificar.';
      _wizSFVerificado = false;
    }
  } catch(e) {
    estado.style.background = '#fdecea';
    estado.style.color = '#b4232c';
    estado.textContent = 'Error de red. Verifica que el bot este corriendo.';
  } finally {
    btn.textContent = 'Verificar conexion con Salesforce';
    btn.disabled = false;
  }
}

function wizSiguiente() {
  const u   = document.getElementById('wiz-sf-user').value.trim();
  const p   = document.getElementById('wiz-sf-pass').value.trim();
  const err = document.getElementById('wiz-err-1');
  if (!u) { err.textContent = 'El usuario de Salesforce no puede estar vacio.'; err.style.display='block'; return; }
  if (!p) { err.textContent = 'La contrasena de Salesforce no puede estar vacia.'; err.style.display='block'; return; }
  // Advertir si no se verifico (no bloquea — el usuario puede continuar igual)
  if (!_wizSFVerificado) {
    const estado = document.getElementById('wiz-verificar-estado');
    estado.style.display = 'block';
    estado.style.background = '#fef9e7';
    estado.style.color = '#b7791f';
    estado.textContent = 'Recomendacion: usa el boton Verificar para confirmar que las credenciales son correctas antes de continuar.';
  }
  _wizMostrarPaso(2);
}

function wizOmitirEmail() {
  _wizEnviarGuardado({ omitir_email: true });
}

// M7 — Validacion de formato email y App Password antes de guardar
async function wizGuardar() {
  const emailRem  = document.getElementById('wiz-email-rem').value.trim();
  const emailDest = document.getElementById('wiz-email-dest').value.trim();
  const emailPass = document.getElementById('wiz-email-pass').value.trim();
  const err = document.getElementById('wiz-err-2');
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

  if (emailRem || emailDest || emailPass) {
    if (!emailRem)  { err.textContent = 'Completa el email remitente.';  err.style.display='block'; return; }
    if (!emailRegex.test(emailRem))  { err.textContent = 'El email remitente no tiene formato valido (ej: cuenta@gmail.com).'; err.style.display='block'; return; }
    if (!emailDest) { err.textContent = 'Completa el email destinatario.'; err.style.display='block'; return; }
    if (!emailRegex.test(emailDest)) { err.textContent = 'El email destinatario no tiene formato valido.'; err.style.display='block'; return; }
    if (!emailPass) { err.textContent = 'Completa la App Password de Gmail.'; err.style.display='block'; return; }
    // App Password: 16 chars sin espacios, o 19 con espacios (formato "xxxx xxxx xxxx xxxx")
    const passClean = emailPass.replace(/\s/g, '');
    if (passClean.length !== 16) {
      err.textContent = 'La App Password debe tener 16 caracteres (ej: xxxx xxxx xxxx xxxx). Revisala en tu cuenta de Google.';
      err.style.display='block';
      return;
    }
  }
  _wizEnviarGuardado({ email_rem: emailRem, email_dest: emailDest, email_pass: emailPass });
}

async function _wizEnviarGuardado(extraData) {
  const btn = extraData.omitir_email
    ? document.getElementById('wiz-btn-omitir')
    : document.getElementById('wiz-btn-guardar');
  const textoOrig = btn.textContent;
  btn.textContent = 'Guardando...';
  btn.disabled = true;

  try {
    const url = document.getElementById('wiz-sf-url') ? document.getElementById('wiz-sf-url').value.trim() : '';
    const payload = {
      sf_url:     url,
      sf_user:    document.getElementById('wiz-sf-user').value.trim(),
      sf_pass:    document.getElementById('wiz-sf-pass').value.trim(),
      email_rem:  extraData.email_rem  || '',
      email_dest: extraData.email_dest || '',
      email_pass: extraData.email_pass || '',
    };
    const r = await fetch('/guardar_credenciales', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const d = await r.json();
    if (d.ok) {
      document.getElementById('wiz-overlay').style.display = 'none';
      document.getElementById('btn-abrir-wizard').classList.remove('alerta');
      agregarLogLinea('sistema', 'Credenciales guardadas correctamente en .env');
      // A2: Limpiar sesión guardada de Playwright — credenciales nuevas requieren login fresco
      try { await fetch('/limpiar_sesion_sf', { method: 'POST' }); } catch(_) {}
      // Actualizar badge de credenciales en header
      await _actualizarBadgeCredenciales();
      // Sincronizar URL con panel si vino del wizard
      if (url) {
        const urlPanel = document.getElementById('url');
        const urlCal   = document.getElementById('cal-url');
        if (urlPanel && !urlPanel.value) urlPanel.value = url;
        if (urlCal   && !urlCal.value)   urlCal.value   = url;
      }
    } else {
      const errEl = document.getElementById(_wizPaso === 1 ? 'wiz-err-1' : 'wiz-err-2');
      errEl.textContent = d.error || 'Error al guardar.';
      errEl.style.display = 'block';
    }
  } catch(e) {
    const errEl = document.getElementById('wiz-err-2');
    errEl.textContent = 'Error de red. Verifica que el bot este corriendo.';
    errEl.style.display = 'block';
  } finally {
    btn.textContent = textoOrig;
    btn.disabled = false;
  }
}

// Verificar credenciales al cargar y mostrar wizard si es necesario
async function _verificarCredencialesWizard() {
  try {
    const r = await fetch('/estado_credenciales');
    const d = await r.json();
    const btnWiz = document.getElementById('btn-abrir-wizard');
    btnWiz.style.display = 'flex';

    if (!d.completas) {
      if (d.sf_user)    document.getElementById('wiz-sf-user').value    = d.sf_user;
      if (d.email_rem)  document.getElementById('wiz-email-rem').value  = d.email_rem;
      if (d.email_dest) document.getElementById('wiz-email-dest').value = d.email_dest;
      btnWiz.classList.add('alerta');
      abrirWizard();
    }
  } catch(e) { /* si falla el fetch no bloquear el panel */ }
}

const _wizOrigOnload = window.onload;
window.onload = async function() {
  if (_wizOrigOnload) await _wizOrigOnload();
  await _verificarCredencialesWizard();
};
// --- FIN WIZARD --------------------------------------------------------------
'''

# =============================================================================
# APLICAR EL PARCHE
# =============================================================================

def main() -> None:
    if not APP.exists():
        print(f"[ERROR] No se encontro app.py. Ejecutar desde la carpeta del proyecto.")
        sys.exit(1)

    contenido = APP.read_text(encoding="utf-8").replace("\r\n", "\n")

    if MARKER in contenido:
        print("[OK] El wizard ya esta instalado en app.py -- nada que hacer.")
        return

    # Backup
    shutil.copy2(APP, BAK)
    print(f"[OK] Backup creado: {BAK}")

    # -- 1. Insertar endpoints Flask antes de @app.route("/") -----------------
    ANCHOR_ROUTE = '@app.route("/")\ndef index():'
    if ANCHOR_ROUTE not in contenido:
        # Intentar con salto de linea Windows
        ANCHOR_ROUTE = '@app.route("/")\r\ndef index():'
    if ANCHOR_ROUTE not in contenido:
        print("[ERROR] No se encontro el endpoint @app.route('/') para inyectar endpoints.")
        sys.exit(1)

    contenido = contenido.replace(
        '@app.route("/")\ndef index():',
        ENDPOINTS + '@app.route("/")\ndef index():',
        1
    )
    # Normalizar si habia CRLF
    if '@app.route("/")\r\ndef index():' in contenido:
        contenido = contenido.replace(
            '@app.route("/")\r\ndef index():',
            ENDPOINTS + '@app.route("/")\ndef index():',
            1
        )
    print("[OK] Endpoints Flask inyectados.")

    # -- 2. Insertar CSS del boton en el <style> del panel --------------------
    ANCHOR_CSS = ".cal-paso.error{color:var(--danger);}"
    if ANCHOR_CSS in contenido:
        contenido = contenido.replace(ANCHOR_CSS, ANCHOR_CSS + "\n" + BTN_HEADER_CSS, 1)
        print("[OK] CSS del wizard inyectado.")
    else:
        # Fallback: insertar antes del cierre del style
        contenido = contenido.replace("</style>", BTN_HEADER_CSS + "\n</style>", 1)
        print("[OK] CSS del wizard inyectado (fallback).")

    # -- 3. Insertar HTML del modal y boton justo despues de <body> -----------
    if "<body>" in contenido:
        contenido = contenido.replace("<body>", "<body>\n" + MODAL_HTML + BTN_HEADER_HTML, 1)
        print("[OK] HTML del modal inyectado.")
    else:
        print("[ERROR] No se encontro <body> en el HTML del panel.")
        sys.exit(1)

    # -- 4. Insertar JS antes del cierre de </script> -------------------------
    # Buscar el ultimo </script> dentro de PANEL_HTML (antes de las rutas Flask)
    # La se-al es que va seguido de </body></html>
    ANCHOR_JS = "</script>\n</body>\n</html>"
    if ANCHOR_JS not in contenido:
        ANCHOR_JS = "</script>\r\n</body>\r\n</html>"
    if ANCHOR_JS in contenido:
        contenido = contenido.replace(
            ANCHOR_JS,
            WIZARD_JS + "\n</script>\n</body>\n</html>",
            1
        )
        print("[OK] JS del wizard inyectado.")
    else:
        print("[ERROR] No se encontro el cierre </script></body></html> en el panel.")
        sys.exit(1)

    # -- Escribir resultado ----------------------------------------------------
    APP.write_text(contenido, encoding="utf-8")

    # -- Verificacion ---------------------------------------------------------
    nuevo = APP.read_text(encoding="utf-8")
    assert MARKER                        in nuevo, "FAIL: marker no encontrado"
    assert "guardar_credenciales"        in nuevo, "FAIL: endpoint guardar_credenciales no encontrado"
    assert "verificar_sf"                in nuevo, "FAIL: endpoint verificar_sf no encontrado"
    assert "wiz-overlay"                 in nuevo, "FAIL: modal HTML no encontrado"
    assert "wiz-sf-url"                  in nuevo, "FAIL: campo URL wizard no encontrado"
    assert "wizVerificarSF"              in nuevo, "FAIL: funcion wizVerificarSF no encontrada"
    assert "_verificarCredencialesWizard" in nuevo, "FAIL: JS no encontrado"

    print(f"[OK] Wizard instalado correctamente en {APP}")
    print()
    print("  PROXIMOS PASOS:")
    print("  1. Volver a empaquetar con EMPAQUETAR.bat")
    print("     (o probar directamente con: python app.py)")
    print("  2. Al abrir el panel, el wizard aparece automaticamente")
    print("     si las credenciales estan incompletas.")
    print("  3. El boton 'Credenciales' en la esquina superior derecha")
    print("     permite volver al wizard en cualquier momento.")


if __name__ == "__main__":
    main()