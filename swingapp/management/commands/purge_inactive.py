from django.core.management.base import BaseCommand

from swingapp.models import InactivityRun
from swingapp.services import inactive_members


class Command(BaseCommand):
    help = "Prévisualise ou supprime les comptes sans connexion ni activité depuis 12 mois."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Supprime réellement. Sans ce drapeau, prévisualise seulement.")

    def handle(self, *args, **options):
        qs = inactive_members()
        matched = qs.count()
        if not options["apply"]:
            InactivityRun.objects.create(mode="preview", matched=matched, deleted=0, detail="prévisualisation")
            self.stdout.write(f"preview {matched}")
            return
        deleted = 0
        photos = 0
        for user in list(qs.select_related("profile")):
            profile = getattr(user, "profile", None)
            if profile is not None:
                photos += profile.photos.count()
            user.delete()
            deleted += 1
        InactivityRun.objects.create(
            mode="apply",
            matched=matched,
            deleted=deleted,
            detail=f"médias supprimés avec les comptes : {photos}",
        )
        self.stdout.write(f"deleted {deleted}")
