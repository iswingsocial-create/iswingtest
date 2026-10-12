# Corrections iSwing

## Accès
- Une règle serveur (`can_view_profile`, `can_interact_with`, `can_view_media`) couvre la découverte, les fiches, les médias et les messages.
- Pause, suspension, profil incomplet, mode discret sans match et blocage réciproque refusent l'URL directe.
- Le propriétaire voit ses médias privés déverrouillés. Un j'aime n'ouvre pas l'accès privé.
- Un blocage révoque `PrivateAccess` et les anciens `PhotoGrant`.
- L'aperçu administratif est `/gestion/membres/<id>/apercu/`. Il ne publie pas la fiche.

## Administration
- `/gestion/` et `/admin/` exigent une session de double authentification (`/gestion/2fa/`).
- Droits distincts : consultation staff, `can_manage_members`, `can_moderate`, `can_manage_billing`, `can_manage_comms`, `can_configure`. Le superutilisateur les a tous.
- Le dernier superadministrateur ne peut pas être supprimé.
- Le journal (`/gestion/journal/`) note l'auteur, la cible, la date et le motif.
- Un média privé n'est ouvert par un administrateur que s'il a la permission de modération et une session 2FA. Chaque ouverture est journalisée.

## Abonnements
- Une annulation Stripe est envoyée au prestataire. Si la clé manque ou si le prestataire refuse, la base locale ne change pas.
- Un avantage saisi dans Gestion est `source=manual`. Il ne modifie pas un abonnement `source=provider`.
- Les webhooks restent en `received` ou `failed` tant que le traitement n'a pas réussi, pour permettre une nouvelle tentative.
- Les états visibles : actif, annulation programmée, expiré, paiement en échec, essai.

## Communications
- Ouvrir une page de gestion n'envoie plus les campagnes ni les reprises.
- Commande : `python manage.py process_outbox` (voir `Planifier.bat`, toutes les 60 secondes).
- États : pending, scheduled, sending, sent, partial, failed, canceled.
- `accepted_by_mailer` = accepté par le système d'envoi, pas une preuve de lecture.
- Date invalide refusée. Fuseau UTC. Annulation possible tant que le statut est `scheduled`.
- Les profils TEST sont exclus sauf case « Inclure les profils TEST » ou cible « Profils TEST seulement ».
- La confirmation reprend les identifiants prévisualisés. Au-delà de 5000 destinataires, rien n'est envoyé.

## Vidéos
- Une conversion ratée ne conserve pas l'original comme vidéo lisible.
- Les fichiers de plus de 8 Mo passent en `processing_status=pending`.
- Commande : `python manage.py process_videos`. Il faut `ffmpeg` et `ffprobe` dans le PATH.

## Inactivité
- `python manage.py purge_inactive` prévisualise.
- `python manage.py purge_inactive --apply` supprime les comptes sans connexion ni activité significative depuis 12 mois (hors staff, superutilisateur et TEST).
- Les médias partent avec le compte. La page `/gestion/inactivite/` fait la même chose après confirmation.
- `last_active` n'est plus mis à jour à chaque page : seulement connexion, j'aime, message, profil et envoi de média.

## Limites
- Stripe n'est pas connecté tant que les clés ne sont pas dans `.env`. Aucun numéro de carte n'est stocké.
- L'adresse postale et la liste des prestataires restent à compléter.
- L'acceptation par le serveur de courriel n'est pas une preuve de délivrance.
- Sans ffmpeg, les vidéos échouent ou restent en attente.
- La suppression pour inactivité retire aussi les signalements liés à la fiche.

## Tests
59 tests OK (`python manage.py test swingapp.tests swingapp.test_testlots`), dont les accès, la double authentification, l'annulation sans prestataire, le webhook repris, les notifications, les quotas, les campagnes, l'aperçu et les favoris.
Aucun navigateur n'était disponible pour produire des captures.

