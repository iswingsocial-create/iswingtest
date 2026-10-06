from datetime import date
from io import BytesIO

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from PIL import Image, ImageDraw

from swingapp.choices import CITIES
from swingapp.models import Match, Message, Partner, Photo, Profile, User


# 5 profils d'origine + 25 supplémentaires. Tous fictifs, marqués TEST.
ROWS = [
    ("test.lea@iswing.test", "Léa TEST", "single", "Lyon", "femme", 1994, "voyages, gastronomie", "diner, voyage", "homme, couple", ""),
    ("test.marc@iswing.test", "Marc TEST", "single", "Paris", "homme", 1988, "musique, sorties", "soiree, concert", "femme, couple", ""),
    ("test.ines@iswing.test", "Inès TEST", "single", "Bordeaux", "femme", 1996, "art, danse", "danse, weekend", "tous", ""),
    ("test.couple.nord@iswing.test", "Alex & Sam TEST", "couple", "Lille", "couple", 1990, "voyages, discussions", "diner, weekend", "femme, couple", "Sam TEST"),
    ("test.couple.sud@iswing.test", "Nina & Jo TEST", "couple", "Marseille", "couple", 1987, "nature, gastronomie", "plage, cuisine", "couple, homme", "Jo TEST"),
    ("test.camille@iswing.test", "Camille TEST", "single", "Nantes", "femme", 1993, "cinema, discussions", "diner, musee", "homme", ""),
    ("test.julien@iswing.test", "Julien TEST", "single", "Toulouse", "homme", 1985, "sport, voyages", "weekend, voyage", "femme", ""),
    ("test.sarah@iswing.test", "Sarah TEST", "single", "Nice", "femme", 1991, "bien-etre, nature", "spa, plage", "homme, couple", ""),
    ("test.mehdi@iswing.test", "Mehdi TEST", "single", "Montpellier", "homme", 1992, "musique, cuisine", "concert, cuisine", "femme", ""),
    ("test.chloe@iswing.test", "Chloé TEST", "single", "Rennes", "femme", 1998, "danse, sorties", "danse, soiree", "tous", ""),
    ("test.hugo@iswing.test", "Hugo TEST", "single", "Strasbourg", "homme", 1986, "art, gastronomie", "musee, diner", "femme, couple", ""),
    ("test.manon@iswing.test", "Manon TEST", "single", "Grenoble", "femme", 1995, "nature, sport", "weekend, voyage", "homme", ""),
    ("test.antoine@iswing.test", "Antoine TEST", "single", "Toulon", "homme", 1983, "discretion, sorties", "diner, soiree", "femme", ""),
    ("test.julie@iswing.test", "Julie TEST", "single", "Genève", "femme", 1989, "voyages, art", "voyage, musee", "homme, couple", ""),
    ("test.lucas@iswing.test", "Lucas TEST", "single", "Bruxelles", "homme", 1997, "musique, danse", "concert, danse", "femme", ""),
    ("test.emma@iswing.test", "Emma TEST", "single", "Montréal", "femme", 1990, "cinema, bien-etre", "spa, diner", "tous", ""),
    ("test.noah@iswing.test", "Noah TEST", "single", "Paris", "non-binaire", 1994, "discussions, art", "musee, soiree", "tous", ""),
    ("test.lea2@iswing.test", "Léa M. TEST", "single", "Lyon", "femme", 1984, "gastronomie, discretion", "cuisine, diner", "couple", ""),
    ("test.paul@iswing.test", "Paul TEST", "single", "Bordeaux", "homme", 1979, "voyages, nature", "voyage, plage", "femme, couple", ""),
    ("test.alice@iswing.test", "Alice TEST", "single", "Lille", "femme", 1999, "sorties, musique", "soiree, concert", "homme", ""),
    ("test.karim@iswing.test", "Karim TEST", "single", "Marseille", "homme", 1991, "sport, plage", "plage, sport", "femme", ""),
    ("test.oceane@iswing.test", "Océane TEST", "single", "Nantes", "femme", 1988, "danse, voyages", "danse, weekend", "couple, homme", ""),
    ("test.thomas@iswing.test", "Thomas TEST", "single", "Toulouse", "homme", 1982, "cinema, discussions", "diner, musee", "femme", ""),
    ("test.couple.est@iswing.test", "Eva & Léo TEST", "couple", "Strasbourg", "couple", 1986, "gastronomie, voyages", "diner, voyage", "femme, couple", "Léo TEST"),
    ("test.couple.ouest@iswing.test", "Maëlle & Robin TEST", "couple", "Rennes", "couple", 1992, "nature, musique", "weekend, concert", "couple, homme", "Robin TEST"),
    ("test.couple.alpes@iswing.test", "Inès & Marc TEST", "couple", "Grenoble", "couple", 1989, "sport, bien-etre", "spa, weekend", "femme, couple", "Marc TEST"),
    ("test.couple.sudest@iswing.test", "Lina & Sami TEST", "couple", "Nice", "couple", 1993, "plage, sorties", "plage, soiree", "tous", "Sami TEST"),
    ("test.couple.centre@iswing.test", "Nora & Eli TEST", "couple", "Lyon", "couple", 1985, "art, cuisine", "musee, cuisine", "couple", "Eli TEST"),
    ("test.couple.nord2@iswing.test", "Claire & Jude TEST", "couple", "Lille", "couple", 1996, "danse, discussions", "danse, diner", "femme, homme", "Jude TEST"),
    ("test.couple.paris@iswing.test", "Yaël & Noé TEST", "couple", "Paris", "couple", 1991, "discretion, sorties", "soiree, diner", "couple, femme", "Noé TEST"),
]


