@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo =============================================
echo   考勤三方对账工具 - 启动器
echo =============================================
echo.

REM ============ 1. 检测 Python ============
set "PY="
python --version >nul 2>&1
if not errorlevel 1 set "PY=python"
if defined PY goto py_ok
py -3 --version >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if defined PY goto py_ok
goto no_python
:py_ok
echo [OK] Python 环境:
%PY% --version

REM ============ 2. 检测并安装依赖 ============
echo.
echo [*] 检测依赖包...
%PY% -c "import openpyxl, opencc, fitz, rapidocr_onnxruntime, PIL, numpy" >nul 2>&1
if not errorlevel 1 goto deps_ok
echo [!] 缺少依赖，开始自动安装（首次需数分钟，请耐心等待）...
%PY% -m pip install -r requirements.txt
if errorlevel 1 goto pip_failed
echo [OK] 依赖安装完成
:deps_ok

REM ============ 3. 检查源文件目录 ============
if not exist "inputfile" mkdir "inputfile"
dir /b "inputfile\*.xlsx" "inputfile\*.xls" "inputfile\*.pdf" >nul 2>&1
if not errorlevel 1 goto have_files
echo.
echo [提示] inputfile 目录中未发现源文件
echo        请将三个源文件放入 inputfile 目录
echo        文件名可随意，程序自动识别
:have_files

echo.
echo [*] 开始运行对账程序...
echo.
%PY% main.py %*

echo.
echo =============================================
echo   程序执行完毕，报告已保存到 output 目录
echo =============================================
pause
exit /b 0

REM ============ 失败分支 ============
:no_python
echo [!] 未检测到 Python，尝试自动安装...
where winget >nul 2>&1
if errorlevel 1 goto no_winget
winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements --silent
if errorlevel 1 goto winget_failed
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if defined PY goto installed_ok
python --version >nul 2>&1
if not errorlevel 1 set "PY=python"
if defined PY goto installed_ok
goto still_no_python
:installed_ok
echo [OK] Python 已安装。请重新运行本程序。
pause
exit /b 0

:no_winget
echo [X] 系统未安装 winget，无法自动安装 Python
echo     请手动访问 https://www.python.org/downloads/ 安装 Python 3.10+
goto fail
:winget_failed
echo [X] winget 安装 Python 失败
goto fail
:still_no_python
echo [X] 安装后仍无法找到 Python
goto fail
:pip_failed
echo [X] 依赖安装失败，请检查网络连接后重试
goto fail
:fail
pause
exit /b 1
