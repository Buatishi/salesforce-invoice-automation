# =============================================================================
# app.py — Panel de control web — InvoiceFlow Bot v1.4
# =============================================================================

import asyncio
import concurrent.futures
import json
import queue
import threading
import webbrowser
from typing import Any, Dict, Generator, Optional

from flask import Flask, render_template_string, request, jsonify, Response

from bot_runner import BotRunner
from config import settings, UMBRAL_SIMILITUD
from salesforce_bot import cargar_selectores, guardar_selectores
from validaciones import validar_todo
from progresodb import limpiar_sesion, hay_sesion_pendiente, cargar_sesion

app    = Flask(__name__)
runner = BotRunner()

# =============================================================================
# HTML DEL PANEL
# =============================================================================

PANEL_HTML = r'''<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>InvoiceFlow Bot v1.4 — Panel de Control</title>
<style>
:root{
  --bg:#f4f5f7;--card:#ffffff;--border:#d6d9de;
  --text:#20262e;--muted:#6b7280;
  --primary:#2f5d8a;--success:#2e7d32;--warning:#b7791f;--danger:#b4232c;
  --radius:6px;
}
*{box-sizing:border-box;margin:0;padding:0;}
body{font-family:Segoe UI,system-ui,-apple-system,Arial,sans-serif;background:var(--bg);color:var(--text);font-size:13px;line-height:1.35;}
header{background:#fff;border-bottom:1px solid var(--border);height:52px;padding:0 18px;display:flex;align-items:center;gap:10px;}
header h1{font-size:14px;font-weight:600;letter-spacing:.2px;}
.badge-version{margin-left:auto;font-size:11px;background:#eef1f4;padding:3px 8px;border-radius:4px;color:#555;}
.contenedor{max-width:1220px;margin:18px auto;padding:0 14px;display:grid;grid-template-columns:360px 1fr;gap:14px;}
.card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:14px;}
.card h2{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:#7a8087;margin-bottom:10px;}
.card+.card{margin-top:10px;}
.campo{margin-bottom:11px;}
.campo label{font-size:11px;font-weight:600;margin-bottom:4px;display:block;color:#6d737a;}
.campo input[type="text"],.campo textarea{width:100%;padding:6px 8px;border:1px solid var(--border);border-radius:4px;font-size:12px;background:#fff;transition:border .15s;}
.campo textarea{font-family:Consolas,monospace;font-size:11px;resize:vertical;min-height:52px;}
.campo input:focus,.campo textarea:focus{outline:none;border-color:var(--primary);}
.campo-hint{font-size:10px;color:#9aa3ad;margin-top:3px;}
/* tabs */
.tabs{display:flex;gap:2px;margin-bottom:10px;border-bottom:1px solid var(--border);}
.tab{padding:6px 12px;font-size:11px;font-weight:600;color:var(--muted);cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-1px;transition:.15s;}
.tab.activo{color:var(--primary);border-bottom-color:var(--primary);}
.tab-panel{display:none;}.tab-panel.activo{display:block;}
/* modo */
.modo-selector{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px;}
.modo-btn{border:1px solid var(--border);border-radius:5px;padding:8px;text-align:center;cursor:pointer;font-size:12px;transition:.15s;}
.modo-btn:hover{background:#f6f8fa;}
.activo-dryrun{border-color:#3b6ea8;background:#edf3fb;}
.activo-real{border-color:#c13b3b;background:#fdeeee;}
/* estado */
.estado-chip{padding:4px 9px;border-radius:4px;font-size:11px;font-weight:600;display:inline-block;margin-bottom:12px;}
.estado-inactivo{background:#eef1f4;color:#54606a;}
.estado-corriendo{background:#e8f5e9;color:var(--success);}
.estado-pausado{background:#fff4e0;color:var(--warning);}
/* métricas */
.metricas{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:12px;}
.metrica{border:1px solid var(--border);padding:8px;border-radius:5px;text-align:center;background:#fafbfc;}
.metrica-valor{font-size:17px;font-weight:600;}
.metrica-label{font-size:10px;color:#6f7680;}
/* progreso */
.progreso-barra-wrap{height:6px;background:#e3e6ea;border-radius:4px;overflow:hidden;}
.progreso-barra-fill{height:100%;background:var(--primary);transition:width .25s ease;}
.progreso-texto{font-size:10px;margin-top:4px;text-align:right;color:#6b7280;}
/* botones */
.botones{display:grid;grid-template-columns:repeat(2,1fr);gap:7px;margin-top:12px;}
.btn{border:none;border-radius:4px;padding:7px;font-size:12px;font-weight:600;cursor:pointer;color:#fff;transition:.15s;}
.btn:hover{filter:brightness(.95);}
.btn:active{transform:translateY(1px);}
.btn:disabled{opacity:.5;cursor:not-allowed;}
.btn-iniciar{background:var(--primary);}
.btn-pausar{background:var(--warning);}
.btn-reanudar{background:var(--success);}
.btn-detener{background:var(--danger);}
.btn-secundario{background:#fff;border:1px solid var(--border);color:var(--text);}
.btn-secundario:hover{background:#f6f8fa;}
/* slider umbral */
.umbral-wrap{display:flex;align-items:center;gap:8px;margin-top:2px;}
.umbral-wrap input[type=range]{flex:1;accent-color:var(--primary);}
.umbral-badge{font-size:12px;font-weight:700;color:var(--primary);min-width:36px;text-align:right;}
.umbral-hint{font-size:10px;color:#9aa3ad;margin-top:3px;}
/* selector de archivo */
.campo-archivo{display:flex;gap:6px;align-items:stretch;}
.campo-archivo input[type="text"]{flex:1;min-width:0;}
.btn-examinar{flex-shrink:0;padding:0 10px;border:1px solid var(--border);border-radius:4px;background:#f6f8fa;color:var(--text);font-size:11px;font-weight:600;cursor:pointer;white-space:nowrap;transition:.15s;}
.btn-examinar:hover{background:#eaecef;border-color:#adb5bd;}
.btn-examinar:active{background:#dde0e4;}
.btn-examinar.cargando{opacity:.6;cursor:wait;}
/* alertas */
.alerta{background:#fdecea;border-left:3px solid var(--danger);padding:7px;font-size:11px;margin-top:6px;border-radius:4px;}
.alerta-ok{background:#eafaf1;border-left:3px solid var(--success);padding:7px;font-size:11px;margin-top:6px;border-radius:4px;}
/* banner sesión */
.banner-sesion{background:#fff9e6;border:1px solid #f0d98a;padding:10px;border-radius:5px;margin-bottom:10px;display:flex;align-items:center;gap:8px;}
.banner-sesion.oculto{display:none;}
/* Banner aprobacion manual Salesforce */
.banner-aprobacion{background:#fff8e1;border:1px solid #f6bf26;border-left:4px solid #f6bf26;padding:12px 14px;border-radius:5px;margin-bottom:10px;display:none;}
.banner-aprobacion.visible{display:block;}
.banner-aprobacion-titulo{font-size:12px;font-weight:700;color:#7a5800;margin-bottom:4px;display:flex;align-items:center;gap:6px;}
.banner-aprobacion-cuerpo{font-size:11px;color:#7a5800;line-height:1.6;}
.banner-aprobacion-timer{font-size:11px;font-weight:600;color:#b45309;margin-top:6px;}
.banner-aprobacion-pulse{display:inline-block;width:8px;height:8px;border-radius:50%;background:#f6bf26;animation:pulso-aprob 1.4s ease-in-out infinite;}
@keyframes pulso-aprob{0%,100%{opacity:1;transform:scale(1);}50%{opacity:.5;transform:scale(0.7);}}
.banner-info{flex:1;display:flex;flex-direction:column;gap:3px;}
/* log */
#log-container{background:#1c1f24;color:#d4d7db;height:520px;overflow-y:auto;padding:10px 12px;font-family:Consolas,monospace;font-size:11px;border-top:1px solid var(--border);}
#log-container::-webkit-scrollbar{width:8px;}
#log-container::-webkit-scrollbar-thumb{background:#3a3f45;border-radius:6px;}
.log-linea{margin-bottom:2px;white-space:pre-wrap;word-break:break-all;}
.log-ts{color:#8b949e}.log-ok{color:#4caf50}.log-error{color:#ff5f56}
.log-warn{color:#ffb020}.log-info{color:#6cb6ff}
.log-cliente{color:#ffd866;font-weight:600}.log-sistema{color:#9aa3ad;font-style:italic}
.log-dry-ok{color:#4caf50}.log-dry-error{color:#ff5f56}
/* selectores */
.sel-grupo{margin-bottom:14px;}
.sel-grupo-titulo{font-size:10px;font-weight:700;color:#7a8087;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px;}
button{font-family:inherit;}
h2{font-weight:600;}
/* calibración - pasos de progreso */
.cal-paso{display:flex;align-items:flex-start;gap:8px;padding:6px 0;font-size:11px;color:var(--muted);border-bottom:1px solid #f0f0f0;}
.cal-paso:last-child{border-bottom:none;}
.cal-icono{font-size:13px;min-width:18px;text-align:center;}
.cal-paso.activo{color:var(--text);font-weight:600;}
.cal-paso.ok{color:var(--success);}
.cal-paso.error{color:var(--danger);}

/* Boton wizard en header */
.wiz-btn-header{position:fixed;top:10px;right:14px;z-index:100;background:#fff;border:1px solid #d1d5db;border-radius:5px;padding:5px 11px;font-size:11px;font-weight:600;color:#4a5568;cursor:pointer;display:flex;align-items:center;gap:5px;box-shadow:0 1px 4px rgba(0,0,0,0.08);}
.wiz-btn-header:hover{background:#f6f8fa;}
.wiz-btn-header.alerta{border-color:#e53e3e;color:#e53e3e;background:#fff5f5;}
/* Badge estado SSE (conexión con el bot) */
#badge-sse{display:none;align-items:center;gap:5px;padding:3px 10px;border-radius:4px;font-size:11px;font-weight:600;border:1px solid transparent;margin-left:6px;}
#badge-sse.sse-ok{background:#eafaf1;border-color:#a8d5b5;color:#2e7d32;display:flex;}
#badge-sse.sse-perdida{background:#fff5f5;border-color:#f5c6cb;color:#c0392b;display:flex;}
#badge-sse.sse-reconectando{background:#fff8e1;border-color:#f6bf26;color:#7a5800;display:flex;}
#badge-sse .sse-dot{width:7px;height:7px;border-radius:50%;display:inline-block;}
#badge-sse.sse-ok .sse-dot{background:#2e7d32;}
#badge-sse.sse-perdida .sse-dot{background:#c0392b;}
#badge-sse.sse-reconectando .sse-dot{background:#f6bf26;animation:pulso-aprob 1.2s ease-in-out infinite;}
/* Badge estado de credenciales en header */
#badge-credenciales{display:none;align-items:center;gap:6px;padding:4px 11px;border-radius:4px;font-size:11px;font-weight:600;border:1px solid transparent;cursor:default;margin-left:8px;}
#badge-credenciales.cred-ok{background:#eafaf1;border-color:#a8d5b5;color:#2e7d32;}
#badge-credenciales.cred-err{background:#fff5f5;border-color:#f5c6cb;color:#c0392b;cursor:pointer;}
#badge-credenciales .cred-dot{width:7px;height:7px;border-radius:50%;display:inline-block;}
#badge-credenciales.cred-ok .cred-dot{background:#2e7d32;}
#badge-credenciales.cred-err .cred-dot{background:#c0392b;}

/* ── Tabla clientes tiempo real ── */
.vista-toggle{display:flex;gap:0;border:1px solid var(--border);border-radius:5px;overflow:hidden;}
.vista-toggle button{flex:1;padding:4px 10px;font-size:11px;border:none;cursor:pointer;background:#f8f9fa;color:#555;font-weight:500;}
.vista-toggle button.activa{background:#2f5d8a;color:#fff;}
#tabla-clientes-wrap{display:none;padding:0;overflow-y:auto;height:520px;}
#tabla-clientes{width:100%;border-collapse:collapse;font-size:11px;}
#tabla-clientes thead tr{background:#2f5d8a;color:#fff;position:sticky;top:0;}
#tabla-clientes th{padding:7px 10px;text-align:left;font-weight:600;font-size:10px;}
#tabla-clientes td{padding:6px 10px;border-bottom:1px solid #f0f0f0;vertical-align:middle;}
#tabla-clientes tbody tr:hover{background:#f8fafc;}
.tc-estado{font-size:10px;font-weight:600;white-space:nowrap;}
.tc-ok{color:#2e7d32;}.tc-pendiente{color:#b7570d;font-weight:600;}.tc-error{color:#b4232c;}.tc-procesando{color:#b7791f;}.tc-skip{color:#6d737a;}
.tc-detalle{font-size:10px;color:#6d737a;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
/* ── Modal resumen post-corrida ── */
.modal-overlay{display:none;position:fixed;inset:0;background:rgba(15,20,30,0.65);z-index:9000;align-items:center;justify-content:center;}
.modal-overlay.visible{display:flex;}
.modal-box{background:#fff;border-radius:10px;width:400px;max-width:94vw;box-shadow:0 8px 40px rgba(0,0,0,0.2);overflow:hidden;animation:modalEntrada .2s ease;}
@keyframes modalEntrada{from{transform:scale(.94);opacity:0}to{transform:scale(1);opacity:1}}
.modal-header{padding:16px 20px 12px;border-bottom:1px solid var(--border);}
.modal-header h3{font-size:15px;font-weight:700;margin:0;}
.modal-metricas{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;padding:18px 20px;}
.modal-metrica{text-align:center;padding:12px 8px;border-radius:7px;}
.modal-tasa{text-align:center;margin:10px 20px 0;padding:10px 14px;border-radius:7px;font-size:13px;font-weight:700;}
.modal-tasa-excelente{background:#eafaf1;color:#2e7d32;}
.modal-tasa-buena{background:#fff8e1;color:#7a5800;}
.modal-tasa-baja{background:#fdecea;color:#b4232c;}
.modal-metrica-valor{font-size:26px;font-weight:700;}
.modal-metrica-label{font-size:10px;color:#6f7680;margin-top:2px;}
.modal-ok{background:#eafaf1;}.modal-ok .modal-metrica-valor{color:#2e7d32;}
.modal-skip{background:#fef9e7;}.modal-skip .modal-metrica-valor{color:#b7791f;}
.modal-err{background:#fdecea;}.modal-err .modal-metrica-valor{color:#b4232c;}
.modal-err-clean{background:#eafaf1;}.modal-err-clean .modal-metrica-valor{color:#2e7d32;}
.modal-footer{padding:12px 20px 16px;display:flex;justify-content:flex-end;gap:8px;border-top:1px solid var(--border);}
.modal-mensaje{padding:0 20px 14px;font-size:11px;color:var(--muted);line-height:1.6;}
</style>
</head>
<body>

<!-- ── HEADER PRINCIPAL ── -->
<header>
  <h1>InvoiceFlow Bot v1.4</h1>
  <div id="badge-credenciales" title="Clic para configurar credenciales">
    <span class="cred-dot"></span>
    <span id="badge-cred-texto">Verificando...</span>
  </div>
  <div id="badge-sse" title="Estado de conexión con el bot">
    <span class="sse-dot"></span>
    <span id="badge-sse-texto"></span>
  </div>
  <span class="badge-version">v1.4.4b</span>
</header>

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


<button class="wiz-btn-header" id="btn-abrir-wizard" onclick="abrirWizard()" style="display:none">
  [cfg] Credenciales
</button>


<!-- ── MODAL RESUMEN POST-CORRIDA ── -->
<div class="modal-overlay" id="modal-resumen">
  <div class="modal-box">
    <div class="modal-header">
      <div style="font-size:10px;color:var(--muted);margin-bottom:3px" id="modal-modo-txt">CORRIDA FINALIZADA</div>
      <h3 id="modal-titulo">Procesamiento completado</h3>
    </div>
    <div class="modal-metricas">
      <div class="modal-metrica modal-ok">
        <div class="modal-metrica-valor" id="modal-ok">0</div>
        <div class="modal-metrica-label">Procesados OK</div>
      </div>
      <div class="modal-metrica modal-skip">
        <div class="modal-metrica-valor" id="modal-skip">0</div>
        <div class="modal-metrica-label">Ya facturados</div>
      </div>
      <div class="modal-metrica modal-err" id="modal-err-box">
        <div class="modal-metrica-valor" id="modal-err">0</div>
        <div class="modal-metrica-label">Con errores</div>
      </div>
    </div>
    <div id="modal-tasa" class="modal-tasa" style="display:none"></div>
    <div class="modal-mensaje" id="modal-mensaje"></div>
    <div class="modal-footer" style="justify-content:space-between">
      <button id="modal-btn-reintentar" onclick="reintentarErrores()"
        style="display:none;padding:7px 14px;font-size:12px;background:#fff3cd;border:1px solid #ffc107;border-radius:5px;cursor:pointer;font-weight:600;color:#856404">
        Reintentar errores
      </button>
      <div style="display:flex;gap:8px">
        <button class="btn btn-secundario" style="padding:7px 16px;font-size:12px"
                onclick="_exportarResumen()" title="Descargar un resumen de la corrida en texto">
          ⬇ Exportar resumen
        </button>
        <button class="btn btn-secundario" style="padding:7px 16px;font-size:12px" onclick="document.getElementById('modal-resumen').classList.remove('visible')">Ver log</button>
        <button class="btn btn-iniciar"    style="padding:7px 16px;font-size:12px" onclick="document.getElementById('modal-resumen').classList.remove('visible')">Cerrar</button>
      </div>
    </div>
  </div>
</div>

<div class="contenedor">

  <!-- ═══ COLUMNA IZQUIERDA ═══ -->
  <div>

    <!-- Banner aprobación manual Salesforce -->
    <div class="banner-aprobacion" id="banner-aprobacion">
      <div class="banner-aprobacion-titulo">
        <span class="banner-aprobacion-pulse"></span>
        Esperando aprobación del administrador
      </div>
      <div class="banner-aprobacion-cuerpo">
        Salesforce necesita que un <strong>administrador apruebe tu acceso</strong> antes de continuar.
        Avisale a tu admin — el bot retomará automáticamente cuando se apruebe.
      </div>
      <div class="banner-aprobacion-timer" id="banner-aprobacion-timer"></div>
    </div>

    <!-- Banner sesión pendiente -->
    <div class="banner-sesion oculto" id="banner-sesion">
      <span style="font-size:1.3rem">⚠️</span>
      <div class="banner-info">
        <strong>Hay una sesión anterior sin terminar</strong>
        <span id="banner-detalle" style="font-size:11px;color:var(--muted)"></span>
      </div>
      <div style="display:flex;gap:6px;flex-shrink:0">
        <button class="btn btn-reanudar" style="font-size:11px;padding:5px 10px" onclick="iniciarBot(true)">↩ Reanudar</button>
        <button class="btn btn-detener"  style="font-size:11px;padding:5px 10px" onclick="descartarSesion()">✕ Descartar</button>
      </div>
    </div>

    <!-- ── TABS ── -->
    <div class="tabs">
      <div class="tab activo" id="tab-config"     onclick="mostrarTab('config')">⚙️ Configuración</div>
      <div class="tab"        id="tab-avanzado"   onclick="mostrarTab('avanzado')">🔧 Avanzado</div>
      <div class="tab"        id="tab-selectores" onclick="mostrarTab('selectores')" style="display:none">🎯 Selectores SF</div>
      <div class="tab" id="tab-calibracion" onclick="mostrarTab('calibracion')">🛠 Calibración</div>
      <div class="tab" id="tab-historial"   onclick="mostrarTab('historial')">📋 Historial</div>
    </div>

    <!-- ══ TAB: CONFIGURACIÓN ══ -->
    <div id="panel-config" class="tab-panel activo">
      <div class="card">
        <h2>Parámetros de ejecución</h2>
        <div class="campo">
          <label>URL de Salesforce</label>
          <input type="text" id="url" placeholder="https://empresa.my.salesforce.com" value="https://">
        </div>
        <div class="campo">
          <label>Archivo Excel</label>
          <div class="campo-archivo">
            <input type="text" id="excel" placeholder="C:\ruta\clientes.xlsx">
            <button class="btn-examinar" id="btn-examinar-excel"
                    onclick="explorar('archivo','excel','btn-examinar-excel')">
               Examinar
            </button>
          </div>
          <div class="campo-hint">Ruta completa al archivo .xlsx</div>
        </div>
        <div class="campo">
          <label>Carpeta de facturas PDF</label>
          <div class="campo-archivo">
            <input type="text" id="carpeta" placeholder="C:\ruta\facturas">
            <button class="btn-examinar" id="btn-examinar-carpeta"
                    onclick="explorar('carpeta','carpeta','btn-examinar-carpeta')">
               Examinar
            </button>
          </div>
          <div class="campo-hint">Carpeta con los archivos PDF</div>
        </div>
        <div id="alertas"></div>
      </div>

      <div class="card">
        <h2>🎯 Modo de ejecución</h2>
        <div class="modo-selector">
          <div class="modo-btn activo-dryrun" id="modo-dryrun" onclick="setModo('dryrun')">
            <div>🔍</div><div style="font-weight:600;margin:3px 0">Dry-run</div>
            <div style="font-size:10px;color:#5a6a7a">Sin tocar Salesforce</div>
          </div>
          <div class="modo-btn" id="modo-real" onclick="setModo('real')">
            <div>▶️</div><div style="font-weight:600;margin:3px 0">Ejecución real</div>
            <div style="font-size:10px;color:#5a6a7a">Adjunta y marca Facturado</div>
          </div>
        </div>
        <div id="aviso-modo" style="font-size:11px;color:#0070d2;margin-bottom:10px">
          🔍 Modo simulación activo — no se modificará nada.
        </div>

        <div class="estado-chip estado-inactivo" id="chip-estado">⬤ Inactivo</div>

        <div class="metricas">
          <div class="metrica" title="Clientes procesados correctamente en esta corrida"><div class="metrica-valor" id="m-ok">0</div><div class="metrica-label">Procesados OK</div></div>
          <div class="metrica" title="Clientes que ya tenían factura antes de esta corrida — el bot los saltó sin modificar nada"><div class="metrica-valor" id="m-skip">0</div><div class="metrica-label">Ya tenían factura ↩</div></div>
          <div class="metrica" title="Clientes con error — revisarlos en el detalle al finalizar"><div class="metrica-valor" id="m-err">0</div><div class="metrica-label">Con error</div></div>
        </div>

        <div class="progreso-barra-wrap">
          <div class="progreso-barra-fill" id="barra-progreso"></div>
        </div>
        <div class="progreso-texto" id="texto-progreso">—</div>

        <div class="botones" style="margin-top:10px">
          <button class="btn btn-iniciar"  id="btn-iniciar"  onclick="iniciarBot(false)">▶ Iniciar</button>
          <button class="btn btn-pausar"   id="btn-pausar"   onclick="pausarBot()"   disabled>⏸ Pausar</button>
          <button class="btn btn-reanudar" id="btn-reanudar" onclick="reanudarBot()" disabled>↩ Reanudar</button>
          <button class="btn btn-detener"  id="btn-detener"  onclick="detenerBot()"  disabled>⏹ Detener</button>
        </div>
      </div>
    </div>

    <!-- ══ TAB: AVANZADO ══ -->
    <div id="panel-avanzado" class="tab-panel">
      <div class="card">
        <h2>🔍 Umbral de similitud de nombres</h2>
        <p style="font-size:11px;color:var(--muted);margin-bottom:10px;line-height:1.5">
          Controla qué tan parecido debe ser el nombre del Excel con el nombre del PDF para considerarlos el mismo cliente.
          Bajalo si el bot no encuentra facturas de clientes con nombre ligeramente distinto.
        </p>
        <div class="campo">
          <label>Umbral actual</label>
          <div class="umbral-wrap">
            <input type="range" id="slider-umbral" min="40" max="95" step="1" value="70"
                   oninput="actualizarUmbral(this.value)">
            <span class="umbral-badge" id="badge-umbral">70%</span>
          </div>
          <div style="display:flex;align-items:center;gap:8px;margin-top:6px">
            <div class="umbral-hint" id="hint-umbral" style="flex:1">Recomendado: 65–80%. Por debajo de 60% puede dar falsos positivos.</div>
            <button onclick="guardarUmbralEnv()" id="btn-guardar-umbral"
              style="flex-shrink:0;padding:5px 12px;background:#f0f6ff;border:1px solid #b8d0f0;border-radius:5px;font-size:11px;color:#2f5d8a;cursor:pointer;font-weight:600;white-space:nowrap">
              Guardar umbral
            </button>
          </div>
          <div id="umbral-guardado-msg" style="display:none;font-size:10px;color:#2e7d32;margin-top:3px"></div>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:6px;font-size:10px;color:var(--muted)">
          <div style="background:#fdecea;padding:6px 8px;border-radius:4px">
            <strong style="color:var(--danger)">⬇ Umbral bajo (40–60%)</strong><br>
            Encuentra más PDFs, pero puede emparejar clientes incorrectos.
          </div>
          <div style="background:#eafaf1;padding:6px 8px;border-radius:4px">
            <strong style="color:var(--success)">⬆ Umbral alto (80–95%)</strong><br>
            Más preciso, pero puede perder facturas con nombres distintos.
          </div>
        </div>
      </div>

      <div class="card" style="margin-top:10px">
        <h2>⚙️ Configuración activa</h2>
        <div id="config-info" style="font-size:11px;color:var(--muted);line-height:1.8">
          Cargando…
        </div>
      </div>
    </div>

    <!-- ══ TAB: SELECTORES ══ -->
    <div id="panel-selectores" class="tab-panel">
      <div class="card">
        <h2>🎯 Selectores de Salesforce</h2>
        <p style="font-size:11px;color:var(--muted);margin-bottom:12px;line-height:1.5">
          Editá los selectores CSS de tu instancia de Salesforce. Para encontrar el selector correcto:
          abrí Salesforce en Chrome → F12 → hacé clic en el elemento → copiá el atributo <code style="background:#f0f0f0;padding:1px 4px;border-radius:3px">name</code>, <code style="background:#f0f0f0;padding:1px 4px;border-radius:3px">title</code> o <code style="background:#f0f0f0;padding:1px 4px;border-radius:3px">placeholder</code>.
        </p>

        <div class="sel-grupo">
          <div class="sel-grupo-titulo">🔐 Login</div>
          <div class="campo"><label>Campo usuario</label><input type="text" id="sel-login-usuario" placeholder='input[name="username"]'></div>
          <div class="campo"><label>Campo contraseña</label><input type="text" id="sel-login-password" placeholder='input[name="pw"]'></div>
          <div class="campo"><label>Botón login</label><input type="text" id="sel-login-boton" placeholder='input[type="submit"]'></div>
        </div>

        <div class="sel-grupo">
          <div class="sel-grupo-titulo">🔎 Búsqueda global</div>
          <div class="campo"><label>Barra de búsqueda</label><input type="text" id="sel-busqueda-barra" placeholder='input[placeholder*="Buscar en Salesforce"]'></div>
        </div>

        <div class="sel-grupo">
          <div class="sel-grupo-titulo">📎 Archivos adjuntos</div>
          <div class="campo"><label>Sección archivos</label><textarea id="sel-adj-seccion" rows="2"></textarea></div>
          <div class="campo"><label>Item de archivo</label><input type="text" id="sel-adj-item" placeholder='a[class*="file"]'></div>
          <div class="campo"><label>Botón subir archivo</label><textarea id="sel-adj-subir" rows="2"></textarea></div>
          <div class="campo"><label>Botón confirmar adjunto</label><textarea id="sel-adj-confirmar" rows="2"></textarea></div>
        </div>

        <div class="sel-grupo">
          <div class="sel-grupo-titulo">✅ Facturado</div>
          <div class="campo"><label>Casilla Facturado</label><textarea id="sel-fact-casilla" rows="2"></textarea></div>
          <div class="campo"><label>Botón guardar</label><input type="text" id="sel-fact-guardar" placeholder='button:has-text("Guardar")'></div>
        </div>

<div id="alertas-sel"></div>

        <!-- Detección automática -->
        <div style="border-top:1px solid var(--border);padding-top:10px;margin-top:10px">
          <p style="font-size:11px;color:var(--muted);margin-bottom:8px;line-height:1.5">
            ¿No sabés los selectores de tu instancia? El bot puede detectarlos automáticamente
            iniciando sesión en Salesforce y probando atributos SLDS conocidos.
          </p>
          <button class="btn btn-secundario" id="btn-detectar-auto"
                  style="width:100%;margin-bottom:8px;font-size:12px"
                  onclick="detectarSelectoresAuto()">
            🔍 Detectar automáticamente
          </button>
          <div id="detectar-resultado" style="font-size:11px;display:none"></div>
        </div>

        <div style="display:flex;gap:8px;margin-top:4px">
          <button class="btn btn-iniciar" style="flex:1" onclick="guardarSelectores()">💾 Guardar selectores</button>
          <button class="btn btn-secundario" style="flex:1" onclick="cargarSelectores()">↺ Recargar desde archivo</button>
        </div>
      </div>
    </div>

    <!-- ══ TAB: CALIBRACIÓN ══ -->
    <div id="panel-calibracion" class="tab-panel">
      <div class="card">
        <h2>🛠 Calibración automática de selectores</h2>
        <p style="font-size:11px;color:var(--muted);margin-bottom:12px;line-height:1.6">
          El bot inicia sesión en Salesforce, abre el perfil de un cliente real
          y detecta automáticamente todos los selectores necesarios: dónde está
          la sección de archivos, el botón de carga, la casilla Facturado y el
          botón Guardar.<br><br>
          <strong>Solo necesitás hacer esto una vez.</strong> Después el bot
          funciona solo para todos los clientes.
        </p>
 
        <div style="background:#edf3fb;border-left:3px solid var(--primary);padding:10px;border-radius:4px;margin-bottom:14px;font-size:11px;line-height:1.6">
          <strong>¿Qué cliente usar?</strong> Cualquier cliente real de Salesforce
          que ya exista en el sistema. El bot <strong>no modifica ningún dato</strong>:
          solo inspecciona la pantalla para aprender cómo está organizada tu instancia.
        </div>
 
        <div class="campo">
          <label>URL de Salesforce</label>
          <input type="text" id="cal-url" placeholder="https://empresa.my.salesforce.com" value="https://">
          <div class="campo-hint">La misma URL que usás en la pestaña Configuración</div>
        </div>
 
        <div class="campo">
          <label>Número de cobro de prueba</label>
          <input type="text" id="cal-cobro"
                 placeholder="Ej: COB-2026-001"
                 style="font-family:Consolas,monospace;font-size:12px">
          <div class="campo-hint">
            Cualquier número de cobro que exista en Salesforce.
            El registro <strong>no se modifica</strong>.
          </div>
        </div>
 
        <div id="cal-alertas" style="margin-bottom:8px"></div>
 
        <button class="btn btn-iniciar" id="btn-calibrar"
                style="width:100%;font-size:13px;padding:10px"
                onclick="calibrarInstancia()">
          🔍 Iniciar calibración automática
        </button>
 
        <!-- Progreso paso a paso (visible solo durante la calibración) -->
        <div id="cal-progreso" style="display:none;margin-top:14px">
          <div style="font-size:11px;font-weight:600;color:var(--muted);margin-bottom:8px">
            Progreso de calibración:
          </div>
          <div id="cal-paso-1" class="cal-paso">
            <span class="cal-icono">⏳</span>
            <span>Iniciando sesión en Salesforce...</span>
          </div>
          <div id="cal-paso-2" class="cal-paso">
            <span class="cal-icono">⏳</span>
            <span>Detectando selectores en pantalla principal...</span>
          </div>
          <div id="cal-paso-3" class="cal-paso">
            <span class="cal-icono">⏳</span>
            <span>Navegando al perfil del cobro de prueba...</span>
          </div>
          <div id="cal-paso-4" class="cal-paso">
            <span class="cal-icono">⏳</span>
            <span>Detectando selectores de archivos y casilla Facturado...</span>
          </div>
          <div id="cal-paso-5" class="cal-paso">
            <span class="cal-icono">⏳</span>
            <span>Guardando configuración...</span>
          </div>
        </div>
 
        <!-- Resultado final -->
        <div id="cal-resultado" style="display:none;margin-top:14px"></div>
 
        <!-- Detalle colapsable de qué se detectó -->
        <div id="cal-detalle-wrap" style="display:none;margin-top:10px">
          <button class="btn-secundario"
                  style="border:1px solid var(--border);border-radius:4px;padding:4px 10px;font-size:11px;cursor:pointer;background:#fff;width:100%"
                  onclick="toggleDetalleCal()">
            Ver detalle de selectores detectados ▼
          </button>
          <div id="cal-detalle" style="display:none;margin-top:8px;font-size:11px;font-family:Consolas,monospace;background:#f6f8fa;padding:10px;border-radius:4px;overflow-x:auto;white-space:pre-wrap;word-break:break-all"></div>
        </div>
 
      </div>
 
      <div class="card" style="margin-top:10px">
        <h2>ℹ️ ¿Qué hace la calibración?</h2>
        <div style="font-size:11px;color:var(--muted);line-height:1.8">
          <div style="margin-bottom:6px">
            <strong style="color:var(--text)">Paso 1 — Inicio de sesión</strong><br>
            Abre Salesforce con tus credenciales del archivo .env.
          </div>
          <div style="margin-bottom:6px">
            <strong style="color:var(--text)">Paso 2 — Pantalla principal</strong><br>
            Detecta la barra de búsqueda global y los campos de login.
          </div>
          <div style="margin-bottom:6px">
            <strong style="color:var(--text)">Paso 3 — Perfil del cliente</strong><br>
            Abre el cobro de prueba para ver cómo está organizado el registro.
          </div>
          <div style="margin-bottom:6px">
            <strong style="color:var(--text)">Paso 4 — Selectores contextuales</strong><br>
            Detecta dónde están los archivos adjuntos, el botón de carga
            y la casilla Facturado — elementos que solo aparecen dentro del perfil.
          </div>
          <div>
            <strong style="color:var(--text)">Paso 5 — Guardado</strong><br>
            Escribe todo en <code style="background:#eee;padding:1px 4px;border-radius:3px">selectores.json</code>.
            A partir de acá el bot usa esos selectores automáticamente.
          </div>
        </div>
      </div>
    </div>

    <!-- Acceso avanzado -->
    <div style="text-align:center;padding:8px 0 2px;margin-top:4px">
      <span id="toggle-selectores-link"
            onclick="toggleSelectoresTab()"
            style="font-size:10px;color:var(--muted);cursor:pointer;text-decoration:underline;user-select:none">
        Mostrar opciones avanzadas de selectores
      </span>
    </div>

    <!-- ── PANEL HISTORIAL ── -->
    <div id="panel-historial" class="tab-panel">
      <div class="card">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px">
          <h2 style="margin:0;border:none;padding:0;font-size:13px">Historial de corridas</h2>
          <button onclick="(async()=>await cargarHistorial())()" class="btn-secundario"
            style="font-size:11px;padding:4px 12px;border:1px solid var(--border);border-radius:4px;cursor:pointer;background:#fff">
            Actualizar
          </button>
        </div>
        <div id="historial-loading" style="display:none;font-size:12px;color:var(--muted);padding:10px 0">
          Cargando historial...
        </div>
        <div id="historial-vacio" style="display:none;font-size:12px;color:var(--muted);padding:10px 0">
          No hay corridas registradas todavia. El historial se actualiza al finalizar cada corrida.
        </div>
        <table id="historial-tabla" style="width:100%;border-collapse:collapse;font-size:11px;display:none">
          <thead>
            <tr style="background:#2f5d8a;color:#fff">
              <th style="padding:7px 10px;text-align:left;font-weight:600">Fecha y hora</th>
              <th style="padding:7px 10px;text-align:left;font-weight:600">Modo</th>
              <th style="padding:7px 10px;text-align:center;font-weight:600">OK</th>
              <th style="padding:7px 10px;text-align:center;font-weight:600">Errores</th>
              <th style="padding:7px 10px;text-align:left;font-weight:600">Log</th>
            </tr>
          </thead>
          <tbody id="historial-body"></tbody>
        </table>
        <div style="font-size:10px;color:var(--muted);margin-top:10px">
          Mostrando las ultimas 20 corridas. Los logs se rotan automaticamente cada
          <span id="historial-retention">30</span> dias.
        </div>
      </div>
    </div>

  </div><!-- fin columna izquierda -->

  <!-- ═══ COLUMNA DERECHA — LOG ═══ -->
  <div>
    <div class="card" style="padding:0;overflow:hidden">
      <div style="padding:10px 16px 8px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;gap:8px">
        <h2 style="margin:0;border:none;padding:0;font-size:13px">📋 Log en tiempo real</h2>
        <div style="display:flex;align-items:center;gap:8px">
          <div class="vista-toggle">
            <button id="btn-vista-log"    class="activa" onclick="setVista('log')">Log</button>
            <button id="btn-vista-tabla"  onclick="setVista('tabla')">Clientes</button>
          </div>
          <button onclick="limpiarLog()" class="btn-secundario"
                  style="border:1px solid var(--border);border-radius:4px;padding:3px 10px;font-size:11px;cursor:pointer;background:#fff;color:#555">
            Limpiar
          </button>
          <!-- #12: log download group -->
          <div id="btn-descargar-log" style="display:none;position:relative">
            <button id="btn-log-toggle"
              onclick="document.getElementById('log-menu').style.display=document.getElementById('log-menu').style.display==='block'?'none':'block'"
              style="border:1px solid var(--border);border-radius:4px;padding:3px 10px;font-size:11px;cursor:pointer;background:#fff;color:#555">
              ⬇ Log ▾
            </button>
            <div id="log-menu" style="display:none;position:absolute;top:100%;left:0;z-index:200;background:#fff;border:1px solid var(--border);border-radius:5px;box-shadow:0 4px 12px rgba(0,0,0,0.1);min-width:160px;margin-top:3px">
              <a href="/descargar_log" download
                 onclick="document.getElementById('log-menu').style.display='none'"
                 style="display:block;padding:8px 14px;font-size:11px;color:#333;text-decoration:none;border-bottom:1px solid #f0f0f0">
                📄 Descargar log (.txt)
              </a>
              <a href="#" onclick="event.preventDefault();_descargarLogCSV();document.getElementById('log-menu').style.display='none'"
                 style="display:block;padding:8px 14px;font-size:11px;color:#333;text-decoration:none">
                📊 Descargar log (.csv) — abrir en Excel
              </a>
            </div>
          </div>
        </div>
      </div>
      <div id="log-container"></div>
      <div id="tabla-clientes-wrap">
        <table id="tabla-clientes">
          <thead>
            <tr>
              <th>Cobro</th>
              <th>Cliente</th>
              <th>Estado</th>
              <th>Detalle</th>
            </tr>
          </thead>
          <tbody id="tabla-clientes-body"></tbody>
        </table>
      </div>
    </div>
  </div>

</div><!-- fin contenedor -->

<script>
// ─── Estado global ───────────────────────────────────────────────────────────
let modo       = 'dryrun';
let procesados = 0;
let total      = 0;
let evtSource  = null;
let umbral     = 70;

// ─── Tabs ────────────────────────────────────────────────────────────────────
async function mostrarTab(nombre) {
  ['config','avanzado','selectores','calibracion','historial'].forEach(t => {
    const tabEl   = document.getElementById('tab-'   + t);
    const panelEl = document.getElementById('panel-' + t);
    if (tabEl)   tabEl.classList.toggle('activo',   t === nombre);
    if (panelEl) panelEl.classList.toggle('activo', t === nombre);
  });
  if (nombre === 'avanzado')   cargarConfigInfo();
  if (nombre === 'selectores') cargarSelectores();
  if (nombre === 'historial')  await cargarHistorial();
}

// ─── Umbral ──────────────────────────────────────────────────────────────────
function actualizarUmbral(v) {
  umbral = parseInt(v);
  document.getElementById('badge-umbral').textContent = v + '%';
  const hint = document.getElementById('hint-umbral');
  if (umbral < 60)      hint.textContent = 'Umbral muy bajo — riesgo de falsos positivos.';
  else if (umbral > 85) hint.textContent = 'Umbral muy alto — puede perder facturas con nombres ligeramente distintos.';
  else                  hint.textContent = 'Recomendado: 65–80%. Ajusta si el bot no encuentra facturas o empareja mal.';
}

// ── M3: Reintentar errores de la última corrida ───────────────────────────────
async function reintentarErrores() {
  document.getElementById('modal-resumen').classList.remove('visible');
  try {
    const r = await fetch('/errores_ultima_corrida');
    const d = await r.json();
    if (!d.ok || !d.errores.length) {
      agregarLogLinea('warn', 'No hay errores de la última corrida para reintentar.');
      return;
    }
    // Marcar en el banner que es un reintento parcial
    const banner = document.getElementById('banner-sesion');
    const detalle = document.getElementById('banner-detalle');
    if (banner && detalle) {
      banner.classList.remove('oculto');
      detalle.textContent = `Reintento de ${d.errores.length} cliente(s) con error.`;
    }
    agregarLogLinea('sistema', `Reintentando ${d.errores.length} cliente(s) con error...`);
    // Lanzar corrida real — el Excel ya tiene marcados los OK anteriores,
    // por lo que cargar_clientes() solo levantará los pendientes (que son los errores)
    await iniciarBot(false);
  } catch(e) {
    agregarLogLinea('error', 'Error al consultar errores: ' + e.message);
  }
}

async function guardarUmbralEnv() {
  const btn = document.getElementById('btn-guardar-umbral');
  const msg = document.getElementById('umbral-guardado-msg');
  btn.textContent = 'Guardando...';
  btn.disabled = true;
  msg.style.display = 'none';
  try {
    const r = await fetch('/guardar_umbral', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ umbral })
    });
    const d = await r.json();
    if (d.ok) {
      msg.textContent = 'Umbral de ' + umbral + '% guardado en .env. Se aplicara en la proxima corrida.';
      msg.style.color = '#2e7d32';
    } else {
      msg.textContent = 'Error al guardar: ' + (d.error || 'desconocido');
      msg.style.color = '#b4232c';
    }
    msg.style.display = 'block';
    setTimeout(() => { msg.style.display = 'none'; }, 4000);
  } catch(e) {
    msg.textContent = 'Error de red al guardar el umbral.';
    msg.style.color = '#b4232c';
    msg.style.display = 'block';
  } finally {
    btn.textContent = 'Guardar umbral';
    btn.disabled = false;
  }
}

// ─── Historial de corridas (tab Historial) ────────────────────────────────────
async function cargarHistorial() {
  const loading = document.getElementById('historial-loading');
  const vacio   = document.getElementById('historial-vacio');
  const tabla   = document.getElementById('historial-tabla');
  const tbody   = document.getElementById('historial-body');

  loading.style.display = 'block';
  vacio.style.display   = 'none';
  tabla.style.display   = 'none';

  try {
    const r = await fetch('/historial');
    const d = await r.json();
    loading.style.display = 'none';

    if (!d.ok || !d.corridas.length) {
      vacio.style.display = 'block';
      return;
    }

    // Actualizar días de retención
    const retEl = document.getElementById('historial-retention');
    if (retEl && d.retention_dias) retEl.textContent = d.retention_dias;

    tbody.innerHTML = '';
    d.corridas.forEach((c, i) => {
      const tr = document.createElement('tr');
      tr.style.background = i % 2 === 0 ? '#fff' : '#f8fafc';
      const colorErr = c.errores > 0 ? '#b4232c' : '#2e7d32';
      const colorOk  = c.ok      > 0 ? '#2e7d32' : '#6d737a';
      tr.innerHTML =
        `<td style="padding:7px 10px;font-size:11px">${escHTML(c.fecha)}</td>` +
        `<td style="padding:7px 10px">` +
          `<span style="font-size:10px;font-weight:600;padding:2px 8px;border-radius:10px;` +
          `background:${c.modo==='Real'?'#fdecea':'#e8f4ff'};` +
          `color:${c.modo==='Real'?'#c0392b':'#2f5d8a'}">${escHTML(c.modo)}</span>` +
        `</td>` +
        `<td style="padding:7px 10px;text-align:center;font-weight:700;color:${colorOk}">${c.ok}</td>` +
        `<td style="padding:7px 10px;text-align:center;font-weight:700;color:${colorErr}">${c.errores}</td>` +
        `<td style="padding:7px 10px;font-size:10px;color:#6d737a">${escHTML(c.archivo)}</td>`;
      tbody.appendChild(tr);
    });

    tabla.style.display = 'table';
  } catch(e) {
    loading.style.display = 'none';
    vacio.style.display   = 'block';
    vacio.textContent = 'Error al cargar el historial.';
  }
}

// ─── Config info (tab Avanzado) ───────────────────────────────────────────────
async function cargarConfigInfo() {
  try {
    const r = await fetch('/config');
    const d = await r.json();
    document.getElementById('config-info').innerHTML = `
      <table style="width:100%;border-collapse:collapse">
        <tr><td style="padding:3px 0;color:#555;width:55%">Umbral de similitud</td><td><strong>${d.umbral_similitud}%</strong> (panel: ${umbral}%)</td></tr>
        <tr><td style="padding:3px 0;color:#555">Timeout carga SF</td><td>${d.timeout_carga}s</td></tr>
        <tr><td style="padding:3px 0;color:#555">Reintentos máximos</td><td>${d.retry_max_intentos}</td></tr>
        <tr><td style="padding:3px 0;color:#555">Circuit breaker</td><td>${d.circuit_breaker_umbral} fallos</td></tr>
        <tr><td style="padding:3px 0;color:#555">Navegador visible</td><td>${d.navegador_visible ? 'Sí' : 'No'}</td></tr>
        <tr><td style="padding:3px 0;color:#555">Archivo selectores</td><td style="word-break:break-all;font-size:10px">${d.selectores_path}</td></tr>
      </table>`;
    // Sincronizar slider con el valor de config si no fue modificado por el usuario
    if (umbral === 70 && d.umbral_similitud !== 70) {
      umbral = d.umbral_similitud;
      document.getElementById('slider-umbral').value = umbral;
      document.getElementById('badge-umbral').textContent = umbral + '%';
    }
  } catch(e) {
    document.getElementById('config-info').textContent = 'Error al cargar configuración.';
  }
}

// ─── Selectores ───────────────────────────────────────────────────────────────
async function cargarSelectores() {
  try {
    const r = await fetch('/config');
    const d = await r.json();
    const s = d.selectores || {};
    const login = s.login || {};
    const bus   = s.busqueda || {};
    const adj   = s.archivos_adjuntos || {};
    const fac   = s.facturado || {};
    document.getElementById('sel-login-usuario').value    = login.campo_usuario  || '';
    document.getElementById('sel-login-password').value   = login.campo_password || '';
    document.getElementById('sel-login-boton').value      = login.boton_login    || '';
    document.getElementById('sel-busqueda-barra').value   = bus.barra_global     || '';
    document.getElementById('sel-adj-seccion').value      = adj.seccion_archivos || '';
    document.getElementById('sel-adj-item').value         = adj.item_archivo     || '';
    document.getElementById('sel-adj-subir').value        = adj.boton_subir      || '';
    document.getElementById('sel-adj-confirmar').value    = adj.boton_confirmar  || '';
    document.getElementById('sel-fact-casilla').value     = fac.casilla          || '';
    document.getElementById('sel-fact-guardar').value     = fac.boton_guardar    || '';
  } catch(e) {
    mostrarAlertaSel('Error al cargar selectores desde el servidor.', false);
  }
}

async function guardarSelectores() {
  const datos = {
    login: {
      campo_usuario:  document.getElementById('sel-login-usuario').value.trim(),
      campo_password: document.getElementById('sel-login-password').value.trim(),
      boton_login:    document.getElementById('sel-login-boton').value.trim(),
    },
    busqueda: {
      barra_global: document.getElementById('sel-busqueda-barra').value.trim(),
    },
    archivos_adjuntos: {
      seccion_archivos: document.getElementById('sel-adj-seccion').value.trim(),
      item_archivo:     document.getElementById('sel-adj-item').value.trim(),
      boton_subir:      document.getElementById('sel-adj-subir').value.trim(),
      boton_confirmar:  document.getElementById('sel-adj-confirmar').value.trim(),
    },
    facturado: {
      casilla:       document.getElementById('sel-fact-casilla').value.trim(),
      boton_guardar: document.getElementById('sel-fact-guardar').value.trim(),
    }
  };

  // Validación básica: ningún campo vacío
  const vacios = [];
  if (!datos.login.campo_usuario)               vacios.push('Campo usuario');
  if (!datos.login.campo_password)              vacios.push('Campo contraseña');
  if (!datos.login.boton_login)                 vacios.push('Botón login');
  if (!datos.busqueda.barra_global)             vacios.push('Barra de búsqueda');
  if (!datos.archivos_adjuntos.seccion_archivos) vacios.push('Sección archivos');
  if (!datos.archivos_adjuntos.boton_subir)     vacios.push('Botón subir archivo');
  if (!datos.facturado.casilla)                 vacios.push('Casilla Facturado');

  if (vacios.length > 0) {
    mostrarAlertaSel('Campos vacíos: ' + vacios.join(', '), false);
    return;
  }

  try {
    const r = await fetch('/selectores', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(datos)
    });
    const d = await r.json();
    if (d.ok) mostrarAlertaSel('✅ Selectores guardados correctamente en selectores.json', true);
    else      mostrarAlertaSel('❌ Error al guardar: ' + (d.error || 'desconocido'), false);
  } catch(e) {
    mostrarAlertaSel('Error de red al guardar selectores.', false);
  }
}

function mostrarAlertaSel(msg, ok) {
  const div = document.getElementById('alertas-sel');
  div.innerHTML = `<div class="${ok ? 'alerta-ok' : 'alerta'}">${escHTML(msg)}</div>`;
  setTimeout(() => { div.innerHTML = ''; }, 4000);
}

// ─── Detección automática de selectores ──────────────────────────────────────
async function detectarSelectoresAuto() {
  const btn = document.getElementById('btn-detectar-auto');
  const res = document.getElementById('detectar-resultado');
  const url = document.getElementById('url').value.trim();

  btn.disabled = true;
  btn.textContent = '⏳ Detectando… (puede tardar 30–60 s)';
  res.style.display = 'none';

  try {
    const r = await fetch('/detectar_selectores', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url })
    });
    const d = await r.json();

    if (d.ok) {
      res.style.display = 'block';
      res.innerHTML = `<div class="alerta-ok">
        ✅ <strong>${d.detectados}/${d.total}</strong> selectores detectados.
        Los detectados fueron guardados en selectores.json.
      </div>`;
      // Recargar los selectores en el formulario para reflejar lo detectado
      await cargarSelectores();
    } else {
      res.style.display = 'block';
      res.innerHTML = `<div class="alerta">❌ ${escHTML(d.error || 'Error desconocido')}</div>`;
    }
  } catch(e) {
    res.style.display = 'block';
    res.innerHTML = `<div class="alerta">❌ Error de red al detectar selectores.</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = '🔍 Detectar automáticamente';
  }
}

// ─── Explorador de archivos/carpetas ─────────────────────────────────────────
async function explorar(tipo, campoId, btnId) {
  const btn = document.getElementById(btnId);
  btn.classList.add('cargando');
  btn.disabled = true;
  const textoOriginal = btn.textContent;
  btn.textContent = '⏳ Abriendo…';
  try {
    const r = await fetch('/explorar/' + tipo, { method: 'POST' });
    const d = await r.json();
    if (d.ok && d.ruta) {
      document.getElementById(campoId).value = d.ruta;
    } else if (d.error) {
      agregarAlerta(d.error);
    }
    // si d.cancelado === true el usuario cerró el diálogo — no hacer nada
  } catch(e) {
    agregarAlerta('No se pudo abrir el explorador de archivos.');
  } finally {
    btn.textContent = textoOriginal;
    btn.classList.remove('cargando');
    btn.disabled = false;
  }
}

// ─── Modo ─────────────────────────────────────────────────────────────────────
function setModo(m) {
  modo = m;
  document.getElementById('modo-dryrun').className = 'modo-btn' + (m==='dryrun' ? ' activo-dryrun' : '');
  document.getElementById('modo-real').className   = 'modo-btn' + (m==='real'   ? ' activo-real'   : '');
  const av = document.getElementById('aviso-modo');
  if (m === 'dryrun') { av.style.color='#0070d2'; av.textContent='🔍 Modo simulación activo — no se modificará nada.'; }
  else                { av.style.color='#e74c3c'; av.textContent='⚠️ Modo real activo — se adjuntarán facturas en Salesforce.'; }
}

// ─── Iniciar / controlar bot ──────────────────────────────────────────────────
async function iniciarBot(reanudar = false) {
  const url     = document.getElementById('url').value.trim();
  const excel   = document.getElementById('excel').value.trim();
  const carpeta = document.getElementById('carpeta').value.trim();
  limpiarAlertas();

  // FIX-5a: confirm ANTES del fetch al servidor.
  // Antes el confirm venía DESPUÉS de /iniciar, lo que causaba que el botón
  // quedara aparentemente inactivo (sin feedback visual) durante el fetch,
  // y en caso de cancelar el confirm el servidor ya había arrancado el proceso.
  if (!reanudar) {
    if (modo === 'real') {
      if (!confirm(
        '⚠️  Modo REAL — vas a procesar facturas en Salesforce.\n\n' +
        'El bot va a adjuntar PDFs y marcar clientes como Facturado.\n' +
        'Esta acción modifica datos reales.\n\n' +
        '¿Confirmar ejecución real?'
      )) return;
    } else {
      if (!confirm(
        'ℹ️  Modo SIMULACIÓN (Dry-Run)\n\n' +
        'El bot va a revisar los clientes pero NO va a adjuntar ' +
        'nada ni modificar Salesforce.\n' +
        'Es ideal para verificar antes de la corrida real.\n\n' +
        '¿Iniciar simulación?'
      )) return;
    }
  }

  // FIX-5b: feedback visual mientras el servidor valida.
  // Sin esto el panel parece no responder durante el fetch de validación.
  const btnIni = document.getElementById('btn-iniciar');
  const textoOriginal = btnIni.textContent;
  btnIni.disabled = true;
  btnIni.textContent = '⏳ Validando...';

  let data;
  try {
    const resp = await fetch('/iniciar', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ url, excel, carpeta, modo, reanudar, umbral })
    });
    data = await resp.json();
  } catch(e) {
    agregarAlerta('❌ Error de conexión con el servidor. Verificá que el panel esté activo.');
    btnIni.disabled = false;
    btnIni.textContent = textoOriginal;
    return;
  }

  if (!data.ok) {
    data.errores.forEach(e => agregarAlerta(e));
    // Restaurar botón si la validación falló (no hay corrida activa)
    btnIni.disabled = false;
    btnIni.textContent = textoOriginal;
    return;
  }

  procesados = 0; total = 0;
  resetMetricas(); limpiarLog(); iniciarSSE();
  setEstado('corriendo');  // setEstado se encarga de deshabilitar el botón correctamente
  document.getElementById('banner-sesion').classList.add('oculto');
  // 9: pedir permiso de notificación del sistema (solo la primera vez)
  _pedirPermisoNotificacion();
}

async function pausarBot()   { await fetch('/pausar',   {method:'POST'}); setEstado('pausado'); }
async function reanudarBot() { await fetch('/reanudar', {method:'POST'}); setEstado('corriendo'); }
async function detenerBot() {
  if (!confirm('¿Detener el bot?')) return;
  await fetch('/detener', {method:'POST'}); setEstado('inactivo');
}
async function descartarSesion() {
  await fetch('/descartar_sesion', {method:'POST'});
  document.getElementById('banner-sesion').classList.add('oculto');
  agregarLogLinea('sistema', 'Sesión anterior descartada.');
}

// ─── SSE ──────────────────────────────────────────────────────────────────────
// ── M5: SSE con reconexión automática y badge de estado ──────────────────────
let _sseReintentos  = 0;
let _sseMaxReintentos = 5;
let _sseTimerReconex = null;

function _setBadgeSSE(estado) {
  // estado: 'ok' | 'perdida' | 'reconectando' | 'oculto'
  const badge = document.getElementById('badge-sse');
  const texto = document.getElementById('badge-sse-texto');
  if (!badge || !texto) return;
  badge.className = 'sse-' + estado;
  const labels = {
    ok:           'Conectado',
    perdida:      'Conexión perdida',
    reconectando: 'Reconectando...',
  };
  texto.textContent = labels[estado] || '';
  badge.style.display = estado === 'oculto' ? 'none' : 'flex';
}

function iniciarSSE() {
  if (evtSource) { evtSource.close(); evtSource = null; }
  evtSource = new EventSource('/eventos');

  evtSource.onopen = () => {
    _sseReintentos = 0;
    if (_sseTimerReconex) { clearTimeout(_sseTimerReconex); _sseTimerReconex = null; }
    _setBadgeSSE('ok');
  };

  evtSource.onmessage = async (e) => {
    _sseReintentos = 0;
    // FIX-8: procesarEvento es async — awaiteamos para que errores internos
    // no queden como promesas flotantes (unhandled rejection silencioso).
    try { await procesarEvento(JSON.parse(e.data)); }
    catch(err) { console.error('[SSE] Error procesando evento:', err); }
  };

  evtSource.onerror = () => {
    evtSource.close();
    evtSource = null;

    // Si el bot ya no está corriendo (estado inactivo), ocultar badge — es normal.
    const chip = document.getElementById('chip-estado');
    if (chip && chip.className.includes('estado-inactivo')) {
      _setBadgeSSE('oculto');
      return;
    }

    _sseReintentos++;
    if (_sseReintentos > _sseMaxReintentos) {
      _setBadgeSSE('perdida');
      agregarLogLinea('warn',
        '⚠️  Se perdió la conexión con el bot después de varios intentos. ' +
        'Verificá que la aplicación siga abierta.'
      );
      return;
    }

    // Reconexión progresiva: 2s, 4s, 6s...
    const espera = _sseReintentos * 2000;
    _setBadgeSSE('reconectando');
    agregarLogLinea('warn',
      `⚠️  Conexión interrumpida — reconectando en ${espera/1000}s (intento ${_sseReintentos}/${_sseMaxReintentos})...`
    );
    _sseTimerReconex = setTimeout(iniciarSSE, espera);
  };
}

async function procesarEvento(ev) {  // FIX-8: async requerido por await cargarHistorial() interno
  const {tipo, mensaje} = ev;
  const mOk  = document.getElementById('m-ok');
  const mErr = document.getElementById('m-err');
  switch(tipo) {
    case 'LOG':
      agregarLogLinea(mensaje.includes('WARNING')?'warn':mensaje.includes('ERROR')?'error':'info', mensaje); break;
    case 'CLIENTE':
      agregarLogLinea('cliente', '── ' + mensaje);
      // Tabla: agregar fila con estado "Procesando"
      if (typeof mensaje === 'string') {
        const partes = mensaje.split(' | ');
        _tablaAgregarFila(partes[0] || mensaje, partes[1] || '');
      } break;
    case 'CLIENTE_FIN':
      // Resultado final de un cliente (real o dry-run)
      if (typeof mensaje === 'object') {
        const estadoMap = {
          'OK':               { txt: 'OK',                cls: 'tc-ok'         },
          'YA_FACTURADO':     { txt: 'Ya facturado',      cls: 'tc-skip'       },
          'DRY_OK':           { txt: 'PDF encontrado',    cls: 'tc-ok'         },
          'DRY_ERROR':        { txt: 'PDF no encontrado', cls: 'tc-error'      },
          'PENDIENTE_MANUAL': { txt: '⚠ Marcar manual',  cls: 'tc-pendiente'  },
          'ERROR_ID':         { txt: 'No encontrado',     cls: 'tc-error'      },
          'ERROR_CIRCUITBREAKER': { txt: 'Error crítico', cls: 'tc-error'      },
        };
        const e   = estadoMap[mensaje.estado] || { txt: mensaje.estado, cls: 'tc-error' };
        const det = mensaje.detalle || mensaje.pdf || '';
        _tablaActualizarFila(mensaje.cobro || '', e.txt, det, e.cls);
      } break;
    case 'DRY_OK':
      agregarLogLinea('dry-ok', mensaje);
      mOk.textContent = parseInt(mOk.textContent)+1;
      procesados++; actualizarProgreso(); break;
    case 'DRY_ERROR':
      agregarLogLinea('dry-error', mensaje);
      mErr.textContent = parseInt(mErr.textContent)+1;
      procesados++; actualizarProgreso(); break;
    case 'PROGRESO':
      // Progreso real desde bot_runner — reemplaza el parsing de strings de log
      if (typeof mensaje === 'object') {
        total      = mensaje.total      || total;
        procesados = mensaje.procesados || 0;
        actualizarProgreso(mensaje.dur_seg || 0);  // ETA: pasa duración del último cliente
      } break;
    case 'INFO':
      agregarLogLinea('info', mensaje);
      if (mensaje.includes('Clientes a procesar:'))
        total = parseInt(mensaje.split(':')[1].trim()) || 0;
      break;
    case 'WARN':
      // Advertencia operativa — el bot sigue corriendo pero hay algo a tener en cuenta
      agregarLogLinea('warn', '⚠️  ' + (typeof mensaje === 'object' ? JSON.stringify(mensaje) : mensaje));
      break;
    case 'INICIO':
      // Confirmación de arranque — mostrar en el log con estilo informativo
      agregarLogLinea('sistema', '▶ ' + (typeof mensaje === 'object' ? JSON.stringify(mensaje) : mensaje));
      // Mostrar botón de descarga del log cuando arranca la corrida
      { const bl = document.getElementById('btn-descargar-log'); if (bl) bl.style.display = 'inline-flex'; }
      break;
    case 'APROBACION_PENDIENTE':
      // Salesforce requiere aprobación manual del admin — no reintentar, esperar
      _mostrarBannerAprobacion(mensaje);
      agregarLogLinea('warn', '⏳ ' + (typeof mensaje === 'object' ? mensaje.mensaje : mensaje));
      setEstado('aprobacion'); break;
    case 'APROBACION_RESUELTA':
      // El admin aprobó — ocultar banner y continuar normalmente
      _ocultarBannerAprobacion();
      agregarLogLinea('sistema', '✅ ' + (typeof mensaje === 'object' ? mensaje.mensaje : mensaje));
      setEstado('corriendo'); break;
    case 'PAUSA':   agregarLogLinea('warn', mensaje); setEstado('pausado');   break;
    case 'REANUDAR':agregarLogLinea('info', mensaje); setEstado('corriendo'); break;
    case 'DETENIDO':agregarLogLinea('warn', mensaje); setEstado('inactivo'); _ocultarBannerAprobacion(); _setBadgeSSE('oculto'); break;
    case 'ERROR':   agregarLogLinea('error','❌ ' + mensaje); break;
    case 'FIN': {
      // U3: distinguir corrida completada vs detenida manualmente
      const motivo  = (typeof mensaje === 'object' && mensaje.motivo) ? mensaje.motivo : 'completado';
      const textoFin = (typeof mensaje === 'object' && mensaje.mensaje) ? mensaje.mensaje : mensaje;
      const esDetenido = motivo === 'detenido';
      const esError    = motivo === 'error';

      agregarLogLinea('sistema', '─'.repeat(46));
      agregarLogLinea(esDetenido ? 'warn' : esError ? 'error' : 'sistema', textoFin);

      // Actualizar el modal de resumen según el motivo
      const modalTitulo   = document.getElementById('modal-titulo');
      const modalModoTxt  = document.getElementById('modal-modo-txt');
      if (modalTitulo) {
        if (esDetenido)    { modalTitulo.textContent  = 'Corrida detenida'; modalModoTxt.textContent = 'DETENIDA MANUALMENTE'; }
        else if (esError)  { modalTitulo.textContent  = 'Corrida interrumpida'; modalModoTxt.textContent = 'FINALIZADA POR ERROR'; }
        else               { modalTitulo.textContent  = 'Procesamiento completado'; modalModoTxt.textContent = 'CORRIDA FINALIZADA'; }
      }

      setEstado('inactivo');
      _ocultarBannerAprobacion();
      _setBadgeSSE('oculto');
      // Refrescar historial si el tab está activo
      if (document.getElementById('panel-historial').classList.contains('activo'))
        await cargarHistorial();
      // 9: Notificación del sistema al terminar
      {
        const ok   = parseInt(document.getElementById('m-ok')?.textContent  || '0');
        const err  = parseInt(document.getElementById('m-err')?.textContent || '0');
        const tit  = esDetenido ? 'InvoiceFlow Bot — Detenido'
                   : esError    ? 'InvoiceFlow Bot — Error'
                   :              'InvoiceFlow Bot — Corrida completa';
        const cuerpo = esDetenido ? 'La corrida fue detenida manualmente.'
                     : esError    ? 'La corrida finalizó con un error. Revisá el log.'
                     : err > 0    ? `${ok} procesados, ${err} con error. Revisá el resumen.`
                     :              `${ok} clientes procesados correctamente. ✅`;
        _notificarFin(tit, cuerpo);
      }
      if(evtSource) evtSource.close(); break;
    } // end case FIN
    case 'TOTALES':
      if (typeof mensaje==='object') {
        const ok   = mensaje.ok || 0;
        const skip = mensaje.ya_facturado || 0;
        const err  = mensaje.errores || 0;
        mOk.textContent  = ok;
        document.getElementById('m-skip').textContent = skip;
        mErr.textContent = err;
        // Mostrar modal de resumen
        document.getElementById('modal-ok').textContent   = ok;
        document.getElementById('modal-skip').textContent = skip;
        document.getElementById('modal-err').textContent  = err;
        const errBox = document.getElementById('modal-err-box');
        errBox.className = 'modal-metrica ' + (err === 0 ? 'modal-err-clean' : 'modal-err');
        const esDry = modo === 'dryrun';
        document.getElementById('modal-modo-txt').textContent = esDry ? 'DRY-RUN FINALIZADO' : 'CORRIDA REAL FINALIZADA';
        document.getElementById('modal-titulo').textContent   = esDry ? 'Análisis de matching completado' : 'Procesamiento completado';
        let msg = '';
        if (esDry) {
          msg = err === 0
            ? `Todos los clientes tienen su PDF listo. Podés pasar a modo <strong>Real</strong> con confianza.`
            : `<strong>${err}</strong> cliente(s) no tienen PDF o tienen un problema de matching. Revisá el log para ver cuáles y por qué.`;
        } else {
          // 4: instrucción específica para PENDIENTE_MANUAL
          const pendientes = (window._ultErrores||[]).filter(e=>e.estado==='PENDIENTE_MANUAL').length;
          const errReales  = err - pendientes;
          let partes = [];
          if (err === 0 && pendientes === 0) {
            partes.push('Corrida sin errores. El Excel fue actualizado y las facturas fueron adjuntadas en Salesforce.');
          } else {
            if (pendientes > 0)
              partes.push(`<strong>${pendientes}</strong> cliente(s) OK en Salesforce pero <strong>no marcados en el Excel</strong> — abrílo y marcalos manualmente en la columna 'Enviadas'.`);
            if (errReales > 0)
              partes.push(`<strong>${errReales}</strong> cliente(s) con error — revisá el log para ver el detalle.`);
          }
          msg = partes.join('<br>');
        }
        document.getElementById('modal-mensaje').innerHTML = msg;
        // 8: Tasa de éxito — solo en corrida real con al menos 1 cliente
        const tasaEl = document.getElementById('modal-tasa');
        if (tasaEl && !esDry) {
          const total_c = ok + skip + err;
          if (total_c > 0) {
            const tasa = Math.round((ok / total_c) * 100);
            const cls  = tasa === 100 ? 'modal-tasa-excelente'
                       : tasa >= 80  ? 'modal-tasa-buena'
                       :               'modal-tasa-baja';
            const emoji = tasa === 100 ? '🎉' : tasa >= 80 ? '⚠️' : '❌';
            tasaEl.className    = `modal-tasa ${cls}`;
            tasaEl.textContent  = `${emoji}  Tasa de éxito: ${tasa}% — ${ok} de ${total_c} clientes procesados`;
            tasaEl.style.display = 'block';
          } else {
            tasaEl.style.display = 'none';
          }
        } else if (tasaEl) {
          tasaEl.style.display = 'none';
        }
        // M3: botón reintentar solo en corrida real con errores
        const btnReintentar = document.getElementById('modal-btn-reintentar');
        btnReintentar.style.display = (!esDry && err > 0) ? 'inline-block' : 'none';
        // 4: cargar errores para instrucción PENDIENTE_MANUAL en modal
        window._ultErrores = [];
        if (err > 0) fetch('/errores_ultima_corrida')
          .then(r => r.json()).then(d => { if (d.ok) window._ultErrores = d.errores || []; })
          .catch(() => {});
        if (!esDry && err > 0) btnReintentar.textContent = `Reintentar ${err} error${err>1?'s':''}`;
        document.getElementById('modal-resumen').classList.add('visible');
      } break;
  }
}

// ─── Estado visual ────────────────────────────────────────────────────────────
function setEstado(estado) {
  const chip = document.getElementById('chip-estado');
  const cfgs = {
    inactivo:   {txt:'⬤ Inactivo',          cls:'estado-inactivo'},
    corriendo:  {txt:'⬤ Corriendo',          cls:'estado-corriendo'},
    pausado:    {txt:'⏸ Pausado',            cls:'estado-pausado'},
    aprobacion: {txt:'⏳ Esperando admin...',cls:'estado-pausado'},
  };
  const cfg = cfgs[estado] || cfgs.inactivo;
  chip.textContent = cfg.txt;
  chip.className   = 'estado-chip ' + cfg.cls;
  document.getElementById('btn-iniciar').disabled  = estado !== 'inactivo';
  document.getElementById('btn-pausar').disabled   = estado !== 'corriendo';
  document.getElementById('btn-reanudar').disabled = estado !== 'pausado';
  // En aprobacion: deshabilitar Detener para evitar interrumpir la espera
  document.getElementById('btn-detener').disabled  = estado === 'inactivo' || estado === 'aprobacion';
}

// ─── Banner de aprobación manual ─────────────────────────────────────────────
let _timerAprobacion = null;
let _inicioAprobacion = null;

function _mostrarBannerAprobacion(datos) {
  const banner = document.getElementById('banner-aprobacion');
  if (!banner) return;
  _inicioAprobacion = Date.now();
  banner.classList.add('visible');
  // Iniciar contador de tiempo de espera
  if (_timerAprobacion) clearInterval(_timerAprobacion);
  _timerAprobacion = setInterval(() => {
    const seg = Math.floor((Date.now() - _inicioAprobacion) / 1000);
    const min = Math.floor(seg / 60);
    const s   = seg % 60;
    const timerEl = document.getElementById('banner-aprobacion-timer');
    if (timerEl) timerEl.textContent = `Esperando hace ${min > 0 ? min + ' min ' : ''}${s} seg`;
  }, 1000);
}

function _ocultarBannerAprobacion() {
  const banner = document.getElementById('banner-aprobacion');
  if (banner) banner.classList.remove('visible');
  if (_timerAprobacion) { clearInterval(_timerAprobacion); _timerAprobacion = null; }
  _inicioAprobacion = null;
}

// ─── Log ──────────────────────────────────────────────────────────────────────
function agregarLogLinea(tipo, texto) {
  const cont = document.getElementById('log-container');
  const div  = document.createElement('div');
  div.className = 'log-linea';
  const ahora = new Date().toLocaleTimeString('es-AR',{hour12:false});
  const clases = {ok:'log-ok',error:'log-error',warn:'log-warn',info:'log-info',
    'dry-ok':'log-dry-ok','dry-error':'log-dry-error',cliente:'log-cliente',sistema:'log-sistema'};
  div.innerHTML = `<span class="log-ts">${ahora}</span> <span class="${clases[tipo]||'log-info'}">${escHTML(texto)}</span>`;
  cont.appendChild(div);
  cont.scrollTop = cont.scrollHeight;
}
const escHTML = t => String(t).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
function limpiarLog() {
  _ocultarBannerAprobacion();
  _duraciones = [];  // ETA: resetear velocidades al iniciar nueva corrida
  const btnLog = document.getElementById('btn-descargar-log');
  if (btnLog) btnLog.style.display = 'none';  // ocultar al limpiar
  document.getElementById('log-container').innerHTML = '';
  document.getElementById('tabla-clientes-body').innerHTML = '';
}

// ── Vista Log / Tabla ─────────────────────────────────────────────────────────
let _vistaActual = 'log';
function setVista(v) {
  _vistaActual = v;
  document.getElementById('log-container').style.display       = v === 'log'   ? 'block' : 'none';
  document.getElementById('tabla-clientes-wrap').style.display = v === 'tabla' ? 'block' : 'none';
  document.getElementById('btn-vista-log').classList.toggle('activa',   v === 'log');
  document.getElementById('btn-vista-tabla').classList.toggle('activa', v === 'tabla');
}

// ── Tabla de clientes en tiempo real ─────────────────────────────────────────
function _tablaAgregarFila(cobro, nombre) {
  const tbody = document.getElementById('tabla-clientes-body');
  const id    = 'tc-' + cobro.replace(/[^a-zA-Z0-9]/g, '_');
  if (document.getElementById(id)) return; // ya existe
  const tr = document.createElement('tr');
  tr.id = id;
  tr.innerHTML =
    `<td style="font-family:monospace;font-size:10px">${escHTML(cobro)}</td>` +
    `<td>${escHTML(nombre)}</td>` +
    `<td class="tc-estado tc-procesando" id="tc-est-${cobro.replace(/[^a-zA-Z0-9]/g,'_')}">Procesando...</td>` +
    `<td class="tc-detalle"              id="tc-det-${cobro.replace(/[^a-zA-Z0-9]/g,'_')}">—</td>`;
  tbody.appendChild(tr);
  tr.scrollIntoView({ block: 'nearest' });
}

function _tablaActualizarFila(cobro, estadoTxt, detalle, cls) {
  const id    = cobro.replace(/[^a-zA-Z0-9]/g, '_');
  const tdEst = document.getElementById('tc-est-' + id);
  const tdDet = document.getElementById('tc-det-' + id);
  if (tdEst) { tdEst.textContent = estadoTxt; tdEst.className = 'tc-estado ' + cls; }
  if (tdDet) { tdDet.textContent = detalle; tdDet.title = detalle; }
}


function limpiarAlertas() { document.getElementById('alertas').innerHTML = ''; }
function agregarAlerta(msg) {
  const div = document.createElement('div');
  div.className='alerta'; div.textContent=msg;
  document.getElementById('alertas').appendChild(div);
}
function resetMetricas() {
  ['m-ok','m-skip','m-err'].forEach(id=>document.getElementById(id).textContent='0');
  document.getElementById('barra-progreso').style.width='0%';
  document.getElementById('texto-progreso').textContent='—';
}
// ── ETA: variables de velocidad ──────────────────────────────────────────────
let _duraciones = [];          // últimas N duraciones de clientes (segundos)
const _ETA_VENTANA = 5;        // promedio sobre los últimos 5 clientes

function actualizarProgreso(durSeg) {
  if (!total) return;
  const pct = Math.round((procesados / total) * 100);
  document.getElementById('barra-progreso').style.width = pct + '%';

  // Acumular duración del último cliente para ETA
  if (durSeg && durSeg > 0) {
    _duraciones.push(durSeg);
    if (_duraciones.length > _ETA_VENTANA) _duraciones.shift();
  }

  // Calcular ETA
  let etaTxt = '';
  const restantes = total - procesados;
  if (_duraciones.length >= 2 && restantes > 0) {
    const promSeg = _duraciones.reduce((a, b) => a + b, 0) / _duraciones.length;
    const totalSeg = Math.round(promSeg * restantes);
    if (totalSeg < 60)       etaTxt = ` — faltan ~${totalSeg}s`;
    else if (totalSeg < 3600) etaTxt = ` — faltan ~${Math.ceil(totalSeg/60)} min`;
    else                      etaTxt = ` — faltan ~${(totalSeg/3600).toFixed(1)} h`;
  }

  document.getElementById('texto-progreso').textContent =
    `${procesados} de ${total} (${pct}%)${etaTxt}`;
}

// ── Badge de estado de credenciales en header ────────────────────────────────
async function _actualizarBadgeCredenciales() {
  const badge = document.getElementById('badge-credenciales');
  const texto = document.getElementById('badge-cred-texto');
  if (!badge || !texto) return;
  try {
    const r = await fetch('/estado_credenciales');
    const d = await r.json();
    badge.style.display = 'flex';
    if (d.completas) {
      badge.className = 'cred-ok';
      texto.textContent = 'Listo';
      badge.onclick = null;
      badge.title   = 'Credenciales de Salesforce configuradas correctamente';
      // Habilitar btn-iniciar si estaba bloqueado por credenciales
      const btnIni = document.getElementById('btn-iniciar');
      if (btnIni && btnIni._bloqCred) {
        btnIni.disabled = false;
        btnIni._bloqCred = false;
        btnIni.title = '';
      }
    } else {
      badge.className = 'cred-err';
      texto.textContent = 'Credenciales no configuradas';
      badge.onclick = () => abrirWizard();
      badge.title   = 'Clic para configurar credenciales de Salesforce';
      // Deshabilitar btn-iniciar con tooltip explicativo
      const btnIni = document.getElementById('btn-iniciar');
      if (btnIni && !btnIni.disabled) {
        btnIni.disabled = true;
        btnIni._bloqCred = true;
        btnIni.title = 'Configura las credenciales de Salesforce antes de iniciar';
      }
    }
  } catch(e) {
    // Si /estado_credenciales no responde (dev sin wizard), no bloquear
    if (badge) badge.style.display = 'none';
  }
}

// ── 9: Notificación del sistema al finalizar corrida ─────────────────────────
let _notifPermiso = 'default';  // 'granted' | 'denied' | 'default'

async function _pedirPermisoNotificacion() {
  if (!('Notification' in window)) return;
  if (Notification.permission === 'granted') { _notifPermiso = 'granted'; return; }
  if (Notification.permission === 'denied')  { _notifPermiso = 'denied';  return; }
  const res = await Notification.requestPermission();
  _notifPermiso = res;
}

function _notificarFin(titulo, cuerpo) {
  // Capa 1: Notification API del browser (muestra notificación del sistema)
  if (_notifPermiso === 'granted') {
    try {
      const n = new Notification(titulo, {
        body: cuerpo,
        icon: '/static/icon.png',  // si no existe, se ignora silenciosamente
        tag:  'invoiceflow-fin',   // reemplaza notificación anterior si hay una
      });
      setTimeout(() => n.close(), 8000);  // auto-cerrar a los 8s
    } catch (_) {}
  }
  // Capa 2: Sonido de fallback (funciona aunque Notification esté denegado)
  try {
    const ctx  = new (window.AudioContext || window.webkitAudioContext)();
    const osc  = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain); gain.connect(ctx.destination);
    osc.type = 'sine'; osc.frequency.value = 880;
    gain.gain.setValueAtTime(0.3, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.6);
    osc.start(ctx.currentTime);
    osc.stop(ctx.currentTime + 0.6);
  } catch (_) {}
}

// ── #12: Exportar log como CSV para abrir en Excel ─────────────────────────
function _descargarLogCSV() {
  const cont   = document.getElementById('log-container');
  if (!cont) return;
  const lineas = cont.querySelectorAll('.log-linea');
  if (!lineas.length) return;

  // Cabecera CSV
  const filas = ['Hora,Tipo,Mensaje'];

  lineas.forEach(div => {
    // Extraer hora del span .log-ts
    const tsEl  = div.querySelector('.log-ts');
    const hora  = tsEl ? tsEl.textContent.trim() : '';

    // Extraer tipo desde la clase CSS del span de mensaje
    const msgEl = div.querySelector('span:not(.log-ts)');
    let tipo = 'info';
    if (msgEl) {
      const cls = msgEl.className || '';
      if (cls.includes('log-ok'))      tipo = 'OK';
      else if (cls.includes('log-error'))  tipo = 'ERROR';
      else if (cls.includes('log-warn'))   tipo = 'WARN';
      else if (cls.includes('log-cliente')) tipo = 'CLIENTE';
      else if (cls.includes('log-sistema')) tipo = 'SISTEMA';
      else if (cls.includes('dry'))         tipo = 'DRYRUN';
    }

    // Texto limpio (sin HTML)
    const texto = (msgEl ? msgEl.textContent : div.textContent)
      .replace(hora, '').trim()
      .replace(/"/g, '""'    // escapar comillas para CSV
      );

    filas.push(`"${hora}","${tipo}","${texto}"`);
  });

  // BOM para que Excel reconozca UTF-8 correctamente
  const bom  = '\uFEFF';
  const csv  = bom + filas.join('\n');
  const blob = new Blob([csv], {type: 'text/csv;charset=utf-8'});
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  const fecha = new Date().toISOString().slice(0,10);
  a.href     = url;
  a.download = `invoiceflow_log_${fecha}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// Cerrar el dropdown de log si se hace click fuera
document.addEventListener('click', (e) => {
  const menu   = document.getElementById('log-menu');
  const toggle = document.getElementById('btn-log-toggle');
  if (menu && toggle && !toggle.contains(e.target) && !menu.contains(e.target)) {
    menu.style.display = 'none';
  }
});

// ── 10: Exportar resumen de corrida ─────────────────────────────────────────
function _exportarResumen() {
  const ok   = document.getElementById('modal-ok')?.textContent   || '0';
  const skip = document.getElementById('modal-skip')?.textContent || '0';
  const err  = document.getElementById('modal-err')?.textContent  || '0';
  const tasa = document.getElementById('modal-tasa')?.textContent || '';
  const modo_txt = document.getElementById('modal-modo-txt')?.textContent || '';
  const titulo   = document.getElementById('modal-titulo')?.textContent   || '';
  const msg      = document.getElementById('modal-mensaje')?.innerText    || '';
  const ahora    = new Date().toLocaleString('es-AR', {hour12:false});

  // Tabla de errores desde window._ultErrores
  let errLines = '';
  if (window._ultErrores && window._ultErrores.length > 0) {
    errLines = `\n── Detalle de errores ──────────────────────────────────\n`;
    window._ultErrores.forEach((e, i) => {
      errLines += `  ${i+1}. [${e.estado}] ${e.cobro || ''} — ${e.nombre || ''}
`;
      if (e.detalle) errLines += `      ${e.detalle}
`;
    });
  }

  const contenido = [
    '═══════════════════════════════════════════════════════',
    '  InvoiceFlow Bot — Resumen de corrida',
    '═══════════════════════════════════════════════════════',
    `  Fecha:  ${ahora}`,
    `  Modo:   ${modo_txt}`,
    `  Estado: ${titulo}`,
    '───────────────────────────────────────────────────────',
    `  ✅ Procesados OK:    ${ok}`,
    `  ↩  Ya tenían factura: ${skip}`,
    `  ❌ Con error:        ${err}`,
    tasa ? `  ${tasa}` : '',
    '───────────────────────────────────────────────────────',
    msg ? `  ${msg.split('\n').join('\n  ')}` : '',
    errLines,
    '═══════════════════════════════════════════════════════',
    '  Generado por InvoiceFlow Bot',
    '═══════════════════════════════════════════════════════',
  ].filter(l => l !== '').join('\n');

  // Descargar como .txt
  const blob = new Blob([contenido], {type: 'text/plain;charset=utf-8'});
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  const fecha = new Date().toISOString().slice(0,10);
  a.href     = url;
  a.download = `invoiceflow_resumen_${fecha}.txt`;
  a.click();
  URL.revokeObjectURL(url);
}

// ─── Inicio ───────────────────────────────────────────────────────────────────
window.onload = async () => {
  setEstado('inactivo');

  // Cargar config inicial para sincronizar slider con valor de .env
  try {
    const r = await fetch('/config');
    const d = await r.json();
    umbral = d.umbral_similitud || 70;
    document.getElementById('slider-umbral').value = umbral;
    document.getElementById('badge-umbral').textContent = umbral + '%';
  } catch(e) {}

  // Sesión pendiente (tiene prioridad sobre última config)
  const resp = await fetch('/sesion_pendiente');
  const data = await resp.json();
  if (data.pendiente) {
    document.getElementById('banner-sesion').classList.remove('oculto');
    document.getElementById('banner-detalle').textContent =
      `Iniciada ${data.inicio} — ${data.procesados}/${data.total} procesados, ${data.pendientes} pendientes`;
    if (data.url)     document.getElementById('url').value     = data.url;
    if (data.excel)   document.getElementById('excel').value   = data.excel;
    if (data.carpeta) document.getElementById('carpeta').value = data.carpeta;
  } else {
    // Sin sesión pendiente: cargar última configuración usada
    try {
      const rc = await fetch('/ultima_config');
      const dc = await rc.json();
      if (dc.ok) {
        if (dc.url)     { document.getElementById('url').value     = dc.url;     document.getElementById('cal-url').value = dc.url; }
        if (dc.excel)   document.getElementById('excel').value   = dc.excel;
        if (dc.carpeta) document.getElementById('carpeta').value = dc.carpeta;
      }
    } catch(e) {}
  }

  // Sincronizar URL entre tab Config y tab Calibración (en tiempo real)
  document.getElementById('url').addEventListener('input', e => {
    document.getElementById('cal-url').value = e.target.value;
  });
  document.getElementById('cal-url').addEventListener('input', e => {
    document.getElementById('url').value = e.target.value;
  });

  // Verificar estado de credenciales y mostrar badge en header
  await _actualizarBadgeCredenciales();

  // FIX-6: _verificarCredencialesWizard() integrada directamente en el onload
  // principal. Antes se hacía con un segundo window.onload que sobrescribía al
  // primero usando el patrón "guardar y envolver" (_wizOrigOnload), que es frágil:
  // cualquier error de parseo JS entre los dos bloques hacía que el wizard nunca
  // se inicializara. Al tenerlo aquí el orden de ejecución es explícito y seguro.
  await _verificarCredencialesWizard();
};

// ─── Calibración guiada ────────────────────────────────────────────────────────
let _calDetalleVisible = false;
let _selectoresVisible = false;

function toggleSelectoresTab() {
  _selectoresVisible = !_selectoresVisible;
  const tab  = document.getElementById('tab-selectores');
  const link = document.getElementById('toggle-selectores-link');
  tab.style.display  = _selectoresVisible ? 'block' : 'none';
  link.textContent   = _selectoresVisible ? 'Ocultar opciones avanzadas' : 'Mostrar opciones avanzadas de selectores';
  if (_selectoresVisible) {
    mostrarTab('selectores');
    // Advertencia antes de editar
    setTimeout(() => {
      if (!window._selWarningShown) {
        window._selWarningShown = true;
        alert('Atención: esta sección es para configuración avanzada.\n\nModificar los selectores incorrectamente puede hacer que el bot no funcione.\n\nSi usaste la Calibración automática, no es necesario cambiar nada aquí.');
      }
    }, 100);
  }
}
 
function toggleDetalleCal() {
  _calDetalleVisible = !_calDetalleVisible;
  document.getElementById('cal-detalle').style.display = _calDetalleVisible ? 'block' : 'none';
}
 
function _calPaso(n, estado) {
  // estado: 'activo' | 'ok' | 'error' | '' (reset)
  const el = document.getElementById('cal-paso-' + n);
  if (!el) return;
  el.className = 'cal-paso' + (estado ? ' ' + estado : '');
  const icono = el.querySelector('.cal-icono');
  if (estado === 'ok')     icono.textContent = '✅';
  else if (estado === 'error') icono.textContent = '❌';
  else if (estado === 'activo') icono.textContent = '⏳';
  else icono.textContent = '⏳';
}
 
function _calResetPasos() {
  for (let i = 1; i <= 5; i++) _calPaso(i, '');
}
 
function mostrarAlertaCal(msg, ok) {
  const div = document.getElementById('cal-alertas');
  div.innerHTML = `<div class="${ok ? 'alerta-ok' : 'alerta'}">${escHTML(msg)}</div>`;
  if (ok) setTimeout(() => { div.innerHTML = ''; }, 5000);
}
 
function calibrarInstancia() {
  const url   = document.getElementById('cal-url').value.trim();
  const cobro = document.getElementById('cal-cobro').value.trim();
 
  if (!url || url === 'https://') {
    mostrarAlertaCal('Ingresa la URL de Salesforce antes de calibrar.', false);
    return;
  }
  if (!cobro) {
    mostrarAlertaCal('Ingresa un numero de cobro de prueba.', false);
    return;
  }
 
  const btn = document.getElementById('btn-calibrar');
  btn.disabled = true;
  btn.textContent = 'Calibrando... (puede tardar 1-2 min)';
  document.getElementById('cal-alertas').innerHTML = '';
  document.getElementById('cal-resultado').style.display = 'none';
  document.getElementById('cal-detalle-wrap').style.display = 'none';
  document.getElementById('cal-progreso').style.display = 'block';
  _calResetPasos();
 
  // Conectar al endpoint SSE en lugar de fetch síncrono + setTimeout
  const params  = new URLSearchParams({ url, cobro });
  const evtCal  = new EventSource('/calibrar_stream?' + params.toString());
 
  evtCal.onmessage = function(e) {
    let msg;
    try { msg = JSON.parse(e.data); } catch(_) { return; }
 
    // Progreso real de paso — sin timers estimados
    if (msg.paso !== undefined && msg.estado !== undefined) {
      _calPaso(msg.paso, msg.estado);
      return;
    }
 
    // Resultado final
    if (msg.fin) {
      evtCal.close();
      btn.disabled = false;
      btn.textContent = 'Iniciar calibracion automatica';
 
      const resDiv = document.getElementById('cal-resultado');
      resDiv.style.display = 'block';
 
      if (msg.ok) {
        resDiv.innerHTML = `
          <div class="alerta-ok" style="font-size:12px;padding:12px">
            <div style="font-size:14px;font-weight:700;margin-bottom:6px">
              Calibracion completada
            </div>
            <div style="margin-bottom:4px">
              <strong>${msg.detectados}</strong> de <strong>${msg.total}</strong> selectores detectados correctamente.
            </div>
            ${msg.detectados < msg.total
              ? `<div style="color:#856404;margin-top:6px">
                  ${msg.total - msg.detectados} selector(es) no se detectaron.
                  El bot usara los valores por defecto para esos elementos.
                 </div>`
              : `<div style="margin-top:4px;color:#2e7d32">
                  Todos los selectores detectados. El bot esta listo.
                 </div>`
            }
          </div>`;
 
        if (msg.detalle && Object.keys(msg.detalle).length > 0) {
          document.getElementById('cal-detalle-wrap').style.display = 'block';
          const detalleTxt = Object.entries(msg.detalle)
            .map(([k, v]) => `${v ? 'OK' : 'X '} ${k.padEnd(40)} ${v || '--'}`)
            .join('\n');
          document.getElementById('cal-detalle').textContent = detalleTxt;
        }
 
        // Recargar selectores en tab Selectores SF
        cargarSelectores();
 
      } else {
        resDiv.innerHTML = `
          <div class="alerta" style="font-size:12px;padding:12px">
            <div style="font-size:13px;font-weight:700;margin-bottom:6px">
              Calibracion fallida
            </div>
            <div>${escHTML(msg.error || 'Error desconocido')}</div>
            <div style="margin-top:8px;color:#666">
              ${(msg.error || '').includes('No se encontro el cobro')
                ? 'Verifica que el numero de cobro existe en Salesforce y que las credenciales son correctas.'
                : 'Revisa los logs para mas detalle o intenta con otro numero de cobro.'}
            </div>
          </div>`;
      }
    }
  };
 
  evtCal.onerror = function() {
    evtCal.close();
    btn.disabled = false;
    btn.textContent = 'Iniciar calibracion automatica';
    _calPaso(1, 'error');
    document.getElementById('cal-resultado').style.display = 'block';
    document.getElementById('cal-resultado').innerHTML =
      `<div class="alerta">Error de conexion con el servidor durante la calibracion.</div>`;
  };
}
 


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

  btn.textContent = 'Verificando... (puede tardar 30-45 seg)';
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
      estado.style.background = '#eafaf1';
      estado.style.color = '#2e7d32';
      estado.textContent = 'Conexion verificada correctamente.';
      _wizSFVerificado = true;
      // Sincronizar URL con el panel principal
      const urlPanel = document.getElementById('url');
      const urlCal   = document.getElementById('cal-url');
      if (urlPanel) urlPanel.value = url;
      if (urlCal)   urlCal.value   = url;
    } else {
      estado.style.background = '#fdecea';
      estado.style.color = '#b4232c';
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

// FIX-6: el segundo window.onload fue eliminado. _verificarCredencialesWizard()
// se llama directamente desde el onload principal (arriba), evitando el patrón
// frágil de "guardar y envolver" que podía dejar el wizard sin inicializar.
// --- FIN WIZARD --------------------------------------------------------------

</script>
</body>
</html>'''


