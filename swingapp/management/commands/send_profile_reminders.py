from django.core.management.base import BaseCommand

from swingapp.services import send_profile_reminders


class Command(BaseCommand):
    help = "Envoie les rappels de profil incomplet (J+1, J+3, J+7)."

    def handle(self, *args, **options):
        sent = send_profile_reminders()
        self.stdout.write(f"rappels {sent}")
