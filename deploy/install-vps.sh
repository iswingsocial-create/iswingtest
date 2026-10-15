#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
test -f .env || cp .env.example .env
docker compose up -d --build
docker compose exec web python manage.py migrate
echo "Définissez SECRET_KEY, POSTGRES_PASSWORD, ALLOWED_HOSTS, domaine et SMTP dans .env"
echo "Puis : docker compose exec web python manage.py createsuperuser"
