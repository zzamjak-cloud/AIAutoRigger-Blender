@echo off
rem Windows 에서는 .py 를 직접 실행할 수 없어 python 으로 감싼다 (테스트 전용)
python "%~dp0fake_ai_cli.py" %*
