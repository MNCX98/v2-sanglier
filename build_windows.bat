@echo off
setlocal
cd /d "%~dp0"

echo [1/3] Installation des dependances...
py -m pip install --upgrade pip
if errorlevel 1 goto error
py -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto error

echo [2/3] Nettoyage des anciennes compilations...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

 echo [3/3] Compilation de DofusAuto...
py -m PyInstaller --noconfirm --clean --windowed --onedir --contents-directory . --name DofusAuto --add-data "assets;assets" --add-data "config.json;." main.py
if errorlevel 1 goto error

echo.
echo Compilation terminee. Executable : dist\DofusAuto\DofusAuto.exe
pause
exit /b 0

:error
echo.
echo Echec de la compilation. Verifie Python, pip et le message ci-dessus.
pause
exit /b 1
