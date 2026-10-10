from django.core.management.base import BaseCommand, CommandError

from swingapp.models import TestBatch
from swingapp.testlots.runner import run_batch


class Command(BaseCommand):
    help = "Génère un lot fictif déjà créé, ou crée puis génère un lot."

    def add_arguments(self, parser):
        parser.add_argument("--batch-id", required=True)
        parser.add_argument("--image-dir", default="")
        parser.add_argument("--name", default="")
        parser.add_argument("--seed", default="iswing-test")
        parser.add_argument("--cities", default="")
        parser.add_argument("--per-city", type=int, default=100)

    def handle(self, *args, **options):
        batch_id = options["batch_id"]
        batch = TestBatch.objects.filter(batch_id=batch_id).first()
        if not batch:
            cities = [item.strip() for item in options["cities"].split(";") if item.strip()]
            if not cities:
                raise CommandError("Lot inconnu : passez --cities pour le créer.")
            from datetime import date
            batch = TestBatch.objects.create(
                batch_id=batch_id,
                name=options["name"] or batch_id,
                seed=options["seed"],
                reference_date=date.today(),
                params={"cities": cities, "per_city": options["per_city"]},
            )
        report = run_batch(batch_id, options["image_dir"])
        self.stdout.write(f"{batch_id}: {report.get('status')} {report.get('reason', '')}")
        if report.get("status") != "packaged":
            raise CommandError("Lot non terminé : images indisponibles ou incomplètes.")