# =============================================================================
# RUTAS DEL SERVIDOR
# =============================================================================


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
    Timeout: 45s. No guarda nada — solo verifica.
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
        from salesforce_bot import SalesforceBot as _SF
        import logging as _lg
        _logger = _lg.getLogger("verificar_sf")
        bot = _SF(logger=_logger, salesforce_url=url)
        # Sobreescribir credenciales para esta verificacion puntual
        bot._sf_username = user
        bot._sf_password = pwd
        try:
            bot.iniciar()
            return {"ok": True}
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
        result = future.result(timeout=45)
    except _cf.TimeoutError:
        result = {"ok": False, "error": "Tiempo de espera agotado (45s). Verificar URL y conexion."}
    except Exception as exc:
        result = {"ok": False, "error": str(exc)[:200]}
    finally:
        executor.shutdown(wait=False)

    return jsonify(result)

@app.route("/")
def index():
    return render_template_string(PANEL_HTML)


@app.route("/config")
def config_info() -> Any:
    """Devuelve la configuración activa + selectores para el panel."""
    sel = cargar_selectores()
    return jsonify({
        "umbral_similitud":       settings.umbral_similitud,
        "timeout_carga":          settings.timeout_carga,
        "retry_max_intentos":     settings.retry_max_intentos,
        "circuit_breaker_umbral": settings.circuit_breaker_umbral,
        "navegador_visible":      settings.navegador_visible,
        "selectores_path":        settings.selectores_path,
        "selectores":             sel,
    })


