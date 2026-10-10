# iSwing — guide d'exploitation

Plateforme de rencontres adultes (célibataires et couples). Le code de ce dépôt a été créé parce qu'aucun code existant n'était présent dans l'espace de travail.

## Démarrage local

Windows : `Installer.bat`, `Creer-Admin.bat`, `Demarrer.bat`.

Linux :

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py runserver 127.0.0.1:8000
```

Site : http://localhost:8000 — administration Django : http://localhost:8000/admin/ — gestion métier : http://localhost:8000/gestion/

## Gestion

Le menu couvre le tableau de bord, les membres, la médiathèque, les signalements, les abonnements, les messages de l'équipe et les paramètres.

- Bloquer un membre est immédiat et réciproque. Le signalement vient après, s'il est choisi. Le membre signalé ne voit pas qui a écrit.
- Chaque signalement est dans Gestion et un courriel part vers Info@iswing.live, sans média joint. Un échec d'envoi se réessaie depuis Paramètres.
- Les médias privés ne s'ouvrent qu'avec la permission de modération (le superutilisateur l'a). Chaque consultation est journalisée.
- Ajouter un membre réel crée une invitation. La personne choisit son mot de passe et coche ses consentements. Un couple demande aussi l'accord du second partenaire.
- Les messages promotionnels ignorent les membres sans consentement. Un même envoi ne part pas deux fois au même compte. L'historique ne marque pas un courriel comme lu.

## Paiements

Non raccordés. Prestataires à faire accepter explicitement l'activité : CCBill, Segpay ou Epoch. Ne pas utiliser Stripe. Le webhook `/paiements/webhook/` refuse tant que `PAYMENT_PROVIDER` et `PAYMENT_WEBHOOK_SECRET` sont vides. Signature HMAC-SHA256 dans `X-Iswing-Signature`.

## Démo (hors production)

`python manage.py import_demo` ou `Importer-Demo.bat`.

Mot de passe commun : `Test-iSwing-1!`

- test.lea@iswing.test
- test.marc@iswing.test
- test.ines@iswing.test
- test.couple.nord@iswing.test
- test.couple.sud@iswing.test

Suppression seule des données démo : `python manage.py purge_demo`.

## Sauvegarde

Copier `data/` (SQLite, médias, clé locale). Sur VPS, `pg_dump` plus le volume médias. Chiffrer l'archive avec la clé `BACKUP_KEY` détenue par le propriétaire. Restaurer avant de relancer l'application. Les mises à jour se font par `git pull` ou remplacement du code, puis `migrate`, sans supprimer `data/`.

## Non prêt pour le public

Paiement réel, courriel SMTP, vérification de majorité par preuve, test sur téléphone physique et VPS Hostinger restent à faire par l'exploitant.
