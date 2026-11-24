@echo off
cd /d E:\derivatives_bot
:loop
python dashboard.py
timeout /t 5
goto loop
