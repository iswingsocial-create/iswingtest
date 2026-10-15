from django.core.management.base import BaseCommand, CommandError

from swingapp.testlots.package import LotError, delete_lot


class Command(BaseCommand):
    help = "Supprime uniquement les profils et médias d'un lot fictif."

    def add_arguments(self, parser):
        parser.add_argument("batch_id")

    def handle(self, *args, **options):
        try:
            count = delete_lot(options["batch_id"])
        except LotError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"profils de test supprimés: {count}")
