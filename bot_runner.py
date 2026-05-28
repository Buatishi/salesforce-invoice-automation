# =============================================================================
# bot_runner.py — Lógica de ejecución del bot (usado por el panel web)
# =============================================================================

import asyncio
import logging
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from logger import inicializar_logger, registrar
from excel_handler import cargar_clientes, marcar_ok, ExcelWriter
from file_matcher import buscar_factura


def _normalizar_nombre(nombre: str) -> str:
    """
    #4: Normaliza un nombre para matching tolerante de PDF.

    Convierte tildes, diéresis, eñes y variantes Unicode a su
    equivalente ASCII. Así "García S.A." matchea "Garcia S.A.",
    "GARCIA S.A." y variantes tipográficas frecuentes en facturas.

    Usa unicodedata de la stdlib — sin dependencias externas.
    """
    import unicodedata
    # NFD descompone caracteres compuestos (á → a + ́)
    # luego filtramos las marcas diacríticas (categoría Mn)
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFD", nombre)
        if unicodedata.category(c) != "Mn"
    )
    # Normalizar espacios múltiples y strip
    return " ".join(sin_tildes.split())
from salesforce_bot import (
    SalesforceBot,
    CircuitBreakerAbierto,
    SesionExpiradaError,
    AprobacionPendienteError,
    detectar_pantalla_aprobacion,
)
from validaciones import validar_todo
from notificacion import enviar_resumen
from progresodb import (
    crear_sesion, registrar_procesado, obtener_pendientes,
    limpiar_sesion, hay_sesion_pendiente, cargar_sesion,
)


