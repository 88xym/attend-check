@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo =============================================
echo   考勤三方对账工具 - 启动器
echo =============================================
echo.

REM ---- 1. 检测 Python ----
set "PY=python"
python --version >nul 2>&1
if errorlevel 1 (
    set "PY=py"
    py -3 --version >nul 2>&1
    if errorlevel 1 (
        echo [!] 未检测到 Python，尝试自动安装...
        call :install_python
        if errorlevel 1 (
            echo [X] Python 不可用，请手动安装 Python 3.10+ 后重试
            echo     下载地址: https://www.python.org/downloads/
            pause
            exit /b 1
        )
    )
)
echo [OK] Python 环境:
%PY% --version

REM ---- 2. 检测并安装依赖 ----
echo.
echo [*] 检测依赖包...
%PY% -c "import openpyxl, opencc, fitz, rapidocr_onnxruntime, PIL, numpy" >nul 2>&1
if errorlevel 1 (
    echo [!] 缺少依赖，开始自动安装（首次需数分钟，请耐心等待）...
    %PY% -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [X] 依赖安装失败，请检查网络连接后重试
        pause
        exit /b 1
    )
    echo [OK] 依赖安装完成
) else (
    echo [OK] 依赖完整，无需安装
)

REM ---- 3. 检查源文件目录 ----
if not exist "inputfile" mkdir "inputfile"
dir /b "inputfile\*.xlsx" "inputfile\*.xls" "inputfile\*.pdf" >nul 2>&1
if errorlevel 1 (
    echo.
    echo [提示] inputfile 目录中未发现源文件
    echo        请将三个源文件（原始打卡记录、手工考勤表、单据PDF）放入 inputfile 目录
    echo        文件名可随意，程序自动识别
)

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

REM ---- 子例程: 自动安装 Python ----
:install_python
where winget >nul 2>&1
if errorlevel 1 (
    echo [X] 系统未安装 winget，无法自动安装 Python
    echo     请手动访问 https://www.python.org/downloads/ 安装 Python 3.10+
    exit /b 1
)
echo     使用 winget 安装 Python 3.12...
winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements --silent
if errorlevel 1 (
    echo [X] winget 安装 Python 失败
    exit /b 1
)
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    exit /b 0
)
python --version >nul 2>&1
if errorlevel 1 exit /b 1
exit /b 0
