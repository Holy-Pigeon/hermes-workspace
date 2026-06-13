#!/bin/bash
# 模拟持仓收盘盯市 cron 包装器：固定用 homebrew python3（akshare 在那）
cd /Users/xiaogexu/hermes-workspace/paper-trading || exit 1
/opt/homebrew/bin/python3 daily_mark.py 2>&1