@app.route("/selectores", methods=["POST"])
def guardar_selectores_endpoint() -> Any:
    """Guarda los selectores editados en el panel al archivo JSON."""
    datos: Dict = request.json or {}
    ok = guardar_selectores(datos)
    if ok:
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "No se pudo escribir selectores.json"}), 500


@app.route("/descargar_log")
def descargar_log() -> Any:
    """
    Sirve el archivo de log de la corrida actual para descarga directa.
    Si no hay corrida activa o el archivo no existe, retorna 404 con mensaje claro.
    """
    from flask import send_file as _send_file
    from pathlib import Path as _Path
    ruta = getattr(runner, "ruta_log", None)
    if not ruta or not _Path(ruta).exists():
        return jsonify({"ok": False, "error": "No hay log disponible para esta corrida."}), 404
    return _send_file(ruta, as_attachment=True, download_name=_Path(ruta).name)


@app.route("/historial")
def historial_corridas() -> Any:
    """
    Lista las últimas 20 corridas leyendo los archivos de log existentes.
    No requiere DB adicional — la info ya está en los archivos de la carpeta logs/.
    Retorna: {ok, corridas: [{fecha, modo, ok, errores, archivo}], retention_dias}
    """
    import re as _re
    from pathlib import Path as _Path

    logs_dir = _Path(settings.carpeta_logs)
    corridas = []

    if logs_dir.exists():
        archivos = sorted(logs_dir.glob("log_*.txt"), reverse=True)[:20]
        for f in archivos:
            es_dry = "_dryrun" in f.name
            m = _re.match(r"log_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})", f.name)
            if m:
                fecha = f"{m.group(1)}-{m.group(2)}-{m.group(3)} {m.group(4)}:{m.group(5)}"
            else:
                fecha = f.stem

            ok_count  = 0
            err_count = 0
            try:
                import re as _re_log
                # Patrón: "— [COBRO] Nombre → ESTADO"
                # Captura solo líneas de registrar() — excluye diagnósticos del matcher,
                # healer y otros warnings que no corresponden a resultados de clientes.
                _pat = _re_log.compile(r'— \[.+?\] .+ → ([A-Z][A-Z_]+)')
                for linea in f.read_text(encoding="utf-8", errors="ignore").splitlines():
                    m = _pat.search(linea)
                    if not m:
                        continue
                    estado = m.group(1)
                    if estado == "OK":
                        ok_count += 1
                    elif "WARNING" in linea and estado != "YA_FACTURADO":
                        err_count += 1
            except Exception:
                pass

            corridas.append({
                "fecha":   fecha,
                "modo":    "Dry-run" if es_dry else "Real",
                "ok":      ok_count,
                "errores": err_count,
                "archivo": f.name,
            })

    return jsonify({
        "ok":            True,
        "corridas":      corridas,
        "retention_dias": settings.log_retention_dias,
    })


