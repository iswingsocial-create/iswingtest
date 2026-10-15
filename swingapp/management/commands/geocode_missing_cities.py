from django.core.management.base import BaseCommand

from swingapp.geo import geocode_missing_profiles


class Command(BaseCommand):
    help = "Géocode les profils qui ont une ville mais pas de coordonnées. N'écrase rien."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Liste les mises à jour sans les enregistrer.")

    def handle(self, *args, **options):
        dry = bool(options["dry_run"])
        updated, missed = geocode_missing_profiles(dry_run=dry)
        mode = "dry-run" if dry else "applied"
        self.stdout.write(f"{mode} {len(updated)} missed {len(missed)}")
        for profile in updated:
            self.stdout.write(f"#{profile.id} {profile.city}")
