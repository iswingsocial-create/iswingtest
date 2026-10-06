from django.core.management.base import BaseCommand

from swingapp.services import process_outbox


class Command(BaseCommand):
    help = "Envoie les campagnes échues et reprend les courriels dont l'échéance est passée."

    def handle(self, *args, **options):
        process_outbox()
        self.stdout.write("outbox ok")
