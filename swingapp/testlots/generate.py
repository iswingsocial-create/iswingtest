"""Génération reproductible des fiches. Les images sont une étape séparée."""

import hashlib
import random
import re
import unicodedata
from datetime import date, timedelta

from swingapp.choices import (
    ACTIVITIES,
    AVAILABILITY,
    CATEGORY_CODES,
    GENDERS,
    LANGUAGES,
    LIMIT_CODES,
    ORIENTATIONS,
    SEEKING,
    TASTES,
)
from swingapp.testlots.cities import resolve_city

FORMAT_VERSION = 1
LANG_CODES = [code for code, _label in LANGUAGES if code != "autre"]
GENDER_CODES = [code for code, _label in GENDERS if code != "couple"]
ORIENTATION_CODES = [code for code, _label in ORIENTATIONS if code]
SEEKING_CODES = [code for code, _label in SEEKING]
TASTE_CODES = [code for code, _label in TASTES]
ACTIVITY_CODES = [code for code, _label in ACTIVITIES]
AVAIL_CODES = [code for code, _label in AVAILABILITY]
COMPOSITIONS = ("HH", "HF", "FF", "NBH", "NBF")
ORIGINS = (
    "europe de l'ouest",
    "europe du nord",
    "europe de l'est",
    "maghreb",
    "afrique de l'ouest",
    "afrique de l'est",
    "moyen-orient",
    "asie du sud",
    "asie de l'est",
    "asie du sud-est",
    "amerique latine",
    "caraibes",
    "amerique du nord",
    "oceanie",
    "mixte",
)
SKIN = ("clair", "clair doré", "olive", "mat", "brun", "foncé")
HAIR = ("noirs courts", "noirs longs", "bruns", "châtains", "blonds", "roux", "poivre et sel", "rasés")
EYES = ("marron", "noisette", "verts", "bleus", "gris")
BUILD = ("mince", "athlétique", "moyenne", "solide")
HAIRNESS = ("absente", "légère", "marquée")
MARKS = ("aucune", "tache de naissance discrète", "lunettes", "fossettes", "barbe courte", "cheveux bouclés")
FIRST = {
    "femme": ["Léa", "Inès", "Nora", "Camille", "Aya", "Lina", "Maya", "Elena", "Sofia", "Chloé", "Amina", "Hana", "Lucia", "Mei", "Nina"],
    "homme": ["Marc", "Sami", "Hugo", "Noah", "Eli", "Karim", "Lucas", "Andre", "Yan", "Omar", "Leo", "Mateo", "Kenji", "Paul", "Adam"],
    "non-binaire": ["Alix", "Sasha", "Noa", "Lou", "Eden", "Charlie", "Yaël", "Robin", "Angel", "Camille"],
}
BIO = {
    "fr": (
        "{names} {verb} à {city}. {ages}. Nous aimons {tastes} et les sorties du type {activities}. "
        "Nous cherchons {seeking}, surtout {avail}. Les catégories indiquées sont {desires}. "
        "Les limites notées sur le profil restent valables, rien d'autre n'est sous-entendu. "
        "Profil fictif de démonstration, personne réelle non représentée."
    ),
    "en": (
        "{names} {verb} in {city}. {ages}. We enjoy {tastes} and plans such as {activities}. "
        "We are looking for {seeking}, mainly {avail}. Listed categories are {desires}. "
        "The limits on the profile still apply, and nothing else is implied. "
        "Fictional demonstration profile, no real person is depicted."
    ),
    "es": (
        "{names} {verb} en {city}. {ages}. Nos gustan {tastes} y planes como {activities}. "
        "Buscamos {seeking}, sobre todo {avail}. Las categorías indicadas son {desires}. "
        "Los límites del perfil siguen vigentes y no implican otras prácticas. "
        "Perfil ficticio de demostración, no representa a una persona real."
    ),
}


def allocate(total, weights):
    total = int(total)
    keys = list(weights)
    if total < 0 or not keys:
        raise ValueError("répartition")
    raw = {key: total * float(weights[key]) for key in keys}
    floors = {key: int(raw[key]) for key in keys}
    left = total - sum(floors.values())
    order = sorted(keys, key=lambda key: (raw[key] - floors[key], key), reverse=True)
    for index in range(left):
        floors[order[index % len(order)]] += 1
    return floors


def defaults():
    return {
        "per_city": 100,
        "couple_ratio": 0.4,
        "compositions": {"HH": 0.15, "HF": 0.45, "FF": 0.25, "NBH": 0.08, "NBF": 0.07},
        "age_min": 25,
        "age_max": 65,
        "photos": 3,
        "private_photos": 1,
        "face_mix": {"visible": 0.60, "blurred": 0.25, "emoji": 0.15},
        "languages": ["fr", "en", "es"],
        "origin_diversity": True,
    }


