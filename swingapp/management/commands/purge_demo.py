from django.core.management.base import BaseCommand
from django.conf import settings
from swingapp.models import User


class Command(BaseCommand):
    help = "Supprime uniquement les comptes marqués démo."

    def handle(self, *args, **options):
        if settings.ISWING_ENV == "production":
            self.stderr.write("Refusé en production.")
            return
        qs = User.objects.filter(is_demo=True)
        n = qs.count()
        qs.delete()
        self.stdout.write(f"Comptes démo supprimés: {n}")
