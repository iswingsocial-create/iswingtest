@echo off
cd /d "%~dp0"
call .venv\Scripts\activate.bat
echo Creation d'un administrateur. La saisie du mot de passe peut etre invisible.
python manage.py createsuperuser
pause
