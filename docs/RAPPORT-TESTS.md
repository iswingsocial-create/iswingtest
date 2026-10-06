# Rapport de tests — 2026-10-02

Exécutés ici (Django 5.1, SQLite temporaire) :

- inscription refusée si moins de 18 ans
- like réciproque crée un seul match
- quota de 10 likes verrouillé côté serveur
- photo privée inaccessible sans autorisation (HTTP 403)
- webhook de paiement refusé sans prestataire configuré (HTTP 503)
- confirmation navigateur limitée aux boutons `data-confirm`
- import démo deux fois : 5 comptes, 5 images, 2 matchs, 3 messages, second import sans doublon

Non exécutés ici :

- installation Windows sur machine propre
- VPS Hostinger, HTTPS, SMTP
- téléphone réel, PWA iPhone, notifications push
- cycle de paiement réel (prestataire non raccordé)
- restauration PostgreSQL

# Rapport de tests — médias et intégrations, 2026-10-05

73 tests Django OK, dont la suite précédente et 14 tests nouveaux.

Exécutés ici avec FFmpeg 7 (pas des captures d'iPhone ou d'Android) :

- HEVC paysage et portrait, WebM VP9, rotation displaymatrix, audio AAC, HDR SMPTE 2084 vers H.264 yuv420p
- le MP4 publié contient `ftyp`, la copie source sous `incoming` disparaît après succès
- un fichier endommagé reste en échec, sans piste vidéo publiée
- refus logique au-delà de 600 s et de 2 000 000 001 octets, sans fabriquer ces fichiers
- pas d'agrandissement d'une petite vidéo
- HEIC et AVIF synthétiques (libheif), GIF animé refusé puis WebP si confirmé, SVG et PDF refusés
- deux masques gravés dans les pixels JPEG, miniature distincte
- média privé et miniature : HTTP 403, y compris avec `Range` ; le propriétaire reçoit 206
- morceau repris sans réécriture, puis annulation
- secret laissé vide conservé ; clé Stripe live refusée en mode test sans appel de paiement
- ouvrir Configuration n'envoie pas une campagne programmée
- robots.txt interdit `/profil/` et `/photos/`
- charge push sans nom ni extrait ; déconnexion et changement de compte désactivent l'appareil

Non exécutés, donc non annoncés comme réussis :

- lecture sur Safari iPhone ou Chrome Android
- fichier réel de 10 minutes ou de 2 Go
- SMTP, Stripe live, Analytics, Search Console, Meta Pixel
- réception push sur un téléphone
- Celery, Redis, S3 : non installés
