"""
aplicar_parche.py — Aplica automáticamente el parche frozen a app.py
=====================================================================
Ejecutar una sola vez antes de empaquetar:
    python aplicar_parche.py

Lo que hace:
  1. Hace backup de app.py → app.py.bak
  2. Inserta el bloque de código frozen detection en el lugar correcto
  3. Parchea use_reloader=False en app.run()
  4. Verifica que el parche se aplicó correctamente

Seguro de correr múltiples veces: detecta si el parche ya está aplicado.
"""

import shutil
import sys
from pathlib import Path

APP_PY = Path("app.py")
BACKUP = Path("app.py.bak")

MARKER_FROZEN = "getattr(_sys, 'frozen', False)"

BLOQUE_FROZEN = '''
import sys as _sys
import os as _os

# Detección de entorno frozen (PyInstaller) — no-op con 'python app.py'
if getattr(_sys, 'frozen', False):
    _EXE_DIR = _os.path.dirname(_sys.executable)
    _BUNDLE  = _sys._MEIPASS  # type: ignore[attr-defined]
    _os.chdir(_EXE_DIR)
    _pw_path = _os.path.join(_BUNDLE, 'ms-playwright')
    if _os.path.isdir(_pw_path):
        _os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', _pw_path)
    _os.environ.setdefault('SELECTORES_PATH',  _os.path.join(_EXE_DIR, 'selectores.json'))
    _os.environ.setdefault('DB_PROGRESO_PATH', _os.path.join(_EXE_DIR, 'progreso.db'))
    _os.environ.setdefault('CARPETA_LOGS',     _os.path.join(_EXE_DIR, 'logs'))
    import shutil as _shutil
    _sel_dst = _os.path.join(_EXE_DIR, 'selectores.json')
    _sel_src = _os.path.join(_BUNDLE,  'selectores.json')
    if not _os.path.exists(_sel_dst) and _os.path.exists(_sel_src):
        _shutil.copy2(_sel_src, _sel_dst)
    _env_dst = _os.path.join(_EXE_DIR, '.env')
    _env_src = _os.path.join(_BUNDLE,  '.env.example')
    if not _os.path.exists(_env_dst) and _os.path.exists(_env_src):
        _shutil.copy2(_env_src, _env_dst)
    _os.makedirs(_os.path.join(_EXE_DIR, 'logs'), exist_ok=True)

'''

ANCHOR_LINE   = "from typing import Any, Dict, Generator, Optional"
OLD_APPRUN    = "app.run(debug=False, port=5000, threaded=True)"
NEW_APPRUN    = "app.run(debug=False, port=5000, threaded=True, use_reloader=False)"
OLD_TIMER     = "threading.Timer(1.0,"
NEW_TIMER     = "threading.Timer(1.5,"


def main() -> None:
    if not APP_PY.exists():
        print(f"[ERROR] No se encontró {APP_PY}. Ejecutar desde la carpeta del proyecto.")
        sys.exit(1)

    contenido = APP_PY.read_text(encoding="utf-8")

    # Verificar si el parche ya está aplicado
    if MARKER_FROZEN in contenido:
        print("[OK] El parche ya está aplicado en app.py — no se requiere acción.")
        return

    # Backup
    shutil.copy2(APP_PY, BACKUP)
    print(f"[OK] Backup creado: {BACKUP}")

    # 1. Insertar bloque frozen después de la línea anchor
    if ANCHOR_LINE not in contenido:
        print(f"[ERROR] No se encontró la línea de anclaje: '{ANCHOR_LINE}'")
        print("        Aplicar el parche manualmente — ver PARCHE_app_py.txt")
        sys.exit(1)

    contenido = contenido.replace(
        ANCHOR_LINE,
        ANCHOR_LINE + "\n" + BLOQUE_FROZEN,
        1,  # solo la primera ocurrencia
    )

    # 2. Parchear app.run() con use_reloader=False
    if OLD_APPRUN in contenido:
        contenido = contenido.replace(OLD_APPRUN, NEW_APPRUN, 1)
        print("[OK] app.run() parcheado con use_reloader=False")
    else:
        print("[WARN] No se encontró app.run() para parchear — verificar manualmente")

    # 3. Parchear timer de apertura del navegador
    if OLD_TIMER in contenido:
        contenido = contenido.replace(OLD_TIMER, NEW_TIMER, 1)
        print("[OK] Timer del navegador ajustado a 1.5s")

    # Escribir resultado
    APP_PY.write_text(contenido, encoding="utf-8")
    print(f"[OK] Parche aplicado a {APP_PY}")

    # Verificación
    nuevo = APP_PY.read_text(encoding="utf-8")
    assert MARKER_FROZEN in nuevo, "Verificación fallida: bloque frozen no encontrado"
    assert "use_reloader=False" in nuevo, "Verificación fallida: use_reloader no encontrado"
    print("[OK] Verificación exitosa — app.py listo para empaquetar")


if __name__ == "__main__":
    main()