@app.route("/errores_ultima_corrida")
def errores_ultima_corrida() -> Any:
    """Retorna los errores de la última corrida real para el botón Reintentar."""
    errores = getattr(runner, "ultimos_errores", [])
    return jsonify({"ok": True, "errores": errores, "total": len(errores)})


@app.route("/guardar_umbral", methods=["POST"])
def guardar_umbral() -> Any:
    """Persiste el umbral de similitud en el archivo .env."""
    from pathlib import Path as _Path
    data  = request.json or {}
    nuevo = int(data.get("umbral", 70))
    if not 40 <= nuevo <= 95:
        return jsonify({"ok": False, "error": "Umbral fuera de rango permitido (40-95)."})
    env_path = _Path(".env")
    try:
        if env_path.exists():
            lineas = env_path.read_text(encoding="utf-8").splitlines()
        else:
            lineas = []
        nuevas = []
        encontrado = False
        for l in lineas:
            if l.startswith("UMBRAL_SIMILITUD="):
                nuevas.append(f"UMBRAL_SIMILITUD={nuevo}")
                encontrado = True
            else:
                nuevas.append(l)
        if not encontrado:
            nuevas.append(f"UMBRAL_SIMILITUD={nuevo}")
        env_path.write_text("\n".join(nuevas) + "\n", encoding="utf-8")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ── lock para serializar detecciones (solo una a la vez) ─────────────────────
