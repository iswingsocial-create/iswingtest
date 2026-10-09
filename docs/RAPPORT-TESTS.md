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

# Rapport de tests — messagerie, 2026-10-06

97 tests Django OK (`python manage.py test swingapp`).

Exécutés ici :

- le fil n'affiche plus « Message object » : le contexte s'appelle `thread_messages`
- les deux participants voient l'avatar public approuvé de l'auteur, y compris dans le poll
- une photo privée jointe crée un PhotoGrant pour l'autre participant ; il ouvre la photo (200) et voit la miniature ; une autre photo privée reste en 403 ; un droit révoqué est rouvert au nouvel envoi
- essai : téléphone, e-mail et @pseudo sont refusés et non enregistrés ; « né le 12.05.1990 » et « j'ai 2 chiens » passent
- premium : l'e-mail est envoyé et l'avis de responsabilité s'affiche pour l'expéditeur seulement
- le quota reste à 2 messages par match et par côté

Non exécutés : téléphone réel, Stripe, SMTP, S3, Celery.

# Rapport de tests — messagerie visuelle, photos de match, consentement, partenaire, 2026-10-07

Suite `python manage.py test swingapp` : 105 tests OK.

Exécutés ici :

- la liste Messages montre l'avatar, le nom, l'aperçu, l'heure et la classe `unread` ; ouvrir le fil retire le non-lu
- un message crée une Notice `kind=message` pour le destinataire seulement, avec lien vers le fil ; la cloche compte les non-lues
- un match ouvert rend les photos privées visibles ; hors match elles restent refusées, sauf PhotoGrant explicite
- inscription, invitation et envoi de média : une seule case, qui coche conditions, contenu intime, médias et communications
- le partenaire crée un mot de passe sur son e-mail, sans second profil ; ses messages s'affichent « chave (monica) », ceux du titulaire « chave » ; le quota de messages reste commun

Non exécutés : téléphone réel, Stripe, SMTP, S3, Celery.

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

# Rapport de tests — masques et écran médias, 2026-10-07

Exécutés ici :

- trois autocollants (visage souriant, diable, ananas) gravés dans les pixels, distincts les uns des autres
- le flou ovale laisse les coins du cadre nets et change le centre
- l'écran d'envoi sépare photo et vidéo et n'énumère plus les extensions
- la phrase « ajustée si possible, sans déformation » n'est plus dans fr/en/es
- /legal/medias/ décrit les limites (poids, 2 560 pixels, 10 minutes, formats) en français, anglais et espagnol

Non exécutés : téléphone réel, Stripe, SMTP, S3, Celery.

# Rapport de tests — badges, certification, avis, 2026-10-07

Exécutés : emojis 😊 😈 🍍 gravés, badges essai/membre/certifié, certification privée revue en gestion, profil test peut écrire à un membre réel, avis en cartes séparées et traduits fr/en/es à l’ouverture.
Non exécutés : téléphone réel, Stripe, SMTP, S3, Celery.

# Rapport de tests — orientations, courriel, médias privés, 2026-10-08

Exécutés : deux orientations de couple visibles et modifiables, interrupteur de courriel d’inscription désactivé par défaut puis envoi réel, miniature privée dans le fil et accès du destinataire. 113 tests Django OK.
Non exécutés : téléphone réel, Stripe, SMTP, S3, Celery.

# Rapport de tests — fiche du match, voyage, villes, 2026-10-08

Exécutés : lien vers la fiche depuis le fil, l’inbox et les matchs ; voyage à Montréal visible dans ce secteur puis retour automatique à Lyon ; Saint-Sauveur (CA) et villes de 10 000 habitants et plus. 116 tests Django OK.
Non exécutés : téléphone réel, Stripe, SMTP, S3, Celery.

# Rapport de tests — module Entreprises, 2026-10-08

Exécutés : module éteint par défaut puis activé depuis la gestion ; compte entreprise absent de Découvrir et sans like ; événement, inscription, liste d’attente, invité anonyme sans courriel ; badge seulement si justificatif accepté et abonnement actif ; push avec aperçu et facture interne ; billetterie en attente sans encaissement. 118 tests Django OK.
Non exécutés : téléphone réel, Stripe, SMTP, S3, Celery, encaissement de billets.

# Rapport de tests — correctifs v8, 2026-10-09

Exécutés : libellé Voir la fiche, redirection après like depuis une fiche, onglet Couple seulement pour un couple, libellés partenaire en espagnol, filtres d’âge, notifications et médias traduits, relation sérieuse enregistrée et filtrée. Les liens de fiche depuis matchs et messages étaient déjà en place. 120 tests Django OK.
Non exécutés : téléphone réel, Stripe, SMTP, S3, Celery.
