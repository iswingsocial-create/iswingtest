# Landing iSwing. Un seul interrupteur : MODE. Aucune autre URL de site ou d'app dans ce fichier,
# hormis LEAVE_URL (sortie du portail 18+) et les adresses schema.org.
# TEST aujourd'hui. Le jour du lancement : MODE = "LIVE", puis relancer ce script.
import importlib.util
import json
import os
import re
import shutil
from decimal import Decimal, InvalidOperation
from html import escape

MODE = "TEST"  # "TEST" ou "LIVE"

PROFILES = {
    "TEST": {
        "SITE_URL": "https://iswingtest.onrender.com",
        "APP_URL": "https://iswingtest.onrender.com",
    },
    "LIVE": {
        "SITE_URL": "https://iswing.live",
        "APP_URL": "https://app.iswing.live",
    },
}

PRICE_AMOUNT = "29"
PRICE_CURRENCY = "USD"
LEAVE_URL = "https://www.google.com/"

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PROJECT = os.path.dirname(ROOT)


def _texts():
    path = os.path.join(HERE, "texts.py")
    spec = importlib.util.spec_from_file_location("iswing_landing_texts", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TEXTS = _texts()
HOME = TEXTS.HOME
CITIES = TEXTS.CITIES


def site_url():
    return PROFILES[MODE]["SITE_URL"].rstrip("/")


def app_url():
    return PROFILES[MODE]["APP_URL"].rstrip("/")


def price_amount():
    try:
        value = Decimal(str(PRICE_AMOUNT))
    except InvalidOperation as exc:
        raise SystemExit("PRICE_AMOUNT invalide") from exc
    return f"{value.quantize(Decimal('0.01')):.2f}"


def price_label(lang):
    value = Decimal(str(PRICE_AMOUNT))
    if value == value.to_integral():
        amount = str(int(value))
    else:
        amount = f"{value.quantize(Decimal('0.01')):.2f}"
    if lang == "fr":
        return f"{amount} $ US"
    if lang == "es":
        return f"{amount} USD"
    return f"US${amount}"


def trial_bundle(trial=None):
    if trial is None:
        return 7, 10, 2
    if isinstance(trial, dict):
        return int(trial["days"]), int(trial["likes"]), int(trial["messages"])
    days, likes, messages = trial
    return int(days), int(likes), int(messages)


def trial_tokens(lang, days, likes, messages):
    days, likes, messages = int(days), int(likes), int(messages)
    if lang == "fr":
        days_phrase = "1 jour" if days == 1 else f"{days} jours"
        days_free = "1 jour gratuit" if days == 1 else f"{days} jours gratuits"
        likes_per_day = "1 « j'aime » par jour" if likes == 1 else f"{likes} « j'aime » par jour"
        messages_per_match = "1 message par match" if messages == 1 else f"{messages} messages par match"
    elif lang == "en":
        days_phrase = "1 day" if days == 1 else f"{days} days"
        days_free = "1 free day" if days == 1 else f"{days} free days"
        likes_per_day = "1 like per day" if likes == 1 else f"{likes} likes per day"
        messages_per_match = "1 message per match" if messages == 1 else f"{messages} messages per match"
    else:
        days_phrase = "1 día" if days == 1 else f"{days} días"
        days_free = "1 día gratis" if days == 1 else f"{days} días gratis"
        likes_per_day = "1 me gusta por día" if likes == 1 else f"{likes} me gusta por día"
        messages_per_match = "1 mensaje por match" if messages == 1 else f"{messages} mensajes por match"
    return {
        "days": str(days),
        "likes": str(likes),
        "messages": str(messages),
        "days_phrase": days_phrase,
        "days_free": days_free,
        "likes_per_day": likes_per_day,
        "messages_per_match": messages_per_match,
        "price": price_label(lang),
    }


def apply_tokens(value, tokens):
    if isinstance(value, str):
        for key, repl in tokens.items():
            value = value.replace("{" + key + "}", str(repl))
        return value
    if isinstance(value, list):
        return [apply_tokens(item, tokens) for item in value]
    if isinstance(value, tuple):
        return tuple(apply_tokens(item, tokens) for item in value)
    if isinstance(value, dict):
        return {key: apply_tokens(item, tokens) for key, item in value.items()}
    return value


def word_count(text):
    return len(re.findall(r"\S+", text or ""))


ICONS = {
    "shield": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z"/><path d="M8.5 12l2.5 2.5 4.5-5"/></svg>',
    "hand": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M12 21s-7-4.4-7-10a4 4 0 017-2.6A4 4 0 0119 11c0 5.6-7 10-7 10z"/></svg>',
    "flag": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M5 21V4M5 4h11l-2 4 2 4H5"/></svg>',
    "lock": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 018 0v3"/></svg>',
    "eye": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>',
    "trash": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/></svg>',
}

CSS = r"""
:root{color-scheme:dark;--bg:#000;--bg-2:#0a0614;--card:#120c1c;--text:#f4f1ff;--muted:#b7a6e8;--line:rgba(144,96,240,.35);--violet:#9060f0;--indigo:#5030e0;--lilac:#b79af8;--glow:0 0 24px rgba(128,96,240,.45)}
*{box-sizing:border-box}html{scroll-behavior:smooth}html,body{margin:0}
body{font-family:"Segoe UI",system-ui,-apple-system,Roboto,"Helvetica Neue",Arial,sans-serif;background:radial-gradient(900px 420px at 50% -10%,rgba(80,48,224,.45),transparent 60%),linear-gradient(180deg,var(--bg-2),var(--bg) 280px);background-color:#000;color:var(--text);line-height:1.6;font-size:1rem}
a{color:#d8c8ff}img,svg{max-width:100%;height:auto}
.skip{position:absolute;left:-999px;top:0;background:var(--indigo);color:#fff;padding:.6rem 1rem;z-index:100;border-radius:0 0 12px 0}.skip:focus{left:0}
:focus-visible{outline:3px solid var(--lilac);outline-offset:3px}
.top{display:flex;justify-content:space-between;align-items:center;gap:.75rem;padding:.6rem 1rem;background:rgba(0,0,0,.72);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:5;backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px)}
.brand{display:flex;align-items:center;gap:.6rem;color:#fff;text-decoration:none;font-weight:700;letter-spacing:.04em;font-size:1.1rem}
.brand img{border-radius:50%;box-shadow:var(--glow);background:#000}
.top nav{display:flex;align-items:center;gap:.4rem}
.nav-links{display:none}
.nav-links a{color:var(--text);text-decoration:none;padding:.4rem .6rem;border-radius:10px;font-size:.92rem}.nav-links a:hover{background:rgba(144,96,240,.18)}
.langs{display:inline-flex;gap:.25rem}
.lang{display:inline-flex;align-items:center;justify-content:center;min-height:44px;min-width:44px;padding:0 .7rem;border:1px solid var(--line);border-radius:999px;text-decoration:none;font-size:.85rem;font-weight:700;color:var(--text)}
.lang[aria-current="true"]{background:rgba(144,96,240,.28)}
.btn{background:linear-gradient(90deg,var(--indigo),var(--violet));color:#fff;border:0;border-radius:999px;padding:.8rem 1.3rem;font-weight:700;min-height:44px;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;justify-content:center;font:inherit;font-weight:700;box-shadow:var(--glow);transition:transform .15s ease,filter .15s ease}
.btn:hover{filter:brightness(1.12);transform:translateY(-1px)}
.btn.ghost{background:transparent;border:1px solid var(--line);box-shadow:none}
.btn.sm{padding:.45rem .95rem;font-size:.9rem}
.btn.lg{padding:1rem 1.8rem;font-size:1.08rem}
main{max-width:1080px;margin:0 auto;padding:1rem}
section{margin:0 0 1.25rem;scroll-margin-top:5rem}
.card,.hero{background:linear-gradient(180deg,rgba(144,96,240,.12),rgba(10,6,20,.92));border:1px solid var(--line);border-radius:22px;padding:1.4rem 1.2rem;box-shadow:0 10px 40px rgba(0,0,0,.35)}
.hero{display:grid;gap:1.2rem;align-items:center;text-align:center;padding:2.2rem 1.2rem}
.hero h1{margin:.3rem 0;font-size:clamp(1.75rem,6vw,2.8rem);line-height:1.15;letter-spacing:.01em}
.hero .lead,.prose p{font-size:1.05rem;color:#e6defc}
.hero .lead{margin:.4rem auto 1rem;max-width:40rem}
.eyebrow{display:inline-block;font-size:.8rem;text-transform:uppercase;letter-spacing:.14em;color:var(--lilac);border:1px solid var(--line);border-radius:999px;padding:.2rem .8rem}
.row{display:flex;flex-wrap:wrap;gap:.6rem;align-items:center;justify-content:center}
.badges{list-style:none;padding:0;margin:1rem 0 0;display:flex;flex-wrap:wrap;gap:.5rem;justify-content:center;font-size:.88rem;color:var(--muted)}
.badges li{border:1px solid var(--line);border-radius:999px;padding:.25rem .75rem;background:rgba(7,4,15,.6)}
.hero-art{max-width:420px;margin:0 auto;width:100%}
h2{font-size:clamp(1.4rem,4.5vw,1.9rem);margin:.2rem 0 .8rem;letter-spacing:.02em;line-height:1.2}
h3{font-size:1.1rem;margin:.2rem 0 .4rem}
.muted{color:var(--muted)}.small{font-size:.88rem}
.grid{display:grid;gap:.9rem}
.step,.feat,.city{background:#07040f;border:1px solid var(--line);border-radius:18px;padding:1.1rem}
.step .num{display:inline-flex;width:2.2rem;height:2.2rem;border-radius:50%;align-items:center;justify-content:center;background:linear-gradient(90deg,var(--indigo),var(--violet));font-weight:800;margin-bottom:.4rem}
.step p,.feat p{margin:.2rem 0 0;color:#ddd3fb}
.price{display:grid;gap:1rem}
.plan{border:1px solid var(--line);border-radius:20px;padding:1.3rem;background:#07040f}
.plan.pro{border-color:var(--violet);box-shadow:var(--glow)}
.amount{font-size:2.6rem;font-weight:800;line-height:1;margin:.4rem 0}.amount small{font-size:1rem;font-weight:600;color:var(--muted)}
.plan ul{padding-left:1.1rem;margin:.6rem 0 1rem}.plan li{margin:.25rem 0}
.feat svg{width:28px;height:28px;color:var(--lilac)}
.city{padding:0;overflow:hidden;text-decoration:none;color:var(--text);display:block;transition:transform .15s ease}
.city:hover{transform:translateY(-2px)}
.city img{display:block;width:100%;aspect-ratio:5/3;object-fit:cover;background:linear-gradient(135deg,var(--indigo),var(--bg-2))}
.city span{display:block;padding:.7rem .9rem;font-weight:700}.city span em{display:block;font-style:normal;font-weight:400;font-size:.85rem;color:var(--muted)}
.city-carousel{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:.35rem;align-items:center}
.city-track{display:flex;gap:.9rem;overflow-x:auto;scroll-snap-type:x mandatory;list-style:none;padding:.15rem 0 .35rem;margin:0;-webkit-overflow-scrolling:touch;scrollbar-width:thin}
.city-track > li{flex:0 0 100%;scroll-snap-align:start;min-width:0}
.city-arrow{min-width:44px;min-height:44px;border-radius:999px;border:1px solid var(--line);background:#07040f;color:var(--text);font-size:1.5rem;line-height:1;cursor:pointer;padding:0 .2rem}
details{background:#07040f;border:1px solid var(--line);border-radius:14px;padding:.2rem 1rem;margin:0 0 .6rem}
summary{cursor:pointer;font-weight:700;padding:.75rem 0;min-height:44px}
details p{margin:0 0 .9rem;color:#ddd3fb}
.cta-band{text-align:center}
.prose p{margin:.7rem 0}
.crumbs{color:var(--muted);font-size:.92rem;margin:0 0 .8rem}
.site-foot{border-top:1px solid var(--line);padding:1.6rem 1rem 2.2rem;text-align:center;color:var(--muted);font-size:.9rem;background:rgba(0,0,0,.5)}
.site-foot nav{display:flex;flex-wrap:wrap;gap:.3rem .9rem;justify-content:center;margin:.8rem 0}
.site-foot nav a{display:inline-flex;align-items:center;min-height:44px;color:#d8c8ff}
.age18{display:inline-flex;align-items:center;justify-content:center;width:2.4rem;height:2.4rem;border-radius:50%;border:2px solid #ffd0dc;color:#ffd0dc;font-weight:800;font-size:.85rem;margin-right:.4rem;vertical-align:middle}
.gate{position:fixed;inset:0;z-index:50;display:flex;align-items:center;justify-content:center;padding:1rem;background:rgba(5,2,12,.86);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px)}
.gate[hidden]{display:none}
.gate-box{max-width:440px;width:100%;text-align:center;background:var(--card);border:1px solid var(--line);border-radius:22px;padding:1.6rem 1.3rem;box-shadow:var(--glow)}
.gate-box h2{font-size:1.4rem}
.gate-box .row{margin-top:1rem}
@media (min-width:760px){
 .nav-links{display:flex;gap:.2rem}
 main{padding:1.5rem}
 .hero{grid-template-columns:1.15fr .85fr;text-align:left;padding:3rem 2.4rem}
 .hero .lead{margin-left:0}.hero .row,.badges{justify-content:flex-start}
 .card{padding:2rem}
 .g3{grid-template-columns:repeat(3,1fr)}.g2{grid-template-columns:repeat(2,1fr)}.g4{grid-template-columns:repeat(4,1fr)}
 .price{grid-template-columns:1fr 1fr}
 .city-track > li{flex-basis:calc((100% - 1.8rem) / 3)}
}
@media (min-width:1080px){
 .city-track > li{flex-basis:calc((100% - 2.7rem) / 4)}
}
@media (prefers-reduced-motion:reduce){*{transition:none!important;scroll-behavior:auto!important}}
"""

JS = r"""
(function(){
  var carousel = document.querySelector("[data-city-carousel]");
  if (carousel) {
    var track = carousel.querySelector(".city-track");
    var buttons = carousel.querySelectorAll("[data-city-dir]");
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].addEventListener("click", function(){
        if (!track) return;
        var card = track.querySelector("li");
        var width = card ? card.getBoundingClientRect().width + 14 : track.clientWidth;
        var dir = Number(this.getAttribute("data-city-dir")) || 1;
        var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        track.scrollBy({left: width * dir, behavior: reduce ? "auto" : "smooth"});
      });
    }
  }
  var GATE_KEY = "iswing_age_ok";
  var gate = document.getElementById("age-gate"), page = document.getElementById("page");
  var ok = false; try { ok = localStorage.getItem(GATE_KEY) === "1"; } catch (e) {}
  if (!gate || ok) return;
  var last = document.activeElement;
  gate.hidden = false; if (page) page.setAttribute("aria-hidden", "true");
  document.documentElement.style.overflow = "hidden";
  var yes = document.getElementById("age-yes"); yes && yes.focus();
  function close(){
    gate.hidden = true; if (page) page.removeAttribute("aria-hidden");
    document.documentElement.style.overflow = "";
    try { localStorage.setItem(GATE_KEY, "1"); } catch (e) {}
    last && last.focus && last.focus();
  }
  yes && yes.addEventListener("click", close);
  gate.addEventListener("keydown", function(e){
    if (e.key !== "Tab") return;
    var f = gate.querySelectorAll("a,button"), first = f[0], lastEl = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first){ e.preventDefault(); lastEl.focus(); }
    else if (!e.shiftKey && document.activeElement === lastEl){ e.preventDefault(); first.focus(); }
  });
})();
"""


def pack(lang, trial=None):
    tokens = trial_tokens(lang, *trial_bundle(trial))
    raw = apply_tokens(HOME[lang], tokens)
    data = dict(raw)
    data["faq"] = [{"q": q, "a": a, "open": index == 0} for index, (q, a) in enumerate(raw["faq"])]
    data["steps"] = [{"n": i + 1, "title": t, "text": d} for i, (t, d) in enumerate(raw["steps"])]
    data["nav"] = [{"href": href, "label": label} for href, label in raw["nav"]]
    data["legal"] = [{"slug": slug, "label": label} for slug, label in raw["legal"]]
    data["feats"] = [{"icon": ICONS[key], "title": title, "text": text} for key, title, text in raw["feats"]]
    return data


def city_record(key):
    for city in CITIES:
        if city["key"] == key:
            return city
    return None


def city_pack(lang, key, trial=None):
    city = city_record(key)
    if city is None or lang not in city:
        return None
    tokens = trial_tokens(lang, *trial_bundle(trial))
    local = apply_tokens(city[lang], tokens)
    data = dict(local)
    data["key"] = key
    data["svg"] = city["svg"]
    data["path"] = city["paths"][lang]
    data["paths"] = dict(city["paths"])
    data["faqs"] = [{"q": q, "a": a, "open": index == 0} for index, (q, a) in enumerate(data["faqs"])]
    data["url_name"] = f"landing_{lang}_{key}"
    return data


def city_cards(lang):
    cards = []
    for city in CITIES:
        local = city[lang]
        cards.append({
            "key": city["key"],
            "name": local["name"],
            "card": local["card"],
            "svg": city["svg"],
            "path": city["paths"][lang],
            "url_name": f"landing_{lang}_{city['key']}",
        })
    return cards


def alternates(paths, site):
    items = []
    for code in ("fr", "en", "es"):
        items.append({"code": code, "href": site + paths[code]})
    items.append({"code": "x-default", "href": site + paths["fr"]})
    return items


def home_paths():
    return {lang: HOME[lang]["path"] for lang in ("fr", "en", "es")}


def json_ld(lang, city_key=None, site=None, app=None, asset_root=None, trial=None, city=None):
    site = (site or site_url()).rstrip("/")
    app = (app or app_url()).rstrip("/")
    asset_root = (asset_root or (site + "/assets")).rstrip("/")
    page = pack(lang, trial)
    if city is None and city_key:
        city = city_pack(lang, city_key, trial)
    path = city["path"] if city else page["path"]
    url = site + path
    price = price_amount()
    org = site + "/#organization"
    offer_text = ""
    for item in page["faq"]:
        low = item["a"].lower()
        if "j'aime" in low or "per day" in low or "por día" in low:
            offer_text = item["a"]
            break
    graph = [
        {
            "@type": "Organization",
            "@id": org,
            "name": "iSwing",
            "url": site + "/",
            "logo": {"@type": "ImageObject", "url": asset_root + "/logo-240.png", "width": 240, "height": 240},
        },
        {
            "@type": "WebSite",
            "@id": site + "/#website",
            "url": site + "/",
            "name": "iSwing",
            "inLanguage": ["fr", "en", "es"],
            "publisher": {"@id": org},
        },
        {
            "@type": ["MobileApplication", "SoftwareApplication"],
            "@id": site + "/#app",
            "name": "iSwing",
            "description": page["app_desc"],
            "url": app + "/comptes/inscription/",
            "applicationCategory": "LifestyleApplication",
            "operatingSystem": "Web",
            "inLanguage": ["fr", "en", "es"],
            "image": asset_root + "/" + page["og_img"],
            "contentRating": "18+",
            "publisher": {"@id": org},
            "offers": {
                "@type": "Offer",
                "price": price,
                "priceCurrency": PRICE_CURRENCY,
                "description": offer_text,
                "url": app + "/comptes/inscription/",
                "category": "subscription",
                "availability": "https://schema.org/InStock",
                "priceSpecification": {
                    "@type": "UnitPriceSpecification",
                    "price": price,
                    "priceCurrency": PRICE_CURRENCY,
                    "billingDuration": "P1M",
                    "unitCode": "MON",
                    "referenceQuantity": {"@type": "QuantitativeValue", "value": 1, "unitCode": "MON"},
                },
            },
        },
    ]
    webpage = {
        "@type": "WebPage",
        "@id": url + "#webpage",
        "url": url,
        "name": city["title"] if city else page["title"],
        "description": city["desc"] if city else page["desc"],
        "inLanguage": lang,
        "isPartOf": {"@id": site + "/#website"},
        "about": {"@id": site + "/#app"},
    }
    graph.append(webpage)
    questions = city["faqs"] if city else page["faq"]
    graph.append({
        "@type": "FAQPage",
        "@id": url + "#faq",
        "inLanguage": lang,
        "mainEntity": [
            {"@type": "Question", "name": item["q"], "acceptedAnswer": {"@type": "Answer", "text": item["a"]}}
            for item in questions
        ],
    })
    if city:
        graph.append({
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "iSwing", "item": site + page["path"]},
                {"@type": "ListItem", "position": 2, "name": city["name"], "item": url},
            ],
        })
    payload = {"@context": "https://schema.org", "@graph": graph}
    return json.dumps(payload, ensure_ascii=False, indent=1).replace("</", "<\\/")