_explorar_lock = threading.Lock()


@app.route("/detectar_selectores", methods=["POST"])
def detectar_selectores() -> Any:
    """
    Inicia una exploración automática de selectores en la instancia de Salesforce.
    Instancia un SalesforceBot temporal: iniciar() → explorar_instancia() → cerrar().
    No puede correr simultáneamente con el bot principal ni consigo mismo.

    Body JSON opcional: {"url": "https://empresa.my.salesforce.com"}
    Si no se pasa url, usa settings.salesforce_url.

    Returns JSON:
        {"ok": true,  "detectados": N, "total": M, "detalle": {...}}
        {"ok": false, "error": "..."}
    """
    if runner.corriendo:
        return jsonify({
            "ok":    False,
            "error": "El bot está en ejecución. Detené el bot antes de detectar selectores.",
        })

    if not _explorar_lock.acquire(blocking=False):
        return jsonify({
            "ok":    False,
            "error": "Ya hay una detección en curso. Esperá a que termine.",
        })

    url: str = (
        (request.json or {}).get("url", "").strip()
        or settings.salesforce_url
    )

    def _ejecutar() -> dict:
        from salesforce_bot import SalesforceBot as _SalesforceBot
        import logging as _logging
        logger = _logging.getLogger("explorar_instancia")
        bot = _SalesforceBot(logger=logger, salesforce_url=url)
        try:
            bot.iniciar()
            return bot.explorar_instancia()
        finally:
            bot.cerrar()

    executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="explorar"
    )
    future = executor.submit(_ejecutar)

    try:
        resultados: Dict = future.result(timeout=120)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:300]})
    finally:
        _explorar_lock.release()
        executor.shutdown(wait=False)

    total_claves = len(resultados)
    detectados   = sum(1 for v in resultados.values() if v is not None)
    return jsonify({
        "ok":         True,
        "detectados": detectados,
        "total":      total_claves,
        "detalle":    resultados,
    })