def _image(label, city, color):
    img = Image.new("RGB", (800, 1000), (8, 6, 16))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, 800, 280), fill=color)
    draw.ellipse((250, 120, 550, 420), outline=(220, 200, 255), width=10)
    draw.ellipse((300, 70, 500, 270), fill=color)
    safe = label.encode("ascii", "ignore").decode() or "TEST"
    city_safe = city.encode("ascii", "ignore").decode() or "Ville"
    initial = "".join(part[0] for part in safe.replace("TEST", "").split() if part)[:2] or "IS"
    draw.text((360, 150), initial, fill=(255, 255, 255))
    draw.text((70, 520), safe[:28], fill=(244, 241, 255))
    draw.text((70, 580), city_safe, fill=(183, 166, 232))
    draw.rounded_rectangle((70, 680, 280, 750), radius=20, fill=(80, 48, 224))
    draw.text((110, 700), "TEST", fill=(255, 255, 255))
    draw.text((70, 820), "Illustration fictive", fill=(160, 150, 190))
    out = BytesIO()
    img.save(out, format="JPEG", quality=85)
    return out.getvalue()


class Command(BaseCommand):
    help = "Importe 30 profils fictifs TEST (5 d'origine + 25). Refusé en production."

    def handle(self, *args, **options):
        if settings.ISWING_ENV == "production":
            raise CommandError("Import démo interdit en production.")
        palette = [(80, 48, 224), (144, 96, 240), (64, 48, 208), (112, 80, 240), (90, 40, 160), (40, 70, 160)]
        created = []
        profiles = []
        for index, row in enumerate(ROWS):
            email, name, kind, city, gender, year, tastes, activities, seeking, partner_name = row
            lat, lng = CITIES[city]
            user = User.objects.filter(email=email).first()
            if not user:
                user = User.objects.create_user(
                    email=email,
                    password="Test-iSwing-1!",
                    birth_date=date(year, (index % 12) + 1, min(28, (index % 27) + 1)),
                    terms_accepted_at=timezone.now(),
                    adult_declared=True,
                    email_verified_at=timezone.now(),
                    is_demo=True,
                )
                created.append(email)
            else:
                user.is_demo = True
                user.birth_date = date(year, (index % 12) + 1, min(28, (index % 27) + 1))
                user.save(update_fields=["is_demo", "birth_date"])
            profile, _ = Profile.objects.get_or_create(user=user, defaults={"display_name": name, "kind": kind})
            profile.display_name = name
            profile.kind = kind
            profile.city = city
            profile.lat = lat
            profile.lng = lng
            profile.gender = gender
            profile.orientation = "bi" if kind == "couple" else "hetero"
            profile.activities = activities
            profile.tastes = tastes
            profile.seeking = seeking
            profile.languages = "fr, en" if index % 2 == 0 else "fr, es"
            codes = ["trio_mfm", "trio_fmf", "echangisme", "melangisme", "groupe", "gangbang", "bdsm", "fetichismes", "voyeurisme", "jeux_role"]
            profile.desires = codes[index % len(codes)] + ", " + codes[(index * 3) % len(codes)]
            profile.user.prefs_consent = True
            profile.user.save(update_fields=["prefs_consent"])
            profile.availability = "weekend, flexible" if index % 2 == 0 else "semaine"
            profile.limits = "pression, stop, public"
            profile.bio = f"Profil fictif TEST à {city}. Rencontres entre adultes, discrétion et respect des limites."
            profile.is_demo = True
            profile.validated_at = profile.validated_at or timezone.now()
            profile.show_online = True
            profile.last_active = timezone.now()
            profile.save()
            if kind == "couple" and partner_name:
                Partner.objects.update_or_create(
                    profile=profile,
                    defaults={
                        "display_name": partner_name,
                        "birth_date": date(year - 1, 4, 12),
                        "consent_at": timezone.now(),
                        "gender": "femme" if index % 2 == 0 else "homme",
                    },
                )
            if not profile.photos.exists():
                photo = Photo(profile=profile, is_primary=True, moderation_status="approved", position=0)
                photo.image.save(f"{profile.id}.jpg", ContentFile(_image(name, city, palette[index % len(palette)])), save=True)
            profiles.append(profile)
        self._match(profiles[0], profiles[1], "Bonjour, profil TEST.", "Bonjour, ravi de discuter.")
        self._match(profiles[3], profiles[4], "Message fictif TEST entre couples.", "")
        self.stdout.write(self.style.SUCCESS(
            f"Démo prête : {len(profiles)} profils, {len(created)} nouveaux. Mot de passe : Test-iSwing-1!"
        ))

    def _match(self, a, b, first, second):
        ids = sorted([a.id, b.id])
        match, _ = Match.objects.get_or_create(profile_a_id=ids[0], profile_b_id=ids[1], defaults={"is_demo": True})
        match.is_demo = True
        match.closed_at = None
        match.save(update_fields=["is_demo", "closed_at"])
        if first and match.messages.count() < 1:
            Message.objects.create(match=match, sender=a if a.id == ids[0] else b, body=first, is_demo=True)
        if second and match.messages.count() < 2:
            Message.objects.create(match=match, sender=b if a.id == ids[0] else a, body=second, is_demo=True)
