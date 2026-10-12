from django.core.management.base import BaseCommand

from swingapp.services import convert_pending_videos


class Command(BaseCommand):
    help = "Convertit les vidéos en attente. ffmpeg et ffprobe sont requis."

    def handle(self, *args, **options):
        done = convert_pending_videos()
        self.stdout.write(f"videos {done}")
