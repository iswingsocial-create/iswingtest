"""Géocodage des villes via cities.sqlite. N'écrase jamais des coordonnées déjà présentes."""

import logging
import math
import sqlite3
import unicodedata
from pathlib import Path

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger("iswing.geo")


def _fold(text):
    raw = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in raw if not unicodedata.combining(ch)).casefold().strip()


def _db():
    return Path(settings.BASE_DIR) / "swingapp" / "cities.sqlite"


def parse_coords(lat_raw, lng_raw):
    try:
        lat = float(str(lat_raw).strip())
        lng = float(str(lng_raw).strip())
    except (TypeError, ValueError):
        return None, None
    if not (math.isfinite(lat) and math.isfinite(lng)):
        return None, None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None, None
    return lat, lng


def geocode_city(query):
    """Retourne name, country, lat, lng ou None. Le plus peuplé gagne en cas d'homonymes."""
    raw = (query or "").strip()
    if "," in raw:
        raw = raw.split(",", 1)[0].strip()
    folded = _fold(raw)
    if len(folded) < 2:
        return None
    path = _db()
    if not path.is_file():
        logger.warning("référentiel des villes absent")
        return None
    like = folded.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = con.execute(
            """SELECT name, ascii, country, lat, lng, pop FROM cities
               WHERE name = ? OR ascii = ? OR name LIKE ? ESCAPE '\\' OR ascii LIKE ? ESCAPE '\\'
               ORDER BY pop DESC LIMIT 40""",
            (raw, raw, like, like),
        ).fetchall()
    finally:
        con.close()
    exact = []
    prefix = []
    for name, ascii_name, country, lat, lng, pop in rows:
        item = {"name": name, "country": country, "lat": lat, "lng": lng, "pop": pop or 0}
        if _fold(name) == folded or _fold(ascii_name) == folded:
            exact.append(item)
        elif _fold(name).startswith(folded) or _fold(ascii_name).startswith(folded):
            prefix.append(item)
    if exact:
        exact.sort(key=lambda item: -item["pop"])
        return {key: exact[0][key] for key in ("name", "country", "lat", "lng")}
    if len(prefix) == 1:
        return {key: prefix[0][key] for key in ("name", "country", "lat", "lng")}
    return None


def assign_city_coords(city, lat, lng, previous_city="", previous_lat=None, previous_lng=None):
    """Coordonnées à enregistrer. Un couple lat/lng déjà fourni est prioritaire.
    Sinon géocode la ville. Ne remplace pas des coordonnées existantes si le nom n'a pas changé.
    """
    city = (city or "").strip()
    previous_city = (previous_city or "").strip()
    if lat is not None and lng is not None:
        return lat, lng
    if not city:
        return previous_lat, previous_lng
    same = _fold(city) == _fold(previous_city)
    if same and previous_lat is not None and previous_lng is not None:
        return previous_lat, previous_lng
    found = geocode_city(city)
    if found:
        logger.info("géocodage à l'enregistrement: %s -> %.5f,%.5f", city, found["lat"], found["lng"])
        return found["lat"], found["lng"]
    logger.warning("géocodage à l'enregistrement impossible: %s", city)
    if same:
        return previous_lat, previous_lng
    return None, None


def geocode_missing_profiles(dry_run=False, actor=None):
    """Remplit lat/lng vides quand la ville est connue. Ne touche pas aux coordonnées déjà là."""
    from .models import AuditLog, Profile

    updated = []
    missed = []
    qs = (
        Profile.objects.filter(lat__isnull=True, lng__isnull=True)
        .exclude(city="")
        .order_by("id")
    )
    for profile in qs.iterator():
        if profile.lat is not None and profile.lng is not None:
            continue
        found = geocode_city(profile.city)
        if not found:
            missed.append(profile.id)
            logger.warning("géocodage impossible: profil %s ville %s", profile.id, profile.city)
            continue
        logger.info(
            "géocodage profil %s « %s » -> %.5f,%.5f",
            profile.id, profile.city, found["lat"], found["lng"],
        )
        updated.append(profile)
        if dry_run:
            continue
        fields = []
        if profile.lat is None:
            profile.lat = found["lat"]
            fields.append("lat")
        if profile.lng is None:
            profile.lng = found["lng"]
            fields.append("lng")
        if not fields:
            continue
        profile.location_updated_at = timezone.now()
        fields.append("location_updated_at")
        profile.save(update_fields=fields)
        AuditLog.objects.create(
            actor=actor,
            action="geocode_city",
            target=str(profile.id),
            detail=f"{profile.city} -> {found['lat']:.5f},{found['lng']:.5f}"[:300],
        )
    return updated, missed
