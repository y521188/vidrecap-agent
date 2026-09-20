@echo off
rem 一键启动：必须用项目虚拟环境里的解释器——系统 python 没装 pydantic。
rem 用法：双击本文件，或在命令行里运行 `serve.bat`（参数原样传给 vidrecap，如 serve.bat --port 9000）。
cd /d "%~dp0"
.venv\Scripts\python.exe -m vidrecap serve %*