# ── lock para serializar calibraciones (solo una a la vez) ───────────────────
_calibrar_lock = threading.Lock()


@app.route("/calibrar_stream")
def calibrar_stream() -> Any:
    """
    Calibración guiada de selectores via SSE — progreso real por paso.
    Sustituye al endpoint síncrono /calibrar (que usaba timeouts simulados en JS).

    Query params: url=... cobro=...
    Emite eventos: {"paso": N, "estado": "activo"|"ok"|"error"}
                   {"fin": true, "ok": bool, "detectados": N, "total": N,
                    "detalle": {...}, "error": ""}
    """
    if runner.corriendo:
        def _err():
            yield f"data: {json.dumps({'fin': True, 'ok': False, 'error': 'El bot está en ejecución. Detené el bot antes de calibrar.'})}\n\n"
        return Response(_err(), mimetype="text/event-stream")

    if not _calibrar_lock.acquire(blocking=False):
        def _err2():
            yield f"data: {json.dumps({'fin': True, 'ok': False, 'error': 'Ya hay una calibración en curso.'})}\n\n"
        return Response(_err2(), mimetype="text/event-stream")

    url   = request.args.get("url",   "").strip()
    cobro = request.args.get("cobro", "").strip()

    if not url or not cobro:
        _calibrar_lock.release()
        def _err3():
            yield f"data: {json.dumps({'fin': True, 'ok': False, 'error': 'URL y cobro son requeridos.'})}\n\n"
        return Response(_err3(), mimetype="text/event-stream")

    cola_cal: queue.Queue = queue.Queue()

    def on_paso(n: int, estado: str) -> None:
        cola_cal.put({"paso": n, "estado": estado})

    def _ejecutar() -> None:
        from salesforce_bot import SalesforceBot as _SF
        import logging as _lg
        logger = _lg.getLogger("calibracion")
        bot = _SF(logger=logger, salesforce_url=url)
        try:
            bot.iniciar()
            resultado = bot.calibrar_instancia(cobro, on_paso=on_paso)
        except Exception as exc:
            resultado = {"ok": False, "detectados": 0, "total": 0,
                         "detalle": {}, "error": str(exc)[:300]}
        finally:
            try:
                bot.cerrar()
            except Exception:
                pass
        cola_cal.put({"fin": True, **resultado})

    threading.Thread(target=_ejecutar, daemon=True, name="calibrar_stream").start()

    def generar():
        try:
            while True:
                try:
                    msg = cola_cal.get(timeout=200)
                except queue.Empty:
                    yield "data: {}\n\n"  # keepalive
                    continue
                yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
                if msg.get("fin"):
                    break
        finally:
            _calibrar_lock.release()

    return Response(
        generar(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )



@app.route("/iniciar", methods=["POST"])
def iniciar() -> Any:
    data     = request.json or {}
    url      = data.get("url",      "").strip()
    excel    = data.get("excel",    "").strip()
    carpeta  = data.get("carpeta",  "").strip()
    es_dry   = data.get("modo",     "dryrun") == "dryrun"
    reanudar = data.get("reanudar", False)
    umbral   = int(data.get("umbral", UMBRAL_SIMILITUD))

    ok, errores = validar_todo(url, excel, carpeta)
    if not ok:
        return jsonify({"ok": False, "errores": errores})

    # Persistir última configuración usada
    import json as _json
    from pathlib import Path as _Path
    try:
        _Path("ultima_config.json").write_text(
            _json.dumps({"url": url, "excel": excel, "carpeta": carpeta}, ensure_ascii=False),
            encoding="utf-8"
        )
    except Exception:
        pass

    runner.iniciar(url, excel, carpeta, es_dry, reanudar, umbral)
    return jsonify({"ok": True})


@app.route("/ultima_config")
def ultima_config() -> Any:
    """Retorna la última configuración guardada (url, excel, carpeta)."""
    import json as _json
    from pathlib import Path as _Path
    try:
        data = _json.loads(_Path("ultima_config.json").read_text(encoding="utf-8"))
        return jsonify({"ok": True, **data})
    except Exception:
        return jsonify({"ok": False})



@app.route("/pausar", methods=["POST"])
def pausar() -> Any:
    runner.pausar()
    return jsonify({"ok": True})


@app.route("/reanudar", methods=["POST"])
def reanudar() -> Any:
    runner.reanudar()
    return jsonify({"ok": True})


@app.route("/detener", methods=["POST"])
def detener() -> Any:
    runner.detener()
    return jsonify({"ok": True})


@app.route("/descartar_sesion", methods=["POST"])
def descartar_sesion() -> Any:
    limpiar_sesion()
    return jsonify({"ok": True})


@app.route("/limpiar_sesion_sf", methods=["POST"])
def limpiar_sesion_sf() -> Any:
    """A2: Invalida el storage_state guardado de Playwright.
    Llamado por el wizard al guardar nuevas credenciales.
    Fuerza login completo en la próxima corrida.
    """
    from salesforce_bot import SalesforceBot as _SF
    _SF.limpiar_sesion_guardada()
    return jsonify({"ok": True})


@app.route("/sesion_pendiente")
def sesion_pendiente() -> Any:
    if hay_sesion_pendiente():
        sesion          = cargar_sesion() or {}
        procesados_dict = sesion.get("procesados", {})
        total           = sesion.get("total", 0)
        n_proc          = len(procesados_dict)
        return jsonify({
            "pendiente":  True,
            "inicio":     sesion.get("inicio", ""),
            "total":      total,
            "procesados": n_proc,
            "pendientes": total - n_proc,
            "url":        sesion.get("url", ""),
            "excel":      sesion.get("excel_path", ""),
            "carpeta":    sesion.get("carpeta_pdfs", ""),
        })
    return jsonify({"pendiente": False})


@app.route("/eventos")
def eventos() -> Any:
    """SSE — stream de logs en tiempo real al navegador."""
    def generar() -> Generator:
        import time as _time

        # FIX-2: esperar a que _ejecutar() haya reemplazado self.cola por la del
        # nuevo loop (señalizado por _cola_lista.set()). Sin esto, /eventos puede
        # capturar la cola vieja (creada en __init__, sin loop activo) y nunca
        # recibir ningún evento aunque el bot esté corriendo correctamente.
        # Timeout de 10s: si el hilo no arranca en ese tiempo, algo falló.
        cola_lista: Optional[threading.Event] = getattr(runner, "_cola_lista", None)
        if cola_lista is not None:
            cola_lista.wait(timeout=10)

        # Capturar referencias estables DESPUÉS de que la cola fue reemplazada.
        # Leer runner.cola/runner._loop en cada iteración del while sería incorrecto
        # porque una nueva llamada a iniciar() podría reemplazarlas en carrera.
        cola_actual = runner.cola
        loop_actual = runner._loop

        while True:
            if loop_actual is None or not loop_actual.is_running():
                _time.sleep(1)
                yield 'data: {"tipo":"PING"}\n\n'
                # Refrescar referencias si el loop cambió (nueva corrida)
                nuevo_loop = runner._loop
                if nuevo_loop is not None and nuevo_loop is not loop_actual:
                    cola_actual = runner.cola
                    loop_actual = nuevo_loop
                continue
            try:
                future = asyncio.run_coroutine_threadsafe(
                    _get_con_timeout(cola_actual, timeout=30), loop_actual
                )
                evento = future.result(timeout=32)
                if evento is None:
                    yield 'data: {"tipo":"PING"}\n\n'
                    continue
                yield f"data: {json.dumps(evento, ensure_ascii=False)}\n\n"
                if evento.get("tipo") == "FIN":
                    break
            except concurrent.futures.TimeoutError:
                yield 'data: {"tipo":"PING"}\n\n'
            except Exception:
                yield 'data: {"tipo":"PING"}\n\n'

    return Response(
        generar(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _get_con_timeout(cola: asyncio.Queue, timeout: float) -> Any:
    """Espera un elemento de la cola con timeout; retorna None si se agota."""
    try:
        return await asyncio.wait_for(cola.get(), timeout=timeout)
    except asyncio.TimeoutError:
        return None


# ── lock para serializar diálogos (tkinter no es thread-safe) ────────────────
_dialogo_lock = threading.Lock()


def _abrir_dialogo(tipo: str) -> Optional[str]:
    """
    Abre un diálogo nativo del SO para seleccionar archivo o carpeta.
    Usa tkinter.filedialog — disponible en Windows/macOS con Python estándar.
    Retorna la ruta seleccionada, o None si el usuario canceló.
    Lanza RuntimeError si tkinter no está disponible.
    """
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()          # ocultar ventana principal de Tk
    root.wm_attributes("-topmost", True)   # diálogo por encima de otras ventanas

    if tipo == "archivo":
        ruta = filedialog.askopenfilename(
            title="Seleccionar archivo Excel",
            filetypes=[("Excel", "*.xlsx *.xls"), ("Todos", "*.*")],
        )
    else:
        ruta = filedialog.askdirectory(
            title="Seleccionar carpeta de facturas PDF",
        )

    root.destroy()
    return ruta if ruta else None


@app.route("/explorar/<tipo>", methods=["POST"])
def explorar(tipo: str) -> Any:
    """
    Abre un diálogo nativo del SO (tkinter) para seleccionar archivo o carpeta.
    tipo: "archivo" → filedialog.askopenfilename
    tipo: "carpeta" → filedialog.askdirectory

    Solo puede haber un diálogo abierto a la vez (_dialogo_lock).
    """
    if tipo not in ("archivo", "carpeta"):
        return jsonify({"ok": False, "error": "Tipo de explorador inválido."}), 400

    if not _dialogo_lock.acquire(blocking=False):
        return jsonify({
            "ok":    False,
            "error": "Ya hay un explorador de archivos abierto. Cerralo antes de abrir otro.",
        })

    try:
        ruta = _abrir_dialogo(tipo)
        if ruta:
            return jsonify({"ok": True, "ruta": ruta})
        return jsonify({"ok": True, "cancelado": True})

    except ImportError:
        return jsonify({
            "ok":    False,
            "error": (
                "tkinter no está disponible en este entorno. "
                "Escribí la ruta directamente en el campo de texto."
            ),
        })
    except Exception as e:
        return jsonify({"ok": False, "error": f"Error al abrir el explorador: {e}"})
    finally:
        _dialogo_lock.release()


# =============================================================================
# ENTRY POINT
# =============================================================================



if __name__ == "__main__":
    threading.Timer(1.0, lambda: webbrowser.open("http://localhost:5000")).start()
    print("\n" + "=" * 50)
    print("  InvoiceFlow Bot v1.4 — Panel de Control")
    print("  Abriendo en: http://localhost:5000")
    print("  Para cerrar: Ctrl+C")
    print("=" * 50 + "\n")
    app.run(debug=False, port=5000, threaded=True)