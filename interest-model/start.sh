#!/usr/bin/env bash
# 个人兴趣模型 · 一键启动（Linux / macOS）
# 首次运行会创建虚拟环境并安装依赖（约 2GB，含语义模型），之后每次直接启动。
set -e
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "需要 Python 3.10+，请先安装：https://www.python.org/downloads/"
  exit 1
fi

if [ ! -d .venv ]; then
  echo "[1/2] 首次运行：创建环境并安装依赖（几分钟，只需一次）…"
  python3 -m venv .venv
  ./.venv/bin/pip install --quiet --upgrade pip
  ./.venv/bin/pip install --quiet -r requirements.txt || \
    ./.venv/bin/pip install --quiet -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
fi

echo "[2/2] 启动中，浏览器会自动打开仪表盘。按 Ctrl+C 退出。"
exec ./.venv/bin/python daemon/app.py "$@"