class BotRunner:
    """
    Orquestador del bot. Expone métodos síncronos para Flask.
    Internamente corre en asyncio sobre un hilo dedicado.
    """

    def __init__(self) -> None:
        self.cola: asyncio.Queue = asyncio.Queue()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._hilo: Optional[threading.Thread] = None
        self._ev_pausar:  Optional[asyncio.Event] = None
        self._ev_detener: Optional[asyncio.Event] = None
        self.corriendo: bool = False
        self.pausado:   bool = False
        self.totales:   Dict[str, int] = {"ok": 0, "ya_facturado": 0, "errores": 0}
        self.ultimos_errores: List[Dict] = []  # M3: errores de la última corrida real
        self._logger:   Optional[logging.Logger] = None  # U4: disponible para _esperar_aprobacion_manual
        self.ruta_log:  Optional[str] = None               # ETA-2: accesible desde Flask para /descargar_log

    # =========================================================================
    # CONTROL PÚBLICO (síncrono — llamado desde Flask)
    # =========================================================================

    def iniciar(
        self,
        url: str,
        excel_path: str,
        carpeta_pdf: str,
        es_dryrun: bool,
        reanudar: bool = False,
        umbral: int = 70,
    ) -> None:
        if self.corriendo:
            return
        self.corriendo = True
        self.pausado   = False
        self.totales   = {"ok": 0, "ya_facturado": 0, "errores": 0}
        # FIX-2: Event para que /eventos espere a que la cola definitiva esté lista
        # antes de empezar a leerla, eliminando la race condition entre el hilo
        # asyncio (_ejecutar reemplaza self.cola) y Flask (lee runner.cola en /eventos).
        self._cola_lista: threading.Event = threading.Event()
        self._loop = asyncio.new_event_loop()
        self._hilo = threading.Thread(
            target=self._arrancar_loop,
            args=(url, excel_path, carpeta_pdf, es_dryrun, reanudar, umbral),
            daemon=True,
        )
        self._hilo.start()

    def pausar(self) -> None:
        if self.corriendo and not self.pausado and self._ev_pausar and self._loop:
            self.pausado = True
            self._loop.call_soon_threadsafe(self._ev_pausar.set)
            self._poner_evento_sync("PAUSA", "⏸  Bot pausado — terminando cliente actual...")

    def reanudar(self) -> None:
        if self.pausado and self._ev_pausar and self._loop:
            self.pausado = False
            self._loop.call_soon_threadsafe(self._ev_pausar.clear)
            self._poner_evento_sync("REANUDAR", "▶  Reanudando...")

    def detener(self) -> None:
        if self._ev_detener and self._loop:
            self._loop.call_soon_threadsafe(self._ev_detener.set)
        if self._ev_pausar and self._loop:
            self._loop.call_soon_threadsafe(self._ev_pausar.clear)
        self.pausado = False

    def hay_sesion_pendiente(self) -> bool:
        return hay_sesion_pendiente()

    def info_sesion_pendiente(self) -> Dict[str, Any]:
        sesion: Optional[Dict] = cargar_sesion()
        if not sesion:
            return {}
        procesados: Dict = sesion.get("procesados", {})
        return {
            "inicio":     sesion.get("inicio", ""),
            "total":      sesion.get("total", 0),
            "procesados": len(procesados),
            "pendientes": sesion.get("total", 0) - len(procesados),
            "modo":       sesion.get("modo", ""),
        }

    # =========================================================================
    # LOOP DEDICADO
    # =========================================================================

    def _arrancar_loop(
        self,
        url: str,
        excel_path: str,
        carpeta_pdf: str,
        es_dryrun: bool,
        reanudar: bool,
        umbral: int,
    ) -> None:
        asyncio.set_event_loop(self._loop)
        # Timeout global: 4 horas máximo por corrida.
        # Evita que el bot quede colgado indefinidamente si Playwright se congela.
        TIMEOUT_GLOBAL = 4 * 60 * 60  # segundos

        async def _con_timeout():
            try:
                await asyncio.wait_for(
                    self._ejecutar(url, excel_path, carpeta_pdf, es_dryrun, reanudar, umbral),
                    timeout=TIMEOUT_GLOBAL,
                )
            except asyncio.TimeoutError:
                self.corriendo = False
                self.pausado   = False
                await self.cola.put({
                    "tipo":    "ERROR",
                    "mensaje": "Tiempo limite de corrida alcanzado (4 horas). El bot se detuvo automaticamente.",
                })
                await self.cola.put({"tipo": "FIN", "mensaje": "Bot detenido por timeout global."})
                await self.cola.put({"tipo": "TOTALES", "mensaje": self.totales})

        try:
            self._loop.run_until_complete(_con_timeout())
        except Exception as exc:
            # FIX-4: si el loop muere por una excepción no capturada (raro pero posible),
            # garantizar que corriendo vuelva a False para que el botón Iniciar no quede
            # permanentemente deshabilitado hasta reiniciar el servidor.
            import traceback
            print(f"[BotRunner] Error fatal en hilo asyncio: {exc}")
            traceback.print_exc()
        finally:
            # FIX-4: reset de estado garantizado — cubre tanto el caso normal (ya lo
            # resetea _finalizar) como el caso de excepción no capturada en el loop.
            self.corriendo = False
            self.pausado   = False
            # Señalizar _cola_lista por si /eventos está esperando (caso de fallo
            # antes de que _ejecutar llegue a reemplazar la cola).
            if hasattr(self, "_cola_lista") and not self._cola_lista.is_set():
                self._cola_lista.set()

    # =========================================================================
    # EJECUCIÓN PRINCIPAL (async)
    # =========================================================================

    async def _ejecutar(
        self,
        url: str,
        excel_path: str,
        carpeta_pdf: str,
        es_dryrun: bool,
        reanudar: bool,
        umbral: int,
    ) -> None:
        """Corrutina principal del bot."""

        # FIX-1: obtener loop PRIMERO — se usa en _t_inicio_corrida y en todo
        # el resto de la corrutina. Antes estaba definido ~70 líneas más abajo,
        # causando NameError inmediato que mataba el hilo silenciosamente.
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()

        self._ev_pausar  = asyncio.Event()
        self._ev_detener = asyncio.Event()

        # FIX-2: reemplazar la cola ANTES de señalizar _cola_lista, para que
        # el endpoint /eventos siempre lea la cola correcta (la del loop activo).
        self.cola = asyncio.Queue()
        # Señalizar que la cola ya es la definitiva — /eventos puede empezar a leer.
        if hasattr(self, "_cola_lista"):
            self._cola_lista.set()

        logger:   logging.Logger = inicializar_logger(dryrun=es_dryrun)
        ruta_log: Optional[str]  = None
        self._logger = logger   # U4: accesible desde _esperar_aprobacion_manual
        self.ruta_log = ruta_log  # actualizado al encontrar el FileHandler (ver abajo)

        # FIX-7: pasar getter en lugar de referencia directa a self.cola.
        # self.cola ya fue reemplazada arriba (nueva Queue del loop activo),
        # pero si en el futuro cambia de nuevo, el handler siempre leerá la vigente.
        logger.addHandler(_QueueHandler(lambda: self.cola, self._loop))
        for h in logger.handlers:
            if hasattr(h, "baseFilename"):
                ruta_log      = h.baseFilename
                self.ruta_log = ruta_log  # exponer a Flask para /descargar_log
                break

        modo_txt: str = "DRY-RUN" if es_dryrun else "REAL"
        await self._evento("INICIO", f"Bot iniciado — Modo: {modo_txt}")
        _t_inicio_corrida = loop.time()  # 5: para avisos progresivos de timeout
        self._aviso_3h  = False  # 5: flags de aviso de timeout
        self._aviso_35h = False

        # ── Validaciones previas ─────────────────────────────────────────────
        ok, errores_val = validar_todo(url, excel_path, carpeta_pdf)
        if not ok:
            for e in errores_val:
                await self._evento("ERROR", e)
            await self._finalizar("error")
            return

        # ── Cargar clientes del Excel ────────────────────────────────────────
        try:
            todos_los_clientes: List[Dict] = cargar_clientes(excel_path, logger)
        except Exception as e:
            await self._evento("ERROR", f"No se pudo leer el Excel: {e}")
            await self._finalizar("error")
            return

        if not todos_los_clientes:
            await self._evento("INFO", "No hay clientes pendientes en el Excel.")
            await self._finalizar("completado")
            return

        # ── Pendientes (con lógica de reanudación) ───────────────────────────
        if reanudar and hay_sesion_pendiente():
            clientes: List[Dict] = obtener_pendientes(todos_los_clientes, logger)
            await self._evento(
                "REANUDAR",
                f"Reanudando sesión — {len(clientes)} clientes pendientes.",
            )
        else:
            clientes = obtener_pendientes(todos_los_clientes, logger)
            crear_sesion(
                excel_path, carpeta_pdf, url,
                "dryrun" if es_dryrun else "real",
                len(clientes),
            )

        if not clientes:
            await self._evento("INFO", "Todos los clientes ya fueron procesados.")
            limpiar_sesion()
            await self._finalizar("completado")
            return

        await self._evento("INFO", f"Clientes a procesar: {len(clientes)}")
        await self._evento("INFO", f"Umbral de similitud: {umbral}%")
        # Emitir total para la barra de progreso del panel
        await self._evento("PROGRESO", {"procesados": 0, "total": len(clientes), "porcentaje": 0})

        # ── Dry-run ──────────────────────────────────────────────────────────
        if es_dryrun:
            errores_detalle: List[Dict] = await self._correr_dryrun(
                clientes, carpeta_pdf, logger, umbral
            )
            limpiar_sesion()
            await self._enviar_mail("dryrun", errores_detalle, ruta_log, logger)
            await self._finalizar("completado")
            return

        # ── Modo real ────────────────────────────────────────────────────────
        errores_detalle = []
        _total_clientes = len(clientes)
        _procesados_count = 0

        # Mejora 1: ExcelWriter persistente durante toda la corrida real.
        excel_writer = ExcelWriter(excel_path, logger)

        bot = SalesforceBot(logger=logger, salesforce_url=url)
        try:
            # Mejora 6: get_running_loop() en lugar de get_event_loop()
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, bot.iniciar)
        except AprobacionPendienteError as e:
            # T2/T4: Salesforce requiere aprobación manual — NO reintentar login.
            # Esperar con polling activo hasta que el admin apruebe o se agote el timeout.
            aprobado = await self._esperar_aprobacion_manual(bot, str(e), sf_url=url)
            if not aprobado:
                excel_writer.cerrar()
                await self._finalizar("detenido")
                return
            # Admin aprobó — continuar la corrida normalmente desde aquí
        except Exception as e:
            msg = str(e)
            # V2: Si existe screenshot de diagnóstico, indicarlo en el mensaje del panel
            from pathlib import Path as _Path
            import glob as _glob
            screenshots = sorted(
                _glob.glob("logs/login_fail_*.png"),
                key=lambda p: _Path(p).stat().st_mtime,
                reverse=True,
            )
            if screenshots:
                msg += f" (captura guardada: {screenshots[0]})"
            await self._evento("ERROR", f"No se pudo iniciar Salesforce: {msg}")
            excel_writer.cerrar()
            await self._finalizar("error")
            return

        try:
            loop = asyncio.get_running_loop()
            from collections import deque
            cola_clientes: deque = deque(clientes)

            while cola_clientes:

                if self._ev_detener.is_set():
                    await self._evento("DETENIDO", "Bot detenido por el operador.")
                    break

                # 5: Avisos progresivos de timeout antes de las 4h
                _elapsed = loop.time() - _t_inicio_corrida
                if not getattr(self, "_aviso_3h", False) and _elapsed >= 3 * 3600:
                    self._aviso_3h = True
                    await self._evento("WARN",
                        "⏰ La corrida lleva 3 horas en curso. "
                        "El bot se detiene automáticamente a las 4 horas. "
                        "Considerá pausar y reanudar mañana si quedan muchos clientes.")
                elif not getattr(self, "_aviso_35h", False) and _elapsed >= 3.5 * 3600:
                    self._aviso_35h = True
                    await self._evento("WARN",
                        "⏰ ¡Faltan 30 minutos para el límite de 4 horas! "
                        "El bot se detendrá pronto. Pausá la corrida para continuar mañana.")

                if self._ev_pausar.is_set():
                    await self._evento("PAUSA", "⏸  En pausa — esperando orden de reanudar.")
                    while self._ev_pausar.is_set() and not self._ev_detener.is_set():
                        await asyncio.sleep(0.5)
                    if self._ev_detener.is_set():
                        break
                    await self._evento("REANUDAR", "▶  Reanudado.")

                cliente = cola_clientes.popleft()
                fila:   int = cliente["fila"]
                nombre: str = cliente["nombre"]
                cobro:  str = cliente["cobro"]

                # T5 — Verificar sesión activa antes de cada cliente.
                # Si expiró: reconectar (puede requerir aprobación manual nuevamente).
                sesion_ok = await loop.run_in_executor(None, bot._verificar_sesion)
                if not sesion_ok:
                    await self._evento("WARN", "⚠️  Sesión expirada — reconectando antes del siguiente cliente...")
                    try:
                        reconectado = await loop.run_in_executor(None, bot.reconectar)
                    except AprobacionPendienteError as e:
                        aprobado = await self._esperar_aprobacion_manual(bot, str(e), sf_url=url)
                        if not aprobado:
                            cola_clientes.appendleft(cliente)
                            break
                        reconectado = True
                    if not reconectado:
                        await self._evento("ERROR", "Reconexión fallida. El bot se detuvo.")
                        cola_clientes.appendleft(cliente)
                        break
                    await self._evento("INFO", "✅ Sesión restablecida — continuando.")

                _t_inicio_cliente = loop.time()
                await self._evento("CLIENTE", f"{cobro} | {nombre}")

                # ── Buscar cliente en Salesforce ─────────────────────────────
                try:
                    resultado: str = await loop.run_in_executor(
                        None, bot.buscar_cliente, cobro
                    )
                except CircuitBreakerAbierto as e:
                    await self._evento(
                        "ERROR",
                        "El bot encontró demasiados errores seguidos y se detuvo "
                        "para evitar problemas mayores. Revisá los últimos clientes "
                        "con error antes de volver a iniciar."
                    )
                    registrar(logger, cobro, nombre, "ERROR_CIRCUITBREAKER", str(e))
                    errores_detalle.append({
                        "cobro": cobro, "nombre": nombre,
                        "estado": "ERROR_CIRCUITBREAKER",
                        "detalle": "Demasiados errores consecutivos — corrida detenida automáticamente.",
                    })
                    self.totales["errores"] += 1
                    break

                if resultado == "ERROR_SESION_EXPIRADA":
                    await self._evento(
                        "WARN", "⚠️  Sesión expirada — intentando reconexión automática..."
                    )
                    try:
                        reconectado: bool = await loop.run_in_executor(None, bot.reconectar)
                    except AprobacionPendienteError as e:
                        # Sesión expiró y el re-login requiere aprobación manual mid-run
                        aprobado = await self._esperar_aprobacion_manual(bot, str(e), sf_url=url)
                        if not aprobado:
                            cola_clientes.appendleft(cliente)
                            break
                        # Admin aprobó — reinsertar cliente y continuar
                        await self._evento("INFO", "✅ Aprobación concedida — reintentando cliente.")
                        cola_clientes.appendleft(cliente)
                        continue
                    if reconectado:
                        await self._evento("INFO", "✅ Reconexión exitosa — reintentando cliente.")
                        # Reinsertar el cliente al frente de la cola para reprocesarlo
                        cola_clientes.appendleft(cliente)
                        continue
                    else:
                        registrar(logger, cobro, nombre, "ERROR_SESION_EXPIRADA",
                                  "Sesión cerrada. Reconexión fallida tras intento.")
                        registrar_procesado(cobro, "ERROR_SESION_EXPIRADA")
                        errores_detalle.append({
                            "cobro": cobro, "nombre": nombre,
                            "estado": "ERROR_SESION_EXPIRADA",
                            "detalle": "Sesión cerrada. Reconexión fallida.",
                        })
                        self.totales["errores"] += 1
                        break

                if resultado == "ERROR_ID":
                    registrar(logger, cobro, nombre, "ERROR_ID",
                              f"No encontrado en Salesforce: cobro='{cobro}', nombre='{nombre}'")
                    registrar_procesado(cobro, "ERROR_ID")
                    _detalle_id = (
                        f"No encontrado en Salesforce buscando: '{cobro}' — '{nombre}'. "
                        f"Verificá que el número de cobro exista y sea exacto en Salesforce."
                    )
                    errores_detalle.append({
                        "cobro": cobro, "nombre": nombre,
                        "estado": "ERROR_ID",
                        "detalle": _detalle_id,
                    })
                    self.totales["errores"] += 1
                    await self._evento("CLIENTE_FIN", {"cobro": cobro, "nombre": nombre, "estado": "ERROR_ID", "detalle": _detalle_id})
                    await loop.run_in_executor(None, bot.reset_estado)
                    continue

                # ── Verificar factura existente ──────────────────────────────
                ya_facturado: bool = await loop.run_in_executor(
                    None, bot.verificar_factura_existente
                )
                if ya_facturado:
                    registrar(logger, cobro, nombre, "YA_FACTURADO", "Tenía factura previa.")
                    registrar_procesado(cobro, "YA_FACTURADO")
                    self.totales["ya_facturado"] += 1
                    await self._evento("CLIENTE_FIN", {"cobro": cobro, "nombre": nombre, "estado": "YA_FACTURADO", "detalle": "Ya tenia factura adjuntada"})
                    await loop.run_in_executor(None, bot.reset_estado)
                    continue

                # ── Buscar PDF local ─────────────────────────────────────────
                # #4: Normalizar nombre (tildes, eñes, mayúsculas) antes de buscar PDF
                _nombre_normalizado = _normalizar_nombre(nombre)
                ruta_pdf, estado_pdf = buscar_factura(_nombre_normalizado, logger, carpeta_pdf, umbral)
                if estado_pdf != "OK":
                    registrar(logger, cobro, nombre, estado_pdf,
                              f"No se encontró factura para '{nombre}'.")
                    registrar_procesado(cobro, estado_pdf)
                    errores_detalle.append({
                        "cobro": cobro, "nombre": nombre,
                        "estado": estado_pdf,
                        "detalle": f"No se encontró PDF para '{nombre}'.",
                    })
                    self.totales["errores"] += 1
                    await self._evento("CLIENTE_FIN", {"cobro": cobro, "nombre": nombre, "estado": estado_pdf, "detalle": f"PDF no encontrado para {nombre}"})
                    await loop.run_in_executor(None, bot.reset_estado)
                    continue

                # ── Adjuntar factura ─────────────────────────────────────────
                try:
                    res_adj: str = await loop.run_in_executor(
                        None, bot.adjuntar_factura, ruta_pdf
                    )
                except CircuitBreakerAbierto as e:
                    await self._evento("ERROR", f"Circuit breaker abierto: {e}")
                    errores_detalle.append({
                        "cobro": cobro, "nombre": nombre,
                        "estado": "ERROR_ADJUNTO_FALLIDO",
                        "detalle": "Circuit breaker: demasiados fallos consecutivos.",
                    })
                    self.totales["errores"] += 1
                    break

                if res_adj != "OK":
                    registrar(logger, cobro, nombre, res_adj,
                              f"No se pudo adjuntar: {ruta_pdf.name}")
                    registrar_procesado(cobro, res_adj)
                    errores_detalle.append({
                        "cobro": cobro, "nombre": nombre,
                        "estado": res_adj,
                        "detalle": f"Fallo al adjuntar {ruta_pdf.name}.",
                    })
                    self.totales["errores"] += 1
                    await loop.run_in_executor(None, bot.reset_estado)
                    continue

                # ── Marcar Facturado ─────────────────────────────────────────
                try:
                    res_fact: str = await loop.run_in_executor(
                        None, bot.marcar_facturado
                    )
                except CircuitBreakerAbierto as e:
                    await self._evento("ERROR", f"Circuit breaker abierto: {e}")
                    errores_detalle.append({
                        "cobro": cobro, "nombre": nombre,
                        "estado": "ERROR_CASILLA_BLOQUEADA",
                        "detalle": "Circuit breaker: demasiados fallos consecutivos.",
                    })
                    self.totales["errores"] += 1
                    break

                if res_fact != "OK":
                    registrar(logger, cobro, nombre, res_fact,
                              "Adjuntado pero no se pudo marcar Facturado.")
                    registrar_procesado(cobro, res_fact)
                    errores_detalle.append({
                        "cobro": cobro, "nombre": nombre,
                        "estado": res_fact,
                        "detalle": "Factura adjuntada pero casilla no marcada.",
                    })
                    self.totales["errores"] += 1
                    await loop.run_in_executor(None, bot.reset_estado)
                    continue

                # ── Marcar OK en Excel (ExcelWriter persistente) ─────────────
                # Mejora 1: marcar_ok() en memoria; flush() persiste en disco.
                # 5/A4: PermissionError explícito — Excel abierto mid-run
                try:
                    ok_excel = excel_writer.marcar_ok(fila)
                    if ok_excel:
                        excel_writer.flush()  # un write por cliente, no por apertura
                except PermissionError:
                    ok_excel = False
                    await self._evento("WARN",
                        "⚠️  El Excel está bloqueado (probablemente abierto en Excel). "
                        "Cerralo y usá 'Reintentar errores' al terminar la corrida."
                    )
                if ok_excel:
                    registrar(logger, cobro, nombre, "OK", f"Procesado: {ruta_pdf.name}")
                    registrar_procesado(cobro, "OK")
                    self.totales["ok"] += 1
                    await self._evento("CLIENTE_FIN", {"cobro": cobro, "nombre": nombre, "estado": "OK", "detalle": ruta_pdf.name})
                else:
                    registrar(logger, cobro, nombre, "PENDIENTE_MANUAL",
                              "OK en Salesforce pero no se escribió OK en Excel.")
                    registrar_procesado(cobro, "PENDIENTE_MANUAL")
                    errores_detalle.append({
                        "cobro": cobro, "nombre": nombre,
                        "estado": "PENDIENTE_MANUAL",
                        "detalle": "OK en Salesforce, fallo al escribir Excel.",
                    })
                    await self._evento("CLIENTE_FIN", {"cobro": cobro, "nombre": nombre, "estado": "PENDIENTE_MANUAL", "detalle": "OK en SF, fallo en Excel"})

                await loop.run_in_executor(None, bot.reset_estado)
                _procesados_count += 1
                _pct = round(_procesados_count / _total_clientes * 100) if _total_clientes else 0
                _dur_seg = round(loop.time() - _t_inicio_cliente, 1)
                await self._evento("PROGRESO", {
                    "procesados": _procesados_count,
                    "total":      _total_clientes,
                    "porcentaje": _pct,
                    "dur_seg":    _dur_seg,  # duración del último cliente en segundos
                })

        except Exception as e:
            await self._evento("ERROR", f"Error inesperado: {e}")
        finally:
            excel_writer.cerrar()          # flush final + libera workbook
            loop2 = asyncio.get_running_loop()
            await loop2.run_in_executor(None, bot.cerrar)

        limpiar_sesion()
        self.ultimos_errores = errores_detalle  # M3: guardar para /errores_ultima_corrida
        await self._enviar_mail("real", errores_detalle, ruta_log, logger)
        await self._finalizar("completado")

    # =========================================================================
    # DRY-RUN (async)
    # =========================================================================

    async def _correr_dryrun(
        self,
        clientes: List[Dict],
        carpeta_pdf: str,
        logger: logging.Logger,
        umbral: int,
    ) -> List[Dict]:
        """
        Corre el dry-run y retorna la lista de errores para el mail.
        Paraleliza la búsqueda de PDFs con asyncio.gather.
        """
        await self._evento("INFO", "=" * 46)
        await self._evento("INFO", f"DRY-RUN — Analizando {len(clientes)} clientes")
        await self._evento("INFO", "=" * 46)

        con_pdf:      List = []
        sin_pdf:      List = []
        errores_mail: List[Dict] = []

        # Mejora 6: get_running_loop() en lugar de get_event_loop()
        loop = asyncio.get_running_loop()

        async def buscar_uno(cliente: Dict) -> None:
            nombre: str = cliente["nombre"]
            cobro:  str = cliente["cobro"]

            if self._ev_detener.is_set():
                return

            await self._evento("CLIENTE", f"{cobro} | {nombre}")

            ruta_pdf, estado = await loop.run_in_executor(
                None, buscar_factura, nombre, logger, carpeta_pdf, umbral
            )

            if estado == "OK":
                await self._evento("DRY_OK", f"PDF listo: {ruta_pdf.name}")
                await self._evento("CLIENTE_FIN", {
                    "cobro":   cobro,
                    "nombre":  nombre,
                    "estado":  "DRY_OK",
                    "detalle": ruta_pdf.name,
                })
                con_pdf.append((cobro, nombre, ruta_pdf.name))
                self.totales["ok"] += 1
            else:
                await self._evento("DRY_ERROR", f"{estado}")
                await self._evento("CLIENTE_FIN", {
                    "cobro":   cobro,
                    "nombre":  nombre,
                    "estado":  "DRY_ERROR",
                    "detalle": estado,
                })
                sin_pdf.append((cobro, nombre, estado))
                errores_mail.append({
                    "cobro":   cobro,
                    "nombre":  nombre,
                    "estado":  estado,
                    "detalle": "PDF no encontrado o con problemas en la carpeta local.",
                })
                self.totales["errores"] += 1

        await asyncio.gather(*[buscar_uno(c) for c in clientes])

        await self._evento("INFO", "=" * 46)
        await self._evento("INFO", "RESUMEN DRY-RUN")
        await self._evento("INFO", f"✅ Con PDF listo : {len(con_pdf)}")
        await self._evento("INFO", f"❌ Con problemas : {len(sin_pdf)}")

        if sin_pdf:
            await self._evento("INFO", "─ Clientes con problemas:")
            for cobro, nombre, estado in sin_pdf:
                await self._evento("DRY_ERROR", f"  {cobro} | {nombre} | {estado}")

        await self._evento("INFO", "=" * 46)
        await self._evento("INFO", "Dry-run finalizado. Revisá y cambiá a modo REAL.")

        return errores_mail

    # =========================================================================
    # ESPERA DE APROBACIÓN MANUAL (async) — T2
    # =========================================================================

    async def _esperar_aprobacion_manual(
        self,
        bot: "SalesforceBot",
        mensaje_original: str,
        sf_url: str = "",
    ) -> bool:
        """
        Espera activamente a que el admin de Salesforce apruebe el acceso.

        Diseño:
        - Emite APROBACION_PENDIENTE → panel muestra banner amarillo con timer.
        - Polling cada 20s: navega al home de SF y verifica si la sesión quedó activa.
        - Emite LOG en cada tick → mantiene el SSE vivo (anti-timeout de proxies).
        - Respeta _ev_detener: si el operador detiene manualmente, cancela la espera.
        - Si se aprueba: emite APROBACION_RESUELTA → panel oculta banner, sigue corriendo.
        - Si se agota el timeout (30 min): emite ERROR con mensaje claro para el usuario.

        Retorna True si la aprobación fue concedida, False si se agotó el tiempo
        o el operador detuvo manualmente.
        """
        TIMEOUT_SEG   = 1800  # 30 minutos máximo de espera
        POLLING_SEG   = 20    # verificar cada 20 segundos
        AVISO_SEG     = 300   # recordatorio al operador cada 5 minutos

        loop = asyncio.get_running_loop()

        await self._evento("APROBACION_PENDIENTE", {
            "mensaje": mensaje_original,
            "ts": __import__("time").strftime("%H:%M:%S"),
        })

        # U4: Notificar por email al usuario para que avise al admin,
        # sin bloquear el loop — el email es best-effort (falla silenciosa).
        loop.run_in_executor(None, lambda: self._enviar_email_aprobacion_pendiente(sf_url))

        inicio       = loop.time()
        ultimo_aviso = inicio

        while True:
            # ── Detención manual por el operador ────────────────────────────
            if self._ev_detener.is_set():
                await self._evento("WARN",
                    "Espera de aprobación cancelada por el operador.")
                return False

            transcurrido = loop.time() - inicio

            # ── Timeout global ───────────────────────────────────────────────
            if transcurrido >= TIMEOUT_SEG:
                await self._evento("ERROR", (
                    f"El administrador no aprobó el acceso en "
                    f"{TIMEOUT_SEG // 60} minutos. "
                    "El bot se detuvo. Pedile al admin que apruebe y volvé a iniciar."
                ))
                return False

            # ── Heartbeat visible → mantiene SSE activo ──────────────────────
            min_e = int(transcurrido // 60)
            seg_e = int(transcurrido  % 60)
            tiempo_str = f"{min_e}m {seg_e}s" if min_e > 0 else f"{seg_e}s"
            await self._evento("LOG",
                f"[Aprobación] Esperando al administrador... ({tiempo_str} transcurridos)")

            # ── Aviso periódico cada 5 min ───────────────────────────────────
            if transcurrido - (ultimo_aviso - inicio) >= AVISO_SEG:
                await self._evento("WARN",
                    "⏳ Todavía esperando aprobación del admin en Salesforce. "
                    "Si pasaron varios minutos, recordale que apruebe la solicitud.")
                ultimo_aviso = loop.time()

            # ── Esperar intervalo respetando detención ───────────────────────
            try:
                await asyncio.wait_for(
                    self._ev_detener.wait(),
                    timeout=POLLING_SEG,
                )
                # Si llegamos acá, _ev_detener se activó durante el sleep
                await self._evento("WARN",
                    "Espera de aprobación cancelada por el operador.")
                return False
            except asyncio.TimeoutError:
                pass  # Normal — el intervalo terminó, verificar estado

            # ── Verificar si la sesión fue aprobada ──────────────────────────
            try:
                sesion_activa = await loop.run_in_executor(None, bot._verificar_sesion)
                aprobacion_aun_pendiente = await loop.run_in_executor(
                    None, detectar_pantalla_aprobacion, bot.page
                )

                if sesion_activa and not aprobacion_aun_pendiente:
                    # ¡Admin aprobó! Notificar y retornar
                    await self._evento("APROBACION_RESUELTA", {
                        "mensaje": "✅ Acceso aprobado por el administrador. Retomando la corrida.",
                        "ts": __import__("time").strftime("%H:%M:%S"),
                        "espera_seg": int(transcurrido + POLLING_SEG),
                    })
                    return True

            except Exception as e:
                # Error de red durante el check — no es fatal, seguir esperando
                await self._evento("LOG",
                    f"[Aprobación] No se pudo verificar estado (reintentando): {str(e)[:60]}")

    # =========================================================================
    # NOTIFICACIÓN EMAIL — APROBACIÓN PENDIENTE (sync, llamado en executor)
    # =========================================================================

    def _enviar_email_aprobacion_pendiente(self, sf_url: str = "") -> None:
        """
        U4: Avisa por email que Salesforce está esperando aprobación del admin.

        - Sincrónica — se llama desde run_in_executor (no bloquea el loop async).
        - Best-effort: cualquier fallo es silencioso, nunca interrumpe la corrida.
        - Usa EMAIL_REMITENTE / EMAIL_DESTINATARIO / EMAIL_APP_PASSWORD del .env,
          los mismos que usa enviar_resumen(). Si no están configurados, no hace nada.
        """
        try:
            from config import EMAIL_REMITENTE, EMAIL_DESTINATARIO, EMAIL_APP_PASSWORD
            if (
                not EMAIL_REMITENTE or EMAIL_REMITENTE == "COMPLETAR@gmail.com"
                or not EMAIL_APP_PASSWORD or EMAIL_APP_PASSWORD == "COMPLETAR"
                or not EMAIL_DESTINATARIO
            ):
                return  # Email no configurado — omitir silenciosamente

            import smtplib
            import time as _t
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText
            from datetime import datetime

            hora      = _t.strftime("%H:%M")
            timestamp = datetime.now().strftime("%d/%m/%Y %H:%M")
            org_label = sf_url if sf_url else "Salesforce"
            asunto    = f"[InvoiceFlow Bot] ⏳ Acción requerida — aprobación pendiente ({hora})"

            cuerpo_html = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f4f6f9;font-family:Arial,sans-serif">
<div style="max-width:600px;margin:32px auto;background:white;border-radius:10px;
            overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08)">

  <!-- Header amarillo de alerta -->
  <div style="background:#f6bf26;padding:22px 28px">
    <p style="margin:0;color:rgba(0,0,0,0.55);font-size:11px;letter-spacing:1px">
      INVOICEFLOW BOT — ACCIÓN REQUERIDA
    </p>
    <h1 style="margin:6px 0 0;color:#333;font-size:20px;font-weight:700">
      ⏳ El bot está esperando al administrador
    </h1>
  </div>

  <!-- Cuerpo -->
  <div style="padding:26px 28px">
    <p style="font-size:14px;color:#444;line-height:1.7;margin-top:0">
      El bot intentó iniciar sesión en <strong>{org_label}</strong> pero tu cuenta
      requiere que un <strong>administrador apruebe el acceso</strong> antes de continuar.
    </p>

    <!-- Qué hacer -->
    <div style="background:#fff8e1;border-left:4px solid #f6bf26;padding:14px 18px;
                border-radius:0 8px 8px 0;margin:20px 0">
      <p style="margin:0 0 8px;font-size:13px;font-weight:700;color:#7a5800">
        ¿Qué hacer ahora?
      </p>
      <ol style="margin:0;padding-left:18px;font-size:13px;color:#555;line-height:1.8">
        <li>Avisale a tu administrador de Salesforce que apruebe tu solicitud de acceso.</li>
        <li>El bot retomará automáticamente cuando el admin apruebe.</li>
        <li>Si pasaron más de 30 minutos sin aprobación, el bot se detuvo —
            volvé a iniciarlo desde el panel.</li>
      </ol>
    </div>

    <p style="font-size:12px;color:#999;margin-bottom:0">
      Hora de la solicitud: {timestamp}
    </p>
  </div>

  <!-- Footer -->
  <div style="background:#f4f6f9;padding:14px 28px;border-top:1px solid #eee">
    <p style="margin:0;font-size:11px;color:#aaa">
      Este aviso fue generado automáticamente por InvoiceFlow Bot.
    </p>
  </div>
