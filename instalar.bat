@echo off
echo ============================================
echo  InvoiceFlow Bot v1.3 -- Instalacion
echo ============================================
echo.
echo By - Bautishi -
echo.

:: Verificar que Python este instalado
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python no esta instalado o no esta en el PATH.
    echo         Descargalo desde https://www.python.org/downloads/
    echo         Asegurate de marcar "Add Python to PATH" al instalar.
    pause
    exit /b 1
)

echo Instalando dependencias Python...
pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Fallo al instalar dependencias.
    pause
    exit /b 1
)

echo.
echo Instalando navegador Chromium para Playwright...
playwright install chromium
if errorlevel 1 (
    echo [ERROR] Fallo al instalar Chromium.
    pause
    exit /b 1
)

:: Crear .env desde .env.example si no existe
if not exist .env (
    if exist .env.example (
        copy .env.example .env >nul
        echo.
        echo [OK] Archivo .env creado desde .env.example.
        echo      IMPORTANTE: edita .env con tus credenciales antes de ejecutar el bot.
    ) else (
        echo [AVISO] No se encontro .env.example. Crea .env manualmente.
    )
) else (
    echo [OK] Archivo .env ya existe -- no se sobreescribe.
)

echo.
echo ============================================
echo  Instalacion completada -- InvoiceFlow Bot v1.3
echo.
echo  Para ejecutar el bot:  python app.py
echo  Para verificar tipos:  mypy .
echo  Para correr tests:     python testing/test_suite.py
echo.
echo  Funcionalidades v1.3:
echo    - ExcelWriter persistente (menos I/O en corridas largas)
echo    - Escritura atomica de progreso.json
echo    - Cache de selectores por mtime (sin I/O en reconexiones)
echo    - Timeouts diferenciados por operacion
echo    - Reconexion automatica de sesion Salesforce
echo    - Validacion de tamano de PDFs antes de subir
echo ============================================
pause