def _e(value):
    return escape(str(value), quote=True)


def _asset_prefix(path):
    parts = [part for part in path.strip("/").split("/") if part]
    return ("../" * len(parts)) + "assets/"


def _shell(page, city, cards, site, app, body):
    path = city["path"] if city else page["path"]
    prefix = _asset_prefix(path)
    paths = city["paths"] if city else home_paths()
    title = city["title"] if city else page["title"]
    desc = city["desc"] if city else page["desc"]
    kw = city["kw"] if city else page["kw"]
    url = site + path
    og = site + "/assets/" + page["og_img"]
    alts = "".join(f'<link rel="alternate" hreflang="{item["code"]}" href="{item["href"]}">' for item in alternates(paths, site))
    locales = "".join(f'<meta property="og:locale:alternate" content="{_e(loc)}">' for loc in page["og_alternates"])
    langs = {"fr": "FR", "en": "EN", "es": "ES"}
    parts = []
    for code in ("fr", "en", "es"):
        current = ' aria-current="true"' if code == page["lang"] else ""
        parts.append(
            f'<a class="lang" href="{site}{paths[code]}" hreflang="{code}" lang="{code}"{current}>{langs[code]}</a>'
        )
    lang_nav = "".join(parts)
    nav = "".join(f'<a href="{_e(item["href"])}">{_e(item["label"])}</a>' for item in page["nav"]) if not city else ""
    legal = "".join(
        f'<a href="{app}/legal/{_e(item["slug"])}/">{_e(item["label"])}</a>' for item in page["legal"]
    )
    home_href = site + page["path"]
    preconnect = ""
    if site != app:
        preconnect = f'<link rel="preconnect" href="{app}">'
    signup = app + "/comptes/inscription/"
    login = app + "/comptes/connexion/"
    return f"""<!DOCTYPE html>
<html lang="{page['lang']}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(title)}</title>
<meta name="description" content="{_e(desc)}">
<meta name="keywords" content="{_e(kw)}">
<meta name="robots" content="index,follow,max-image-preview:large">
<meta name="rating" content="adult">
<meta name="theme-color" content="#5030e0">
<link rel="canonical" href="{url}">
{alts}
<link rel="icon" type="image/png" sizes="192x192" href="{prefix}icon-192.png">
<link rel="apple-touch-icon" href="{prefix}icon-192.png">
{preconnect}
<meta property="og:type" content="website">
<meta property="og:site_name" content="iSwing">
<meta property="og:locale" content="{page['locale']}">
{locales}
<meta property="og:title" content="{_e(title)}">
<meta property="og:description" content="{_e(desc)}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{og}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="{_e(page['og_alt'])}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{_e(title)}">
<meta name="twitter:description" content="{_e(desc)}">
<meta name="twitter:image" content="{og}">
<meta name="twitter:image:alt" content="{_e(page['og_alt'])}">
<script type="application/ld+json">
{json_ld(page['lang'], city['key'] if city else None, site, app)}
</script>
<style>{CSS.strip()}</style>
</head>
<body>
<div id="age-gate" class="gate" role="dialog" aria-modal="true" aria-labelledby="gate-title" aria-describedby="gate-text" hidden>
 <div class="gate-box">
  <img src="{prefix}logo-80.webp" alt="" width="64" height="64">
  <h2 id="gate-title"><span class="age18" aria-hidden="true">18+</span>{_e(page['gate_title'])}</h2>
  <p id="gate-text" class="muted">{_e(page['gate_text'])}</p>
  <div class="row">
   <button type="button" id="age-yes" class="btn">{_e(page['gate_yes'])}</button>
   <a class="btn ghost" href="{LEAVE_URL}" rel="nofollow">{_e(page['gate_no'])}</a>
  </div>
 </div>
</div>
<div id="page">
<a class="skip" href="#main">{_e(page['skip'])}</a>
<header class="top">
 <a class="brand" href="{home_href}" aria-label="iSwing">
  <img src="{prefix}logo-80.webp" alt="iSwing" width="40" height="40"><span>iSwing</span>
 </a>
 <nav aria-label="{_e(page['nav_label'])}">
  <div class="nav-links">{nav}</div>
  <nav class="langs" aria-label="{_e(page['lang_nav_label'])}">{lang_nav}</nav>
  <a class="btn sm" href="{signup}">{_e(page['cta_short'])}</a>
 </nav>
</header>
<main id="main">
{body}
</main>
<footer class="site-foot">
 <a class="brand" href="{home_href}" style="justify-content:center" aria-label="iSwing">
  <img src="{prefix}logo-80.webp" alt="iSwing" width="40" height="40" loading="lazy" decoding="async"><span>iSwing</span>
 </a>
 <nav aria-label="{_e(page['foot_legal'])}">{legal}</nav>
 <p><span class="age18" aria-hidden="true">18+</span>{_e(page['foot_18'])}</p>
 <p>{lang_nav}</p>
 <p class="small">{_e(page['foot_copy'])}</p>
</footer>
</div>
<script>{JS.strip()}</script>
</body>
</html>
"""