</div>
</body>
</html>"""

            msg = MIMEMultipart("mixed")
            msg["From"]    = EMAIL_REMITENTE
            msg["To"]      = EMAIL_DESTINATARIO
            msg["Subject"] = asunto
            msg.attach(MIMEText(cuerpo_html, "html", "utf-8"))

            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as servidor:
                servidor.login(EMAIL_REMITENTE, EMAIL_APP_PASSWORD)
                servidor.sendmail(EMAIL_REMITENTE, EMAIL_DESTINATARIO, msg.as_string())

        except Exception:
            pass  # Best-effort — nunca interrumpir la corrida por un email fallido

    # =========================================================================
    # NOTIFICACIÓN POR MAIL (async)
    # =========================================================================

    async def _enviar_mail(
        self,
        modo: str,
        errores_detalle: List[Dict],
        ruta_log: Optional[str],
        logger: logging.Logger,
    ) -> None:
        await self._evento("INFO", "Enviando notificación por email...")
        # Mejora 6: get_running_loop()
        loop = asyncio.get_running_loop()
        ok: bool = await loop.run_in_executor(
            None,
            lambda: enviar_resumen(
                modo=modo,
                totales=self.totales,
                errores_detalle=errores_detalle,
                ruta_log=ruta_log,
                logger=logger,
            ),
        )
        if ok:
            await self._evento("INFO", "✅ Notificación enviada correctamente.")
        else:
            await self._evento(
                "INFO",
                "⚠️  No se envió notificación — verificá EMAIL_* en el archivo .env",
            )

    # =========================================================================
    # HELPERS
    # =========================================================================

    async def _evento(self, tipo: str, mensaje: Any) -> None:
        await self.cola.put({"tipo": tipo, "mensaje": mensaje})

    async def _finalizar(self, motivo: str = "completado") -> None:
        """
        U3: Finaliza la corrida emitiendo el motivo real al panel.
        motivo: "completado" | "detenido" | "error"
        """
        self.corriendo = False
        self.pausado   = False
        mensajes = {
            "completado": "✅ Corrida finalizada — todos los clientes procesados.",
            "detenido":   "⏹ Corrida detenida manualmente por el operador.",
            "error":      "❌ Corrida finalizada por error crítico.",
        }
        await self._evento("FIN", {"mensaje": mensajes.get(motivo, "Bot finalizado."), "motivo": motivo})
        await self._evento("TOTALES", self.totales)

    def _poner_evento_sync(self, tipo: str, mensaje: str) -> None:
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self._evento(tipo, mensaje), self._loop
            )


# =============================================================================
# HANDLER DE LOGGING → COLA ASYNC
# =============================================================================

class _QueueHandler(logging.Handler):
    """
    Redirige el logger a la cola asyncio de eventos del panel web.
    Requiere el loop para poner elementos de forma thread-safe.

    FIX-7: acepta un callable cola_getter en lugar de la cola directamente.
    Si BotRunner reemplaza self.cola (lo hace al inicio de cada _ejecutar()),
    el handler seguira apuntando a la instancia vigente porque llama al getter
    en cada emit(), en vez de guardar la referencia inicial que ya fue descartada.
    """

    def __init__(
        self,
        cola_getter: "Callable[[], asyncio.Queue]",
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        super().__init__()
        self._cola_getter: "Callable[[], asyncio.Queue]" = cola_getter
        self.loop: asyncio.AbstractEventLoop             = loop

    def emit(self, record: logging.LogRecord) -> None:
        msg: str = self.format(record)
        try:
            asyncio.run_coroutine_threadsafe(
                self._cola_getter().put({"tipo": "LOG", "mensaje": msg}),
                self.loop,
            )
        except Exception:
            pass  # Nunca interrumpir el logger por un fallo de cola