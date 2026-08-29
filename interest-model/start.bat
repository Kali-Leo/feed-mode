@echo off
rem 个人兴趣模型 · 一键启动（Windows，双击即可）
rem 首次运行会创建虚拟环境并安装依赖（约 2GB，含语义模型），之后每次直接启动。
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo 需要 Python 3.10+，请先安装：https://www.python.org/downloads/
  echo 安装时勾选 "Add python.exe to PATH"
  pause
  exit /b 1
)

if not exist .venv (
  echo [1/2] 首次运行：创建环境并安装依赖（几分钟，只需一次）…
  python -m venv .venv
  .venv\Scripts\pip install --quiet --upgrade pip
  .venv\Scripts\pip install --quiet -r requirements.txt
  if errorlevel 1 .venv\Scripts\pip install --quiet -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
)

echo [2/2] 启动中，浏览器会自动打开仪表盘。关闭本窗口即退出。
.venv\Scripts\python daemon\app.py %*
pause
