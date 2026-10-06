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

# Rapport de tests — apparence, lecture vidéo et clé Stripe, 2026-10-06

74 tests Django OK (suites `swingapp.tests`, `swingapp.test_testlots`, `swingapp.test_media_stack`).

Exécutés ici :

- onglet Apparence : thème Clair enregistré, logo et vignette BDSM remplacés par un PNG servi depuis `data/brand`, remise d'origine d'une vignette, remise de toutes les images sans perdre le thème
- la page Paiements indique le champ « Clé API secrète de test » et `sk_test_`
- une vidéo convertie est H.264 yuv420p, `moov` avant `mdat`, réponse 206 sans `no-store`, et la page membre contient `playsinline`
- une vidéo non prête répond 409 sur `/fichier/` au lieu d'envoyer l'affiche JPEG à la place du fichier vidéo
- une photo JPEG avec orientation EXIF 6 est enregistrée plus haute que large

Non exécutés, donc non annoncés comme réussis :

- lecture sur un ordinateur, un iPhone ou un Android réels (fichiers fabriqués par ffmpeg seulement)
- Stripe, SMTP, S3 et Celery réels

# Rapport de tests — likes et quotas, 2026-10-06

87 tests Django OK (`python manage.py test swingapp`).

Exécutés ici :

- 10 likes distincts comptés, le 11e refusé (`likes_exhausted`)
- deux POST simultanés avec la même `client_key` : 1 like, quota +1
- re-like : `already:true`, quota inchangé
- 2 messages par participant, le 3e refusé des deux côtés
- nouveau jour : quota likes remis
- Découvrir vide distinct du bandeau de quota
- Chromium headless 360×640 (pas un téléphone) : double tap, un seul POST avec `client_key`, carte retirée en 68 ms, compteur 10 puis 9

Non exécutés : tap sur un téléphone physique. Stripe, S3 et Celery toujours non raccordés.
