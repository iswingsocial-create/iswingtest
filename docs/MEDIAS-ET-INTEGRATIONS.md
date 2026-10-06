# Médias, stockage et intégrations

Ce guide décrit ce qui fonctionne dans cette livraison, et ce qui n'est pas branché.

## Vidéo

- Durée maximale initiale : 600 secondes. Taille source maximale : 2 000 000 000 octets. Les deux sont vérifiées sur le serveur et se règlent dans Gestion, Configuration, Médias.
- Le conteneur est lu avec ffprobe s'il est installé, sinon avec `ffmpeg -i`. L'extension seule ne suffit pas.
- Conversion : H.264, AAC 128 kb/s s'il y a du son, yuv420p, `+faststart`, sans agrandir. 1080p au plus, paysage, portrait ou carré. Environ 6 Mb/s à 1080p30, plafonné à 8 Mb/s. Le poids affiché est une estimation, puis la taille réelle.
- Une source HDR (SMPTE 2084) est ramenée en SDR si les filtres `zscale` et `tonemap` existent.
- La rotation `displaymatrix` est appliquée par ffmpeg avant le redimensionnement. Les pixels d'origine ne sont pas publiés.
- États : Importation, Vérification, Conversion, En modération, Disponible, Échec.
- L'envoi navigateur se fait par morceaux de 1 Mo, avec reprise, annulation et nouvel essai. Un envoi simple de plus de 60 Mo est refusé par Django : il faut le formulaire vidéo, qui découpe le fichier.
- Après une conversion réussie, la source dans `data/private_media/incoming` est supprimée. En cas d'échec, elle reste 24 heures pour le bouton Réessayer, puis `Planifier.bat` l'efface. Rien d'illisible n'est publié.
- La lecture passe par `/photos/<id>/fichier/` après contrôle des droits, avec les requêtes `Range`.
- Le masquage des visages n'existe pas pour la vidéo.
- FFmpeg est obligatoire. FFprobe est optionnel. Espace temporaire : une source plus un MP4 par conversion. Le nombre simultané se règle (1 par défaut). Un verrou évite de convertir deux fois le même fichier. Un verrou abandonné est repris après 3 heures.

Les essais automatiques fabriquent des fichiers HEVC, WebM, portrait, paysage, HDR et rotation avec ffmpeg. Ce ne sont pas des captures iPhone ou Android.

## Photos

- JPEG, PNG, WebP, HEIC, AVIF, TIFF, BMP et GIF. SVG et PDF sont refusés.
- 50 Mo par défaut, plus grand côté 2 560 px, miniature, orientation EXIF, métadonnées retirées à l'enregistrement JPEG ou WebP.
- Décodage plafonné à 80 000 000 pixels, modifiable avec le réglage `photo_max_pixels`.
- Un GIF animé est refusé tant que la case de confirmation n'est pas cochée. Avec la case, il devient un WebP animé.
- Les masques (forme opaque ou flou) sont dessinés dans les pixels enregistrés, y compris la miniature. L'original non masqué n'est pas servi. Le flou ne garantit pas l'anonymat.
- Remplacer une photo efface les fichiers précédents. L'URL ajoute `?v=` avec la taille pour éviter un ancien cache.

## Stockage

- Local et privé au départ. S3 n'est pas installé et n'est pas opérationnel.
- L'administration affiche le disque, le poids des photos et des vidéos, la file et les échecs.
- Un quota cumulé à 0 ne change pas les limites déjà en place, ni les j'aime, ni les messages. Une valeur enregistrée ensuite est appliquée.

## Intégrations

- Les secrets sont chiffrés avec `ISWING_DATA_KEY` si elle existe, sinon avec `SECRET_KEY`. Un champ vide conserve l'ancien secret. Il n'est pas renvoyé au navigateur.
- Stripe peut être enregistré en test ou en production. Le test appelle le solde et ne crée pas de paiement. Sans clés, aucun paiement n'est lancé. CCBill, Segpay et Epoch ne sont pas implémentés. L'admissibilité auprès du prestataire n'est pas acquise.
- SMTP transactionnel et SMTP de campagne sont séparés. Sans SMTP, les courriels partent vers la console locale. SPF, DKIM et DMARC sont expliqués, pas créés.
- Les campagnes se programment avec un fuseau, se mettent en pause et peuvent annuler le reste. « Accepté par le serveur » n'est pas une preuve de délivrance.
- Web Push : bouton explicite dans Paramètres. Pas de demande au chargement. Charge utile discrète. La déconnexion ou le changement de compte retire l'appareil de la session. iPhone exige une PWA installée ; ce n'est pas vérifié sur un téléphone ici.
- SEO, Analytics, Tag Manager et Meta Pixel sont désactivés tant qu'un administrateur ne les active pas, et seulement sur les pages publiques listées. Pas de script libre.

## Files d'attente

- Installation Windows : `Planifier.bat` lance `process_outbox` puis `process_videos` chaque minute. `Demarrer.bat` ne suffit pas pour une campagne programmée ou une vidéo encore en attente.
- Le site lance aussi un fil d'arrière-plan quand le nombre de conversions le permet.
- Docker Compose ajoute un service `worker` avec la même boucle. Celery et Redis ne sont pas installés.
- Un mot de passe oublié n'attend pas une conversion vidéo.

## Ce qui n'a pas été vérifié sur un appareil ou un compte réel

- Lecture Safari sur iPhone et Chrome sur Android.
- Réception push sur un téléphone.
- SMTP, Stripe live, Search Console, Analytics et Meta avec de vrais identifiants.
- Un fichier de 10 minutes ou de 2 Go n'a pas été converti : le refus au-delà de la limite est testé sur les métadonnées, pas sur un fichier de cette taille.
