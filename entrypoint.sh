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
from django.utils import timezone

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

# Comptes de test pour la messagerie (actif si SEED_TEST_ACCOUNTS=1)
if os.environ.get("SEED_TEST_ACCOUNTS") == "1":
    from datetime import date
    from swingapp.models import Profile, Match
    from swingapp.services import sync_trial

    now2 = timezone.now()
    seeds = [
        {"email": os.environ.get("TEST1_EMAIL", "melange1@iswing.test"),
         "password": os.environ.get("TEST1_PASSWORD", "TestMelange1!"),
         "name": "Alex & Jo"},
        {"email": os.environ.get("TEST2_EMAIL", "melange2@iswing.test"),
         "password": os.environ.get("TEST2_PASSWORD", "TestMelange2!"),
         "name": "Sam & Lou"},
    ]
    test_profiles = []
    for s in seeds:
        tu = User.objects.filter(email=s["email"]).first()
        if tu is None:
            tu = User.objects.create_user(
                email=s["email"], password=s["password"],
                birth_date=date(1990, 5, 5),
                terms_accepted_at=now2, adult_declared=True,
                email_verified_at=now2, intimate_consent=True,
            )
            print("test user created:", s["email"])
        else:
            tu.set_password(s["password"])
            tu.is_active = True
            tu.adult_declared = True
            if not tu.terms_accepted_at:
                tu.terms_accepted_at = now2
            if not tu.email_verified_at:
                tu.email_verified_at = now2
            tu.save()
            print("test user exists, password reset:", s["email"])
        tp, _ = Profile.objects.get_or_create(user=tu, defaults={"display_name": s["name"]})
        tp.display_name = s["name"]
        tp.kind = "couple"
        tp.city = "Montreal"
        tp.country = "CA"
        tp.bio = "Compte de test pour la messagerie."
        tp.activities = "melangisme"
        if not tp.validated_at:
            tp.validated_at = now2
        tp.save()
        sync_trial(tp)
        test_profiles.append(tp)
    pa, pb = sorted(test_profiles, key=lambda p: p.id)
    m, mcreated = Match.objects.get_or_create(profile_a=pa, profile_b=pb)
    if m.closed_at:
        m.closed_at = None
        m.save(update_fields=["closed_at"])
    print("test match ready:", m.id, "created:", mcreated)
PYEOF

exec gunicorn iswing.wsgi:application --bind "0.0.0.0:${PORT:-8000}" --workers 2