def _home_body(page, cards, site, app):
    prefix = _asset_prefix(page["path"])
    steps = "".join(
        f'<li class="step"><span class="num" aria-hidden="true">{item["n"]}</span><h3>{_e(item["title"])}</h3><p>{_e(item["text"])}</p></li>'
        for item in page["steps"]
    )
    trial = "".join(f"<li>{_e(item)}</li>" for item in page["trial_items"])
    pro = "".join(f"<li>{_e(item)}</li>" for item in page["pro_items"])
    feats = "".join(
        f'<li class="feat">{item["icon"]}<h3>{_e(item["title"])}</h3><p>{_e(item["text"])}</p></li>'
        for item in page["feats"]
    )
    cities = "".join(
        f'<li><a class="city" href="{site}{item["path"]}"><img src="{prefix}{item["svg"]}" alt="{_e(page["city_alt"].format(name=item["name"]))}" width="400" height="240" loading="lazy" decoding="async"><span>{_e(item["name"])}<em>{_e(item["card"])}</em></span></a></li>'
        for item in cards
    )
    faq = "".join(
        f'<details{" open" if item["open"] else ""}><summary>{_e(item["q"])}</summary><p>{_e(item["a"])}</p></details>'
        for item in page["faq"]
    )
    signup = app + "/comptes/inscription/"
    login = app + "/comptes/connexion/"
    billing = app + "/legal/abonnements/"
    badges = "".join(f"<li>{_e(item)}</li>" for item in page["badges"])
    return f"""<section class="hero" aria-labelledby="h1">
 <div>
  <span class="eyebrow">{_e(page['eyebrow'])}</span>
  <h1 id="h1">{_e(page['h1'])}</h1>
  <p class="lead">{_e(page['lead'])}</p>
  <div class="row">
   <a class="btn lg" href="{signup}">{_e(page['cta_main'])}</a>
   <a class="btn ghost" href="{login}">{_e(page['cta_login'])}</a>
  </div>
  <ul class="badges">{badges}</ul>
 </div>
 <img class="hero-art" src="{prefix}hero-rings.svg" alt="{_e(page['hero_alt'])}" width="480" height="360" fetchpriority="high">
</section>
<section id="{page['how_id']}" class="card" aria-labelledby="how-h">
 <h2 id="how-h">{_e(page['how_h'])}</h2>
 <p class="muted">{_e(page['how_intro'])}</p>
 <ol class="grid g3" style="list-style:none;padding:0;margin:0">{steps}</ol>
</section>
<section id="{page['price_id']}" class="card" aria-labelledby="price-h">
 <h2 id="price-h">{_e(page['price_h'])}</h2>
 <p class="muted">{_e(page['price_intro'])}</p>
 <div class="price">
  <article class="plan" aria-labelledby="plan-trial">
   <h3 id="plan-trial">{_e(page['trial_name'])}</h3>
   <p class="amount">{_e(page['trial_figure'])} <small>{_e(page['trial_period'])}</small></p>
   <ul>{trial}</ul>
   <a class="btn ghost" href="{signup}">{_e(page['trial_cta'])}</a>
  </article>
  <article class="plan pro" aria-labelledby="plan-pro">
   <h3 id="plan-pro">{_e(page['pro_name'])}</h3>
   <p class="amount">{_e(page['pro_figure'])} <small>{_e(page['pro_period'])}</small></p>
   <ul>{pro}</ul>
   <a class="btn" href="{signup}">{_e(page['pro_cta'])}</a>
  </article>
 </div>
 <p class="small muted">{_e(page['price_note'])} <a href="{billing}">{_e(page['price_note_link'])}</a>.</p>
</section>
<section id="{page['safe_id']}" class="card" aria-labelledby="safe-h">
 <h2 id="safe-h">{_e(page['safe_h'])}</h2>
 <p class="muted">{_e(page['safe_intro'])}</p>
 <ul class="grid g3" style="list-style:none;padding:0;margin:0">{feats}</ul>
</section>
<section id="{page['city_id']}" class="card" aria-labelledby="city-h">
 <h2 id="city-h">{_e(page['city_h'])}</h2>
 <p class="muted">{_e(page['city_intro'])}</p>
 <div class="city-carousel" data-city-carousel>
  <button type="button" class="city-arrow" data-city-dir="-1" aria-label="{_e(page['city_prev'])}">‹</button>
  <ul class="city-track">{cities}</ul>
  <button type="button" class="city-arrow" data-city-dir="1" aria-label="{_e(page['city_next'])}">›</button>
 </div>
</section>
<section id="{page['faq_id']}" class="card" aria-labelledby="faq-h">
 <h2 id="faq-h">{_e(page['faq_h'])}</h2>
 {faq}
</section>
<section class="card cta-band" aria-labelledby="band-h">
 <h2 id="band-h">{_e(page['band_h'])}</h2>
 <p class="muted">{_e(page['band_p'])}</p>
 <a class="btn lg" href="{signup}">{_e(page['cta_main'])}</a>
</section>
"""


