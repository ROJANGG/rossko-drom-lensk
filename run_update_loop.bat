@echo off
cd /d %~dp0
py -m pip install -r requirements.txt
py update_prices.py --config config.json --loop 3600
pause
