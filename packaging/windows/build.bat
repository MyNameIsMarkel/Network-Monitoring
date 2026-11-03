@echo off
REM Compila el instalador de Windows en local. Requiere Python 3.10+ e Inno Setup 6.
cd /d "%~dp0\..\.."
python -m pip install --upgrade pip || exit /b 1
python -m pip install -r requirements.txt pyinstaller || exit /b 1
python -m PyInstaller packaging\netmon.spec --noconfirm --clean || exit /b 1
set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% (
  echo Inno Setup 6 no encontrado. Descargalo de https://jrsoftware.org/isdl.php
  echo La version portable esta en dist\NetworkMonitoring\NetworkMonitoring.exe
  exit /b 1
)
%ISCC% packaging\windows\installer.iss || exit /b 1
echo.
echo Instalador listo en dist\
