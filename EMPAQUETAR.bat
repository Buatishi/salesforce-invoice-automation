@echo off
setlocal enabledelayedexpansion

:: CRITICO: cambiar al directorio donde esta este .bat
cd /d "%~dp0"

echo.
echo ================================================
echo   InvoiceFlow Bot v1.4 - Empaquetado .exe
echo   Directorio: %~dp0
echo ================================================
echo.

:: Verificar carpeta correcta
if not exist "app.py" (
    echo [ERROR] No se encontro app.py en esta carpeta.
    echo         Ruta actual: %CD%
    echo         Mover EMPAQUETAR.bat a la carpeta raiz del proyecto.
    pause
    exit /b 1
)
if not exist "requirements.txt" (
    echo [ERROR] No se encontro requirements.txt en esta carpeta.
    echo         Ruta actual: %CD%
    pause
    exit /b 1
)

:: Verificar Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python no esta instalado o no esta en el PATH.
    pause
    exit /b 1
)
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo [OK] Python %PYVER% detectado.
echo [OK] Directorio: %CD%

:: Crear entorno virtual
echo.
echo [1/7] Creando entorno virtual limpio...
if exist "venv_build" rmdir /s /q venv_build
python -m venv venv_build
if errorlevel 1 ( echo [ERROR] No se pudo crear el entorno virtual. & pause & exit /b 1 )
echo [OK] Entorno virtual creado.

:: Activar entorno virtual
call "%~dp0venv_build\Scripts\activate.bat"
if errorlevel 1 ( echo [ERROR] No se pudo activar el entorno virtual. & pause & exit /b 1 )

:: Instalar dependencias (ignorar warning de pip, solo falla si errorlevel >= 1)
echo.
echo [2/7] Instalando dependencias...
"%~dp0venv_build\Scripts\python.exe" -m pip install --quiet --upgrade pip 2>nul
"%~dp0venv_build\Scripts\pip.exe" install --quiet -r "%~dp0requirements.txt"
if errorlevel 1 ( echo [ERROR] Fallo al instalar dependencias. & pause & exit /b 1 )
echo [OK] Dependencias instaladas.

:: Instalar PyInstaller
echo.
echo [3/7] Instalando PyInstaller...
"%~dp0venv_build\Scripts\pip.exe" install --quiet "pyinstaller>=6.0.0"
if errorlevel 1 ( echo [ERROR] Fallo al instalar PyInstaller. & pause & exit /b 1 )
echo [OK] PyInstaller instalado.

:: Instalar Chromium
echo.
echo [4/7] Instalando Chromium de Playwright...
echo       Puede tardar 2-3 minutos (descarga ~130 MB)
"%~dp0venv_build\Scripts\playwright.exe" install chromium
if errorlevel 1 ( echo [ERROR] Fallo al instalar Chromium. & pause & exit /b 1 )
echo [OK] Chromium instalado.

:: Detectar ruta de Chromium
echo.
echo [5/7] Detectando ruta de Chromium...
set MSPLAYWRIGHT_DIR=
for /f "delims=" %%p in ('"%~dp0venv_build\Scripts\python.exe" -c "import os; p=os.path.join(os.environ.get(\"LOCALAPPDATA\",\"\"), \"ms-playwright\"); print(p if os.path.isdir(p) else \"\")"') do set MSPLAYWRIGHT_DIR=%%p
if "!MSPLAYWRIGHT_DIR!"=="" (
    echo [WARN] No se detecto ms-playwright. Chromium debera copiarse manualmente.
) else (
    echo [OK] Chromium en: !MSPLAYWRIGHT_DIR!
)

:: Verificar archivos necesarios
echo.
echo [6/7] Verificando archivos del proyecto...
if not exist "aplicar_parche.py" ( echo [ERROR] Falta aplicar_parche.py & pause & exit /b 1 )
if not exist "invoiceflow.spec"  ( echo [ERROR] Falta invoiceflow.spec & pause & exit /b 1 )

