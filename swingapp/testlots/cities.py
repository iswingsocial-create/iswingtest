"""Résolution des villes dans cities.sqlite. Refuse les homonymes."""

import sqlite3
from pathlib import Path

from django.conf import settings


class CityError(ValueError):
    pass


def db_path():
    return Path(settings.BASE_DIR) / "swingapp" / "cities.sqlite"


def city_ref(name, country, lat, lng):
    return f"{name}|{country}|{float(lat):.5f}|{float(lng):.5f}"


def parse_ref(raw):
    parts = (raw or "").split("|")
    if len(parts) != 4:
        raise CityError("référence de ville invalide")
    name, country, lat, lng = parts
    country = country.strip().upper()
    if not name.strip() or len(country) != 2:
        raise CityError("référence de ville invalide")
    try:
        return name.strip(), country, float(lat), float(lng)
    except ValueError as exc:
        raise CityError("coordonnées illisibles") from exc


def resolve_city(raw):
    """Retourne name, country, lat, lng. Refuse une ville absente ou ambiguë."""
    name, country, lat, lng = parse_ref(raw)
    path = db_path()
    if not path.is_file():
        raise CityError("référentiel des villes introuvable")
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT name, country, lat, lng FROM cities WHERE name = ? AND country = ?",
            (name, country),
        ).fetchall()
    finally:
        con.close()
    if not rows:
        raise CityError(f"ville introuvable : {name}, {country}")
    close = [row for row in rows if abs(row[2] - lat) < 0.02 and abs(row[3] - lng) < 0.02]
    if len(close) != 1:
        raise CityError(f"ville ambiguë : {name}, {country}")
    found = close[0]
    return {"name": found[0], "country": found[1], "lat": found[2], "lng": found[3], "ref": city_ref(*found)}


def search_cities(query, limit=12):
    q = (query or "").strip()
    if len(q) < 2:
        return []
    path = db_path()
    if not path.is_file():
        return []
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = con.execute(
            """SELECT name, country, lat, lng, pop FROM cities
               WHERE name LIKE ? OR ascii LIKE ?
               ORDER BY pop DESC LIMIT ?""",
            (q + "%", q + "%", limit),
        ).fetchall()
    finally:
        con.close()
    return [
        {"name": name, "country": country, "lat": lat, "lng": lng, "ref": city_ref(name, country, lat, lng)}
        for name, country, lat, lng, _pop in rows
    ]
