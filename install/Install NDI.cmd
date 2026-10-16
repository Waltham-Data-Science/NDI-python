@echo off
rem Double-click this file to install NDI (Windows).
rem
rem It runs install-ndi.ps1 from the same folder, or downloads it if this file
rem was saved on its own, and waits at the end so you can read what happened.
rem -ExecutionPolicy Bypass applies to this one run only; it changes no setting.
rem If Windows SmartScreen warns about the file, choose "More info", then "Run anyway".

setlocal
set "SCRIPT=%~dp0install-ndi.ps1"
set "URL=https://raw.githubusercontent.com/Waltham-Data-Science/NDI-python/main/install/install-ndi.ps1"

if exist "%SCRIPT%" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" %*
) else (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12; irm '%URL%' | iex"
)
set "STATUS=%ERRORLEVEL%"

echo.
if "%STATUS%"=="0" (echo Done.) else (echo NDI was not installed; the reason is above.)
pause
exit /b %STATUS%
