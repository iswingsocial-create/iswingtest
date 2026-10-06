#!/bin/sh
# iSwing - script de demarrage (Render / Docker).
# 1. applique les migrations
# 2. cree ou met a jour le compte admin (mot de passe pris de ADMIN_PASSWORD)
# 3. collecte les fichiers statiques
# 4. lance gunicorn
set -e

python manage.py migrate --noinput
python manage.py collectstatic --noinput

python manage.py shell <<'PYEOF'
import os
from django.contrib.auth import get_user_model

User = get_user_model()
email = os.environ.get("ADMIN_EMAIL", "admin@iswing.live")
password = os.environ.get("ADMIN_PASSWORD", "")

u = User.objects.filter(email=email).first()
if u is None:
    u = User.objects.create_superuser(email=email, password=password or None)
    print("admin created:", email)
else:
    u.is_staff = True
    u.is_superuser = True
    u.is_active = True
    u.save(update_fields=["is_staff", "is_superuser", "is_active"])
    print("admin exists, flags ensured:", email)

if password:
    u.set_password(password)
    u.save(update_fields=["password"])
    print("admin password set from ADMIN_PASSWORD")
else:
    print("ADMIN_PASSWORD not set: password unchanged")
PYEOF

exec gunicorn iswing.wsgi:application --bind "0.0.0.0:${PORT:-8000}" --workers 2
