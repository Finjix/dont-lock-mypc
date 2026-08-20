@echo off
setlocal EnableExtensions
cd /d "%~dp0"

rem 注意：本文件必须保存为 ANSI/GBK 编码（中文 Windows 默认），
rem 不要用 UTF-8 保存，否则中文注释会导致 cmd 解析错乱。
title 臭网易不要锁我电脑

rem ============================================================
rem  启动器：自动寻找 Python 并运行 dont_lock.py
rem  常用命令：
rem    start.bat                 前台运行（默认每 30 秒微移一次鼠标）
rem    start.bat -i 60           间隔改为 60 秒
rem    start.bat --idle-aware    仅当电脑空闲达到间隔时才微移
rem    start.bat --hidden        后台无窗口运行
rem    start.bat --stop          停止正在运行的实例
rem ============================================================

set "SCRIPT=dont_lock.py"

rem ---- 定位 Python：优先 py 启动器，其次 python ----
set "PYCMD="
py -3 -c "" >nul 2>nul && set "PYCMD=py -3"
if not defined PYCMD python -c "" >nul 2>nul && set "PYCMD=python"
if not defined PYCMD (
    echo [错误] 未检测到 Python 3，请先安装：https://www.python.org/downloads/
    echo        安装时记得勾选 "Add Python to PATH"。
    pause
    exit /b 1
)

%PYCMD% "%SCRIPT%" %*
set "EC=%ERRORLEVEL%"

if /i "%~1"=="--hidden" (
    rem --hidden 模式下脚本立即转入后台，停留 3 秒展示提示后自动关闭
    timeout /t 3 /nobreak >nul 2>&1
) else if /i "%~1"=="--stop" (
    pause
) else if %EC% NEQ 0 (
    echo.
    echo [提示] 脚本已退出，退出码 %EC%。
    pause
)

endlocal & exit /b %EC%
