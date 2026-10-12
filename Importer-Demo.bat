@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python manage.py import_demo
echo Comptes TEST, mot de passe Test-iSwing-1!
echo Suppression : python manage.py purge_demo
pause
