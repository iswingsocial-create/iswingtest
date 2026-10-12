from django.core.management.base import BaseCommand, CommandError

from swingapp.testlots.package import LotError, import_lot


class Command(BaseCommand):
    help = "Importe un lot fictif validé. Refusé en production."

    def add_arguments(self, parser):
        parser.add_argument("zip_path")
        parser.add_argument("--update", action="store_true")

    def handle(self, *args, **options):
        try:
            result = import_lot(options["zip_path"], update=options["update"])
        except LotError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            f"créés={len(result['created'])} ignorés={len(result['skipped'])} refusés={len(result['refused'])}"
        )