if not exist ".env.example" (
    echo SALESFORCE_USERNAME=COMPLETAR@email.com > .env.example
    echo SALESFORCE_PASSWORD=COMPLETAR >> .env.example
    echo EMAIL_DESTINATARIO= >> .env.example
    echo EMAIL_REMITENTE= >> .env.example
    echo EMAIL_APP_PASSWORD= >> .env.example
)

:: Aplicar parche si no esta aplicado
"%~dp0venv_build\Scripts\python.exe" -c "import pathlib; c=pathlib.Path('app.py').read_text(encoding='utf-8'); exit(0 if 'frozen' in c else 1)" >nul 2>&1
if errorlevel 1 (
    echo Aplicando parche frozen a app.py...
    "%~dp0venv_build\Scripts\python.exe" aplicar_parche.py
    if errorlevel 1 ( echo [ERROR] Fallo al aplicar el parche. & pause & exit /b 1 )
) else (
    echo [OK] Parche frozen ya aplicado.
)
echo [OK] Todo verificado.

:: Empaquetar
echo.
echo [7/7] Empaquetando con PyInstaller (3-5 minutos)...
if exist "dist\InvoiceFlowBot" rmdir /s /q "dist\InvoiceFlowBot"
if exist "build\InvoiceFlowBot" rmdir /s /q "build\InvoiceFlowBot"

"%~dp0venv_build\Scripts\pyinstaller.exe" invoiceflow.spec --noconfirm --clean
if errorlevel 1 (
    echo.
    echo [ERROR] PyInstaller fallo. Revisa los mensajes arriba.
    pause
    exit /b 1
)

:: Copiar archivos al dist
set DIST_DIR=%~dp0dist\InvoiceFlowBot
if exist "selectores.json"            copy /y "selectores.json"            "!DIST_DIR!\" >nul
if exist ".env.example"               copy /y ".env.example"               "!DIST_DIR!\.env.example" >nul
if exist "CONFIGURAR_PRIMERA_VEZ.bat" copy /y "CONFIGURAR_PRIMERA_VEZ.bat" "!DIST_DIR!\" >nul
if not exist "!DIST_DIR!\logs"        mkdir "!DIST_DIR!\logs"

:: Copiar Chromium
if not "!MSPLAYWRIGHT_DIR!"=="" (
    if exist "!MSPLAYWRIGHT_DIR!" (
        echo Copiando Chromium al bundle (1-2 minutos)...
        xcopy "!MSPLAYWRIGHT_DIR!" "!DIST_DIR!\_internal\ms-playwright\" /E /I /Q /Y >nul 2>&1
        if errorlevel 1 ( echo [WARN] No se pudo copiar Chromium. ) else ( echo [OK] Chromium copiado. )
    )
)

:: Crear lanzador
echo @echo off > "!DIST_DIR!\ABRIR_PANEL.bat"
echo cd /d "%%~dp0" >> "!DIST_DIR!\ABRIR_PANEL.bat"
echo start "" "InvoiceFlowBot.exe" >> "!DIST_DIR!\ABRIR_PANEL.bat"
echo timeout /t 2 /nobreak ^>nul >> "!DIST_DIR!\ABRIR_PANEL.bat"
echo start http://localhost:5000 >> "!DIST_DIR!\ABRIR_PANEL.bat"

:: Crear ZIP
echo.
echo Creando ZIP...
if exist "%~dp0dist\InvoiceFlowBot_v1.4.zip" del "%~dp0dist\InvoiceFlowBot_v1.4.zip"
powershell -command "Compress-Archive -Path '%~dp0dist\InvoiceFlowBot\*' -DestinationPath '%~dp0dist\InvoiceFlowBot_v1.4.zip' -Force" >nul 2>&1
if errorlevel 1 ( echo [WARN] ZIP no creado. Comprimir manualmente dist\InvoiceFlowBot\ ) else ( echo [OK] ZIP creado. )

call "%~dp0venv_build\Scripts\deactivate.bat" 2>nul

echo.
echo ================================================
echo   COMPLETADO
echo   Ejecutable: dist\InvoiceFlowBot\InvoiceFlowBot.exe
echo   ZIP listo:  dist\InvoiceFlowBot_v1.4.zip
echo ================================================
echo.
pause
