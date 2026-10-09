from django.core.management.base import BaseCommand

from swingapp.models import TestBatch


class Command(BaseCommand):
    help = "Affiche l'état d'un lot fictif."

    def add_arguments(self, parser):
        parser.add_argument("batch_id")

    def handle(self, *args, **options):
        batch = TestBatch.objects.filter(batch_id=options["batch_id"]).first()
        if not batch:
            self.stdout.write("absent")
            return
        self.stdout.write(f"{batch.batch_id} {batch.status} {batch.error} zip={batch.zip_path}")
