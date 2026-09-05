@echo off
cd /d %~dp0
set TASK_NAME=Rossko_Drom_Update
set SCRIPT=%cd%\update_prices.py
set CONFIG=%cd%\config.json
schtasks /Create /TN "%TASK_NAME%" /SC HOURLY /MO 4 /TR "py \"%SCRIPT%\" --config \"%CONFIG%\"" /F
pause
