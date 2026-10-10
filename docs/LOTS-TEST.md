# Lots de profils fictifs

Ces profils ne sont pas des membres. Ils portent `is_demo=True`, un courriel `@members.inv` et un mot de passe inutilisable. Le badge affiché est « membre a vie ». L'abonnement `test-simulated` n'est pas un paiement.

## Choisir les villes

1. Ouvrir Gestion, puis Profils de test.
2. Chercher la ville. Copier la référence `Nom|PAYS|latitude|longitude`.
3. Une ville sans cette référence, ou homonyme, est refusée.

## Générer

Indiquer le nombre par ville (100 par défaut), la graine et le nom du lot. Le volume s'affiche avant le lancement. La génération d'images ne démarre que si un dossier source (`ISWING_IMAGE_DIR` ou `--image-dir`) ou une clé fournisseur est disponible. Sinon le lot reste `images_blocked` et n'est pas présenté comme terminé.

## Déposer les images vous-même

Après la génération des fiches, ouvrez le lot. Chaque compte a un identifiant stable, par exemple `lot-lyonfr-0001`.

- Une image à la fois : choisir le compte, l'emplacement (0 principale publique, puis publiques, la dernière privée) et le JPEG.
- Ou une archive : dossiers `identifiant/0.jpg`, `identifiant/1.jpg`, `identifiant/2.jpg`.
- Quand toutes les images sont là : « Assembler le ZIP », puis importer.

Le flou ou l'emoji prévu est écrit dans le fichier seulement si la case est cochée, ou automatiquement pour une archive.

## Importer

Déposer le ZIP puis « Vérifier et importer le lot ». Un second import n'ajoute pas de doublon. `--update` ne modifie que le lot fictif.

## Supprimer

`python manage.py delete_test_batch NOM` ou le bouton du lot. Les comptes réels ne sont pas touchés.

Refusé si `ISWING_ENV=production`.

## Paquet

- `manifest.json` : format 1, lot, graine, date de référence, villes, compteurs
- `profiles.json` : listes structurées, converties à l'import
- `media/{identifiant}/{slot}.jpg` : JPEG sans métadonnées, empreinte SHA-256
- `generation-report.json`, `image-provenance.json`, `README.txt`

La graine reproduit les fiches. Elle ne garantit pas des images identiques d'un fournisseur à l'autre.
