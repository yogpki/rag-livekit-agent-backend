@echo off
:: 脚本名称：restart_main_agent.bat

:: 设置虚拟环境路径
set VENV_PATH=simpleenv\Scripts\activate

:: 设置 Python 脚本路径和参数
set SCRIPT_PATH=main_assist_agent.py
set SCRIPT_ARGS=dev

:loop
:: 激活虚拟环境
call %VENV_PATH%
if errorlevel 1 (
    echo Failed to activate virtual environment. Exiting...
    exit /b
)

:: 清屏显示提示信息
echo Running %SCRIPT_PATH% with args: %SCRIPT_ARGS%
echo Press [R] to restart the script.
echo Press [Q] to quit.

:: 启动 Python 脚本
start /b python %SCRIPT_PATH% %SCRIPT_ARGS%

:: 无限循环等待按键
choice /c RQ /n /m "Press R to restart, Q to quit: "

:: 检测按键
if errorlevel 2 goto quit
if errorlevel 1 goto restart

:restart
:: 停止 Python 进程
taskkill /f /im python.exe >nul 2>&1
echo Restarting script...
goto loop

:quit
:: 退出脚本
taskkill /f /im python.exe >nul 2>&1
echo Exiting...
exit
