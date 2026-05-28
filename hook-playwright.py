# =============================================================================
# hook-playwright.py — Hook de PyInstaller para Playwright
# =============================================================================

from PyInstaller.utils.hooks import collect_data_files, collect_all

# Recopilar todos los datos de playwright (incluye el driver)
datas, binaries, hiddenimports = collect_all('playwright')

# El driver de Playwright es un binario nativo que necesita ir en binaries
# (no en datas) para preservar sus permisos de ejecución
