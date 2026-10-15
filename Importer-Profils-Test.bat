@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat (
  echo Environnement absent. Lancez Installer.bat d'abord.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
echo.
echo 1 Generer un lot : python manage.py generate_test_batch --batch-id NOM --cities "Paris|FR|48.85341|2.34880" --per-city 100 --image-dir DOSSIER
echo 2 Verifier un ZIP : python manage.py verify_test_batch lot.zip
echo 3 Importer : python manage.py import_test_batch lot.zip
echo 4 Etat : python manage.py test_batch_status NOM
echo 5 Supprimer : python manage.py delete_test_batch NOM
echo.
echo Refusé si ISWING_ENV=production. Les comptes restent is_demo=True.
echo Interface : http://127.0.0.1:8000/gestion/profils-test/
echo.
pause
