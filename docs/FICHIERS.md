# Carte des fichiers

- iswing/settings.py : configuration dev/test/prod, SQLite ou PostgreSQL
- platform/models.py : comptes, profils, couples, photos, matchs, messages, quotas, paiements
- platform/services.py : quotas verrouillés, distance, match réciproque, signature webhook
- platform/views.py : parcours web, photos privées, export, suppression, gestion
- templates/ : interface mobile sombre
- static/ : style, script, logo, service worker via vue
- platform/management/commands/import_demo.py : 5 profils TEST
- Installer.bat Demarrer.bat Creer-Admin.bat Importer-Demo.bat : Windows
- docker-compose.yml deploy/ : VPS Hostinger avec Caddy et PostgreSQL
- docs/GUIDE.md : exploitation
