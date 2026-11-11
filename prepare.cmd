@echo off
rem Windowless entry point for RecompLauncher: %1 is the player's disc image.
powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0setup.ps1" -Prepare -Iso %1
exit /b %ERRORLEVEL%
