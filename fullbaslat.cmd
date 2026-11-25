@echo off
rem Full start of the live demo: sets everything up, closes an old demo, opens the dashboard.
rem Usage:  fullbaslat.cmd   [-Realistic] [-NoBrowser]
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0fullbaslat.ps1" %*