def _slug(value):
    folded = "".join(ch for ch in unicodedata.normalize("NFKD", value) if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "", folded.lower())[:12] or "ville"


def _birth(rng, ref, age):
    start = date(ref.year - age - 1, ref.month, ref.day) + timedelta(days=1)
    end = date(ref.year - age, ref.month, ref.day)
    if end < start:
        end = start
    return start + timedelta(days=rng.randrange((end - start).days + 1))


def _person(rng, gender, ref, age_min, age_max, languages, diversity):
    age = rng.randint(age_min, age_max)
    primary = rng.choice(languages)
    secondary = [code for code in rng.sample(LANG_CODES, k=rng.randint(0, 2)) if code != primary]
    origins = [rng.choice(ORIGINS)]
    if diversity and rng.random() < 0.25:
        extra = rng.choice([item for item in ORIGINS if item not in origins])
        origins.append(extra)
    return {
        "gender": gender,
        "age": age,
        "birth_date": _birth(rng, ref, age).isoformat(),
        "display_name": rng.choice(FIRST[gender]),
        "origins": origins,
        "primary_language": primary,
        "secondary_languages": secondary,
        "visual": {
            "skin": rng.choice(SKIN),
            "hair": rng.choice(HAIR),
            "eyes": rng.choice(EYES),
            "build": rng.choice(BUILD),
            "hairness": rng.choice(HAIRNESS),
            "marks": rng.choice(MARKS),
            "apparent_age": age,
        },
    }


def _composition_genders(code):
    return {
        "HH": ("homme", "homme"),
        "HF": ("homme", "femme"),
        "FF": ("femme", "femme"),
        "NBH": ("non-binaire", "homme"),
        "NBF": ("non-binaire", "femme"),
    }[code]


def _bio(kind, people, city, tastes, activities, seeking, desires, availability, primary):
    lang = primary if primary in BIO else "fr"
    names = people[0]["display_name"] if kind == "single" else f"{people[0]['display_name']} et {people[1]['display_name']}"
    ages = f"{people[0]['age']} ans" if kind == "single" else f"{people[0]['age']} et {people[1]['age']} ans"
    if lang == "en":
        names = people[0]["display_name"] if kind == "single" else f"{people[0]['display_name']} and {people[1]['display_name']}"
        ages = f"{people[0]['age']} years old" if kind == "single" else f"{people[0]['age']} and {people[1]['age']} years old"
        verb = "lives" if kind == "single" else "live"
    elif lang == "es":
        names = people[0]["display_name"] if kind == "single" else f"{people[0]['display_name']} y {people[1]['display_name']}"
        ages = f"{people[0]['age']} años" if kind == "single" else f"{people[0]['age']} y {people[1]['age']} años"
        verb = "vive" if kind == "single" else "viven"
    else:
        verb = "vit" if kind == "single" else "vivent"
    text = BIO[lang].format(
        names=names,
        verb=verb,
        city=city,
        ages=ages,
        tastes=", ".join(tastes),
        activities=", ".join(activities),
        seeking=", ".join(seeking),
        desires=", ".join(desires),
        avail=", ".join(availability),
    )
    if people[0]["primary_language"] not in ("fr", "en", "es") and lang == "fr":
        text += f" Langue principale indiquée : {people[0]['primary_language']}."
    words = text.split()
    if len(words) < 50:
        text += " Discrétion demandée, rencontres entre adultes seulement, aucun paiement ni identité réelle."
    return " ".join(text.split()[:100])


