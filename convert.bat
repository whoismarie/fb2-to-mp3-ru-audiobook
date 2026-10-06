@echo off
rem Drag an .fb2 file onto this to convert it. Extra options can be added after %*
python "%~dp0fb2_to_mp3.py" %*
pause
