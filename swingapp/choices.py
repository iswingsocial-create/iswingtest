"""Listes de l'interface. Les libellés affichés passent par i18n."""

GENDERS = [
    ("femme", "femme"),
    ("homme", "homme"),
    ("non-binaire", "non-binaire"),
    ("couple", "couple"),
]

ORIENTATIONS = [
    ("", "orientation_skip"),
    ("hetero", "hetero"),
    ("homo", "homo"),
    ("bi", "bi"),
    ("pan", "pan"),
    ("queer", "queer"),
]

SEEKING = [
    ("femme", "seek_femme"),
    ("homme", "seek_homme"),
    ("non-binaire", "seek_nb"),
    ("couple", "seek_couple"),
    ("tous", "seek_tous"),
]

LANGUAGES = [
    ("en", "lang_en"),
    ("zh", "lang_zh"),
    ("hi", "lang_hi"),
    ("es", "lang_es"),
    ("fr", "lang_fr"),
    ("ar", "lang_ar"),
    ("bn", "lang_bn"),
    ("pt", "lang_pt"),
    ("ru", "lang_ru"),
    ("ur", "lang_ur"),
    ("id", "lang_id"),
    ("de", "lang_de"),
    ("ja", "lang_ja"),
    ("sw", "lang_sw"),
    ("mr", "lang_mr"),
    ("te", "lang_te"),
    ("tr", "lang_tr"),
    ("ko", "lang_ko"),
    ("vi", "lang_vi"),
    ("it", "lang_it"),
    ("autre", "lang_other"),
]

TASTES = [
    ("gastronomie", "taste_gastronomie"),
    ("voyages", "taste_voyages"),
    ("musique", "taste_musique"),
    ("danse", "taste_danse"),
    ("art", "taste_art"),
    ("cinema", "taste_cinema"),
    ("nature", "taste_nature"),
    ("sport", "taste_sport"),
    ("bien-etre", "taste_bien"),
    ("discussions", "taste_discussions"),
    ("discretion", "taste_discretion"),
    ("sorties", "taste_sorties"),
]

ACTIVITIES = [
    ("diner", "act_diner"),
    ("soiree", "act_soiree"),
    ("weekend", "act_weekend"),
    ("voyage", "act_voyage"),
    ("plage", "act_plage"),
    ("concert", "act_concert"),
    ("musee", "act_musee"),
    ("cuisine", "act_cuisine"),
    ("danse", "act_danse"),
    ("spa", "act_spa"),
]

CATEGORY_CODES = [
    "trio_mfm",
    "trio_fmf",
    "echangisme",
    "melangisme",
    "groupe",
    "gangbang",
    "bdsm",
    "fetichismes",
    "voyeurisme",
    "jeux_role",
]

LIMIT_CODES = [
    "chambres",
    "solo",
    "anale",
    "vaginale",
    "sans_preservatif",
    "oral_sans",
    "oral",
    "baisers",
    "ejac_bouche",
    "ejac_corps",
    "douleur",
    "marques",
    "attaches",
    "domination",
    "humiliation",
    "cou",
    "jouets",
    "photos",
    "echanges",
    "nuit",
]

AVAILABILITY = [
    ("semaine", "avail_semaine"),
    ("weekend", "avail_weekend"),
    ("jour", "avail_jour"),
    ("flexible", "avail_flexible"),
]

REPORT_REASONS = [
    ("fake", "report_fake"),
    ("fraud", "report_fraud"),
    ("stolen", "report_stolen"),
    ("ai", "report_ai"),
    ("minor", "report_minor"),
    ("illegal", "report_illegal"),
    ("noconsent", "report_noconsent"),
    ("harassment", "report_harassment"),
    ("spam", "report_spam"),
    ("other", "report_other"),
]

DESIRES = [(code, code) for code in CATEGORY_CODES]
LIMITS = [(code, code) for code in LIMIT_CODES]

# Villes de démonstration seulement. La recherche mondiale passe par cities.sqlite.
CITIES = {
    "Paris": (48.86, 2.35),
    "Lyon": (45.75, 4.85),
    "Marseille": (43.30, 5.37),
    "Toulouse": (43.60, 1.44),
    "Bordeaux": (44.84, -0.58),
    "Lille": (50.63, 3.06),
    "Nice": (43.70, 7.26),
    "Nantes": (47.22, -1.55),
    "Strasbourg": (48.57, 7.75),
    "Montpellier": (43.61, 3.88),
    "Rennes": (48.11, -1.68),
    "Grenoble": (45.19, 5.72),
    "Toulon": (43.12, 5.93),
    "Genève": (46.20, 6.14),
    "Bruxelles": (50.85, 4.35),
    "Montréal": (45.50, -73.57),
}


def city_choices():
    return [(name, name) for name in CITIES]
