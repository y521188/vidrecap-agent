#!/usr/bin/env bash
# 一键启动（Git Bash 用）：必须用项目虚拟环境里的解释器——系统 python 没装 pydantic。
cd "$(dirname "$0")"
exec .venv/Scripts/python.exe -m vidrecap serve "$@"
