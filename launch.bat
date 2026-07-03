@echo off
setlocal enabledelayedexpansion
title Souls of the Reaper - Launcher

set "ROOT=%~dp0"

rem ---- Detect layout: release (exe in root) vs dev build ----
if exist "%ROOT%diablo3.exe" (
    set "EXE=%ROOT%diablo3.exe"
    set "TOML=%ROOT%diablo3.toml"
) else (
    set "EXE=%ROOT%port\out\build\win-amd64-relwithdebinfo\diablo3.exe"
    set "TOML=%ROOT%port\out\build\win-amd64-relwithdebinfo\diablo3.toml"
)

set "GAME=%ROOT%game"
set "APPLY=%ROOT%apply_config.ps1"

rem ---- First-run setup check ----
if not exist "%ROOT%.setup_done" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%setup.ps1"
    exit /b %errorlevel%
)

if not exist "%EXE%" (
    echo ERROR: diablo3.exe not found.
    echo Run setup again or check that the release zip was fully extracted.
    pause
    exit /b 1
)

rem ---------------- CONTROL MODE ----------------
:mode
cls
echo ==================================================
echo    Souls of the Reaper
echo ==================================================
echo.
echo    Control mode:
echo.
echo       [1]  Gamepad                       - standard controller
echo       [2]  Keyboard only                 - WASD + buttons, mouse hidden
echo       [3]  Keyboard + mouse              - WASD + camera/clicks with mouse
echo.
echo       [Q]  Quit
echo.
echo    (Rebind keys/buttons: F4 in-game. The gamepad is
echo     rebound from Diablo's own options menu.)
echo.
choice /c 123Q /n /m "Mode: "
set "MODE=%errorlevel%"

set "MNKMODE=false"
set "MNKMOUSE=false"
set "CURSOR=true"
if "%MODE%"=="4" exit /b 0
if "%MODE%"=="1" ( set "MNKMODE=false" & set "MNKMOUSE=false" & set "CURSOR=true" )
if "%MODE%"=="2" ( set "MNKMODE=true"  & set "MNKMOUSE=false" & set "CURSOR=false" )
if "%MODE%"=="3" goto mode3
goto rtp

:mode3
set "MNKMODE=true"
set "MNKMOUSE=true"
echo.
echo    Mode 3: mouse controls the camera and clicks act as triggers/stick.
echo    Mouse cursor:
echo       [1]  Visible    (can aim/click on screen)
echo       [2]  Hidden     (smoother, gamepad-like feel)
choice /c 12 /n /m "Cursor: "
if "%errorlevel%"=="1" ( set "CURSOR=true" ) else ( set "CURSOR=false" )
goto rtp

rem ---------------- FPS + RENDER PATH ----------------
:rtp
cls
echo ==================================================
echo    Render and FPS
echo ==================================================
echo.
echo    ROV:
echo.
echo       [1]   30 fps
echo       [2]   60 fps
echo       [3]  120 fps
echo       [4]  144 fps
echo.
echo    RTV:
echo.
echo       [5]   60 fps
echo       [6]  120 fps
echo       [7]  144 fps
echo       [8]  240 fps
echo.
echo       [B]   Back
echo.
choice /c 12345678B /n /m "Option: "
set "OPT=%errorlevel%"

set "DFIX=false"
if "%OPT%"=="9" goto mode
if "%OPT%"=="1" ( set "RTP=rov" & set "FPS=30"  & set "VS=true"  )
if "%OPT%"=="2" ( set "RTP=rov" & set "FPS=60"  & set "VS=true"  )
if "%OPT%"=="3" ( set "RTP=rov" & set "FPS=120" & set "VS=false" )
if "%OPT%"=="4" ( set "RTP=rov" & set "FPS=144" & set "VS=false" )
if "%OPT%"=="5" ( set "RTP=rtv" & set "FPS=60"  & set "VS=true"  )
if "%OPT%"=="6" ( set "RTP=rtv" & set "FPS=120" & set "VS=false" )
if "%OPT%"=="7" ( set "RTP=rtv" & set "FPS=144" & set "VS=false" )
if "%OPT%"=="8" ( set "RTP=rtv" & set "FPS=240" & set "VS=false" )

powershell -NoProfile -ExecutionPolicy Bypass -File "%APPLY%" ^
  -Toml "%TOML%" -Fps %FPS% -Vsync %VS% -Rtp %RTP% ^
  -MnkMode %MNKMODE% -MnkMouse %MNKMOUSE% -CursorVisible %CURSOR% -DepthFix %DFIX%

echo.
echo Launching... (%FPS% fps, %RTP%, mode %MODE%)
start "" "%EXE%" --game_data_root "%GAME%"
exit /b 0
