@echo off
cd /d "%~dp0"
echo iSwing — envois et videos. Laissez cette fenetre ouverte.
echo ffmpeg est requis. ffprobe est optionnel : sans lui, ffmpeg lit le fichier.
echo Apres une conversion reussie, la source est supprimee. Un echec la garde 24 h.
echo Celery et Redis ne sont pas utilises ici. Les quotas de j'aime ne changent pas.
:loop
call ".venv\Scripts\python.exe" manage.py process_outbox
call ".venv\Scripts\python.exe" manage.py process_videos
timeout /t 60 /nobreak >nul
goto loop
