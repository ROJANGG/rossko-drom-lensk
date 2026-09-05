@echo off
cd /d %~dp0
py -m pip install requests
py check_rossko_link.py
pause
