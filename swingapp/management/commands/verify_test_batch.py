import json

from django.core.management.base import BaseCommand, CommandError

from swingapp.testlots.package import LotError, verify_lot


class Command(BaseCommand):
    help = "Vérifie un ZIP de lot sans l'importer."

    def add_arguments(self, parser):
        parser.add_argument("zip_path")

    def handle(self, *args, **options):
        try:
            report = verify_lot(options["zip_path"])
        except (LotError, OSError, json.JSONDecodeError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps({"ok": report["ok"], "profiles": report["profiles"], "images": report["images"], "errors": report["errors"]}, ensure_ascii=False))
        if not report["ok"]:
            raise CommandError("paquet refusé")
