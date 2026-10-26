#!/bin/bash
# 一键启动：实时捕捉 iPhone 镜像窗口并全屏放大到扩展屏。
# 用法：
#   ./run.sh                # 按 config.py 默认配置（扩展屏[1]）
#   ./run.sh --display 1    # 指定扩展屏
#   ./run.sh --list-displays  # 查看显示器序号
cd "$(dirname "$0")"
exec .venv/bin/python main.py "$@"
