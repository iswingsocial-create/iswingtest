@echo off
setlocal
cd /d "%~dp0"
echo Installation iSwing
where py >nul 2>&1 && set PY=py -3 || set PY=python
%PY% -m venv .venv
if errorlevel 1 goto fail
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 goto fail
if not exist data mkdir data
if not exist .env (
  echo ISWING_ENV=development> .env
  echo DEBUG=1>> .env
  echo SECRET_KEY=changez-moi>> .env
  echo ALLOWED_HOSTS=localhost,127.0.0.1>> .env
)
python manage.py migrate
if errorlevel 1 goto fail
python manage.py collectstatic --noinput
echo.
echo Site membres : http://localhost:8000
echo Gestion : http://localhost:8000/gestion/
echo Administration technique : http://localhost:8000/admin/
echo Le mot de passe saisi dans le terminal peut rester invisible.
echo Lancez Creer-Admin.bat puis Demarrer.bat
pause
goto end
:fail
echo Echec de l'installation. Verifiez Python 3.10+ et la connexion.
pause
exit /b 1
:end
