@echo off
cd /d "%~dp0"
echo starting>> "%~dp0launch-log.txt"
cmd /k call "%~dp0launch-workbench.bat"