def _city_body(page, city, site, app):
    prefix = _asset_prefix(city["path"])
    paragraphs = "".join(f"<p>{_e(text)}</p>" for text in city["paragraphs"])
    faq = "".join(
        f'<details{" open" if item["open"] else ""}><summary>{_e(item["q"])}</summary><p>{_e(item["a"])}</p></details>'
        for item in city["faqs"]
    )
    signup = app + "/comptes/inscription/"
    return f"""<article class="card prose">
 <p class="crumbs"><a href="{site}{page['path']}">iSwing</a> · {_e(city['name'])}</p>
 <h1>{_e(city['h1'])}</h1>
 {paragraphs}
 <p><a class="btn lg" href="{signup}">{_e(page['cta_main'])}</a></p>
</article>
<section class="card" aria-labelledby="city-faq">
 <h2 id="city-faq">{_e(page['faq_h'])}</h2>
 {faq}
</section>
<section class="card">
 <img src="{prefix}{city['svg']}" alt="{_e(page['city_alt'].format(name=city['name']))}" width="400" height="240">
</section>
"""


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)


def _sitemap(site):
    groups = [(home_paths(), "/")]
    for city in CITIES:
        groups.append((city["paths"], city["paths"]["fr"]))
    lastmod = "2026-10-12"
    urls = []
    for paths, _loc in groups:
        for code in ("fr", "en", "es"):
            links = "".join(
                f'<xhtml:link rel="alternate" hreflang="{lang}" href="{site}{paths[lang]}"/>'
                for lang in ("fr", "en", "es")
            )
            links += f'<xhtml:link rel="alternate" hreflang="x-default" href="{site}{paths["fr"]}"/>'
            urls.append(
                f"  <url><loc>{site}{paths[code]}</loc>{links}<lastmod>{lastmod}</lastmod></url>"
            )
    body = "\n".join(urls)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">
{body}
</urlset>
"""


def _robots(site):
    return (
        "User-agent: *\n"
        "Allow: /\n"
        "\n"
        f"Sitemap: {site}/sitemap.xml\n"
    )


def build():
    if MODE not in PROFILES:
        raise SystemExit("MODE doit être TEST ou LIVE")
    site, app = site_url(), app_url()
    pages = []
    for lang in ("fr", "en", "es"):
        page = pack(lang)
        cards = city_cards(lang)
        html = _shell(page, None, cards, site, app, _home_body(page, cards, site, app))
        relative = "index.html" if lang == "fr" else f"{lang}/index.html"
        _write(os.path.join(ROOT, relative), html)
        pages.append(html)
        for city in CITIES:
            packed = city_pack(lang, city["key"])
            city_html = _shell(page, packed, cards, site, app, _city_body(page, packed, site, app))
            _write(os.path.join(ROOT, packed["path"].strip("/"), "index.html"), city_html)
            pages.append(city_html)
            text = " ".join(packed["paragraphs"])
            if word_count(text) < 300:
                raise SystemExit(f"Texte trop court ({word_count(text)} mots) : {lang} {city['key']}")
    _write(os.path.join(ROOT, "sitemap.xml"), _sitemap(site))
    _write(os.path.join(ROOT, "robots.txt"), _robots(site))
    static_dir = os.path.join(PROJECT, "static", "landing")
    if os.path.isfile(os.path.join(PROJECT, "manage.py")):
        os.makedirs(static_dir, exist_ok=True)
        assets = os.path.join(ROOT, "assets")
        for name in os.listdir(assets):
            source = os.path.join(assets, name)
            if os.path.isfile(source) and not name.startswith("source-"):
                shutil.copy2(source, os.path.join(static_dir, name))
        _write(os.path.join(static_dir, "landing.css"), CSS.strip() + "\n")
        _write(os.path.join(static_dir, "gate.js"), JS.strip() + "\n")
    blob = "\n".join(pages)
    forbidden = ["data-app=", "PLACEHOLDER", "À CONFIRMER", "TO CONFIRM", "iswing.live" if MODE == "TEST" else "iswingtest.onrender.com"]
    if MODE == "TEST":
        forbidden.append("app.iswing.live")
    for token in forbidden:
        if token in blob:
            raise SystemExit("Jeton interdit dans le HTML généré : " + token)
    if price_amount() not in blob or PRICE_CURRENCY not in blob:
        raise SystemExit("Le prix schéma est absent du HTML")
    if site not in blob or app not in blob:
        raise SystemExit("SITE_URL ou APP_URL absent du HTML")
    print("landing OK", MODE, site, app, price_amount(), PRICE_CURRENCY, "pages", len(pages))


if __name__ == "__main__":
    build()
