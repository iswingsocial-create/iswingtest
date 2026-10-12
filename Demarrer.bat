@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat (
  echo Lancez d'abord Installer.bat
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
echo.
echo Site     http://localhost:8000
echo Gestion  http://localhost:8000/gestion/
echo Admin    http://localhost:8000/admin/
echo Laissez cette fenetre ouverte. Ctrl+C pour arreter.
echo.
python manage.py migrate
if errorlevel 1 (
  echo La mise a jour de la base a echoue.
  pause
  exit /b 1
)
python manage.py runserver 127.0.0.1:8000
pause
