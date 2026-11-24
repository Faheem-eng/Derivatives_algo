@echo off
cd /d E:\derivatives_bot
set MODE=shadow
:loop
python main.py
echo Bot band hua. 10 sec mein dobara chalu hoga. Rokne ke liye is window ko band karo.
timeout /t 10
goto loop