def build_profiles(batch_id, seed, reference, cities, options):
    opts = defaults()
    opts.update(options or {})
    rng = random.Random(str(seed))
    per_city = int(opts["per_city"])
    if per_city < 1 or per_city > 500:
        raise ValueError("nombre de profils par ville hors limites")
    age_min, age_max = int(opts["age_min"]), int(opts["age_max"])
    if age_min < 25 or age_max > 65 or age_min > age_max:
        raise ValueError("tranche d'âge")
    photos = int(opts["photos"])
    private_photos = int(opts["private_photos"])
    if photos < 1 or photos > 10 or private_photos < 0 or private_photos >= photos:
        raise ValueError("photos")
    languages = [code for code in opts["languages"] if code in LANG_CODES] or ["fr", "en", "es"]
    profiles = []
    used_names = set()
    for city_raw in cities:
        city = resolve_city(city_raw)
        couples = allocate(per_city, {"couple": float(opts["couple_ratio"]), "single": 1 - float(opts["couple_ratio"])})
        compositions = allocate(couples["couple"], opts["compositions"])
        singles = allocate(couples["single"], {"femme": 0.45, "homme": 0.4, "non-binaire": 0.15})
        faces = allocate(per_city, opts["face_mix"])
        slots = (
            [("couple", code) for code, count in compositions.items() for _ in range(count)]
            + [("single", code) for code, count in singles.items() for _ in range(count)]
        )
        face_slots = [mode for mode, count in faces.items() for _ in range(count)]
        rng.shuffle(slots)
        rng.shuffle(face_slots)
        for index, ((kind, code), face) in enumerate(zip(slots, face_slots), start=1):
            genders = _composition_genders(code) if kind == "couple" else (code,)
            people = [_person(rng, gender, reference, age_min, age_max, languages, opts["origin_diversity"]) for gender in genders]
            tastes = rng.sample(TASTE_CODES, k=rng.randint(2, 3))
            activities = rng.sample(ACTIVITY_CODES, k=rng.randint(2, 3))
            seeking = rng.sample(SEEKING_CODES, k=rng.randint(1, 2))
            desires = rng.sample(CATEGORY_CODES, k=rng.randint(1, 2))
            availability = rng.sample(AVAIL_CODES, k=rng.randint(1, 2))
            limits = rng.sample(LIMIT_CODES, k=rng.randint(2, 4))
            primary = people[0]["primary_language"]
            if kind == "couple":
                label = f"{people[0]['display_name']} & {people[1]['display_name']}"
            else:
                label = people[0]["display_name"]
            base = label
            suffix = 2
            while label.lower() in used_names or len(label) > 40:
                label = f"{base} {suffix}"[:40]
                suffix += 1
            used_names.add(label.lower())
            external = f"{batch_id}-{_slug(city['name'])}{city['country'].lower()}-{index:04d}"
            photo_rows = []
            for slot in range(photos):
                private = slot >= photos - private_photos
                photo_rows.append({
                    "slot": slot,
                    "file": f"media/{external}/{slot}.jpg",
                    "is_primary": slot == 0,
                    "is_private": private,
                    "face": face,
                    "sha256": "",
                })
            profiles.append({
                "external_key": external,
                "email": f"{external}@members.inv",
                "kind": kind,
                "composition": code if kind == "couple" else code,
                "display_name": label,
                "gender": people[0]["gender"],
                "orientation": rng.choice(ORIENTATION_CODES),
                "city": city["name"],
                "country": city["country"],
                "city_ref": city["ref"],
                "lat": city["lat"],
                "lng": city["lng"],
                "languages": [primary] + people[0]["secondary_languages"],
                "origins": people[0]["origins"] if kind == "single" else people[0]["origins"] + people[1]["origins"],
                "seeking": seeking,
                "tastes": tastes,
                "activities": activities,
                "desires": desires,
                "availability": availability,
                "limits": limits,
                "bio": _bio(kind, people, city["name"], tastes, activities, seeking, desires, availability, primary),
                "visibility": "public",
                "show_distance": rng.random() > 0.2,
                "people": people,
                "photos": photo_rows,
                "face": face,
                "simulated": {
                    "consent": "donnée de test, pas une preuve",
                    "age_proof": "declared",
                    "subscription": "test-simulated",
                    "email_domain": "members.inv",
                },
            })
    return profiles


def prompt_for(profile, slot):
    people = profile["people"]
    face = profile["face"]
    bits = []
    for person in people:
        visual = person["visual"]
        bits.append(
            f"{person['gender']} adult around {person['age']}, {visual['skin']} skin, {visual['hair']} hair, "
            f"{visual['eyes']} eyes, {visual['build']} build, {visual['marks']}"
        )
    who = " and ".join(bits)
    scene = ["city cafe portrait", "park walk portrait", "evening restaurant portrait"][slot % 3]
    cover = ""
    if face == "blurred":
        cover = " Faces intentionally soft and unreadable."
    elif face == "emoji":
        cover = " Faces fully covered by a large simple smiley sticker."
    count = "exactly two adults, no extra person" if profile["kind"] == "couple" else "exactly one adult, no extra person"
    return (
        f"Original fictional photograph, non-explicit, fully clothed adults, no nudity, no sexual act, no logo, no text. "
        f"{count}. {who}. Scene: {scene}, {profile['city']}. Natural light, realistic.{cover}"
    )


def fingerprint(payload):
    return hashlib.sha256(repr(payload).encode()).hexdigest()
