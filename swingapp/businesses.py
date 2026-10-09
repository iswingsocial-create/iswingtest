"""Comptes entreprise, événements et pushs. Hors découverte et hors messagerie."""

from datetime import date, datetime, timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import F, Q
from django.http import FileResponse, Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .gestion import staff_only
from .i18n import t
from .models import (
    BusinessAccount,
    BusinessDocument,
    BusinessInvoice,
    BusinessPhoto,
    BusinessPush,
    Campaign,
    CampaignDelivery,
    Event,
    EventPhoto,
    EventRsvp,
    Profile,
    SiteSetting,
    User,
)
from .services import haversine_km, placed, send_campaign

CATEGORIES = [
    ("club", "biz_cat_club"),
    ("sauna", "biz_cat_sauna"),
    ("party", "biz_cat_party"),
    ("travel", "biz_cat_travel"),
    ("cruise", "biz_cat_cruise"),
    ("shop", "biz_cat_shop"),
    ("photo", "biz_cat_photo"),
    ("organizer", "biz_cat_organizer"),
    ("other", "biz_cat_other"),
]


def businesses_enabled():
    return SiteSetting.get("businesses_enabled", "0") == "1"


def ticketing_enabled():
    """Réglage de réserve. La vente et la commission ne sont pas branchées."""
    return SiteSetting.get("ticketing_enabled", "0") == "1"


def ticket_sale_ready():
    return False


def price_of(key, default="0"):
    raw = SiteSetting.get(key, default)
    try:
        return max(0, int(str(raw).strip() or "0"))
    except ValueError:
        return 0


def plan_active(biz, today=None):
    today = today or timezone.localdate()
    if biz.plan_status != "active":
        return False
    if biz.plan_until and biz.plan_until < today:
        return False
    return True


def verified_badge(biz):
    return bool(biz.verified and plan_active(biz))


def _need_module():
    if not businesses_enabled():
        raise Http404("entreprises")


def _lang(request):
    return getattr(request, "lang", "fr")


def _cats(lang):
    return [(code, t(lang, key)) for code, key in CATEGORIES]


def _own(request):
    profile = getattr(request.user, "profile", None)
    if profile is None or profile.kind != "business":
        return None
    return getattr(profile, "business", None)


def _parse_dt(raw):
    value = datetime.fromisoformat((raw or "").strip())
    if timezone.is_naive(value):
        value = timezone.make_aware(value, timezone.get_current_timezone())
    return value


def _age_ok(birth):
    today = timezone.localdate()
    years = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
    return years >= 18


def push_audience(lat, lng, radius_km, category=""):
    radius = max(1, min(int(radius_km or 1), 500))
    qs = Profile.objects.select_related("user").exclude(kind="business").exclude(suspended=True)
    qs = qs.filter(user__promo_consent=True).exclude(lat__isnull=True)
    if category:
        qs = qs.filter(Q(desires__icontains=category) | Q(seeking__icontains=category))
    found = []
    for profile in qs.iterator():
        plat, plng, _city = placed(profile)
        km = haversine_km(lat, lng, plat, plng)
        if km is not None and km <= radius:
            found.append(profile)
        if len(found) >= 5000:
            break
    return found


def _public_events():
    now = timezone.now() - timedelta(hours=6)
    rows = []
    for event in Event.objects.select_related("business", "business__profile").filter(published=True, ends_at__gte=now):
        if plan_active(event.business):
            rows.append(event)
    return rows


@login_required
def business_list(request):
    _need_module()
    lang = _lang(request)
    rows = []
    for biz in BusinessAccount.objects.select_related("profile").order_by("profile__display_name"):
        if not plan_active(biz):
            continue
        rows.append({"biz": biz, "badge": verified_badge(biz), "category": t(lang, "biz_cat_" + biz.category)})
    return render(request, "businesses.html", {"rows": rows, "categories": _cats(lang)})


@login_required
def business_page(request, pk):
    _need_module()
    biz = get_object_or_404(BusinessAccount.objects.select_related("profile"), profile_id=pk)
    if not plan_active(biz) and _own(request) != biz:
        raise Http404("entreprise")
    BusinessAccount.objects.filter(pk=biz.pk).update(views=F("views") + 1)
    biz.refresh_from_db()
    lang = _lang(request)
    events = [event for event in biz.events.filter(published=True, ends_at__gte=timezone.now() - timedelta(hours=6))]
    return render(request, "business.html", {
        "biz": biz,
        "badge": verified_badge(biz),
        "category": t(lang, "biz_cat_" + biz.category),
        "events": events,
        "photos": biz.photos.all()[:12],
        "ticketing_on": ticketing_enabled(),
        "sale_ready": ticket_sale_ready(),
    })


def business_signup(request):
    _need_module()
    lang = _lang(request)
    error = ""
    if request.method == "POST":
        email = (request.POST.get("email") or "").strip().lower()
        password = request.POST.get("password") or ""
        name = (request.POST.get("name") or "").strip()[:40]
        category = request.POST.get("category") if request.POST.get("category") in dict(CATEGORIES) else "other"
        try:
            birth = date.fromisoformat(request.POST.get("birth") or "")
        except ValueError:
            birth = None
        if not email or User.objects.filter(email__iexact=email).exists():
            error = "email"
        elif len(password) < 10 or not name or birth is None or not _age_ok(birth):
            error = "form"
        elif request.POST.get("accept") != "on":
            error = "accept"
        else:
            user = User.objects.create_user(
                email=email,
                password=password,
                birth_date=birth,
                terms_accepted_at=timezone.now(),
                adult_declared=True,
                intimate_consent=True,
            )
            profile = Profile.objects.create(
                user=user, display_name=name, kind="business", city=(request.POST.get("city") or "")[:80], bio="",
            )
            try:
                profile.lat = float(request.POST.get("lat") or "")
                profile.lng = float(request.POST.get("lng") or "")
            except ValueError:
                profile.lat = profile.lng = None
            profile.save()
            BusinessAccount.objects.create(
                profile=profile,
                category=category,
                description=(request.POST.get("description") or "")[:4000],
                address=(request.POST.get("address") or "")[:160],
                website=(request.POST.get("website") or "")[:200],
                ticket_url=(request.POST.get("ticket_url") or "")[:200],
            )
            from django.contrib.auth import login
            login(request, user)
            return redirect("business_home")
    return render(request, "business_signup.html", {"error": error, "categories": _cats(lang)})


@login_required
def business_home(request):
    _need_module()
    biz = _own(request)
    if biz is None:
        return redirect("business_list")
    lang = _lang(request)
    if request.method == "POST" and request.POST.get("action") == "profile":
        biz.profile.display_name = (request.POST.get("name") or biz.profile.display_name)[:40]
        biz.profile.city = (request.POST.get("city") or "")[:80]
        try:
            biz.profile.lat = float(request.POST.get("lat") or "")
            biz.profile.lng = float(request.POST.get("lng") or "")
        except ValueError:
            pass
        biz.profile.save()
        category = request.POST.get("category")
        biz.category = category if category in dict(CATEGORIES) else biz.category
        biz.description = (request.POST.get("description") or "")[:4000]
        biz.address = (request.POST.get("address") or "")[:160]
        biz.website = (request.POST.get("website") or "")[:200]
        biz.ticket_url = (request.POST.get("ticket_url") or "")[:200]
        if request.FILES.get("logo"):
            biz.logo.save(request.FILES["logo"].name, request.FILES["logo"], save=False)
        biz.save()
        for upload in request.FILES.getlist("photos"):
            BusinessPhoto.objects.create(business=biz, image=upload)
        return redirect("business_home")
    events = list(biz.events.all())
    return render(request, "business_home.html", {
        "biz": biz,
        "badge": verified_badge(biz),
        "plan_on": plan_active(biz),
        "categories": _cats(lang),
        "events": events,
        "plan_price": price_of("business_plan_price"),
        "push_price": price_of("business_push_price"),
        "show_prices": False,
    })


@login_required
@require_POST
def business_document(request):
    _need_module()
    biz = _own(request)
    if biz is None or not request.FILES.get("document"):
        return redirect("business_home")
    upload = request.FILES["document"]
    if upload.size > 8 * 1024 * 1024:
        return redirect("business_home")
    BusinessDocument.objects.create(business=biz, document=upload)
    return redirect("business_home")


@login_required
@require_POST
def event_save(request):
    _need_module()
    biz = _own(request)
    if biz is None:
        return redirect("business_list")
    try:
        starts = _parse_dt(request.POST.get("starts"))
        ends = _parse_dt(request.POST.get("ends"))
    except ValueError:
        return redirect("business_home")
    if ends < starts or not (request.POST.get("title") or "").strip():
        return redirect("business_home")
    capacity = None
    raw_cap = (request.POST.get("capacity") or "").strip()
    if raw_cap.isdigit():
        capacity = int(raw_cap)
    category = request.POST.get("category") if request.POST.get("category") in dict(CATEGORIES) else "party"
    published = request.POST.get("published") == "1" and plan_active(biz)
    event = Event.objects.create(
        business=biz,
        title=(request.POST.get("title") or "").strip()[:120],
        category=category,
        starts_at=starts,
        ends_at=ends,
        place=(request.POST.get("place") or "")[:160],
        city=(request.POST.get("city") or "")[:80],
        description=(request.POST.get("description") or "")[:4000],
        practical=(request.POST.get("practical") or "")[:4000],
        price_note=(request.POST.get("price_note") or "")[:240],
        ticket_url=(request.POST.get("ticket_url") or "")[:200],
        capacity=capacity,
        published=published,
    )
    try:
        event.lat = float(request.POST.get("lat") or "")
        event.lng = float(request.POST.get("lng") or "")
        event.save(update_fields=["lat", "lng"])
    except ValueError:
        pass
    for upload in request.FILES.getlist("photos"):
        EventPhoto.objects.create(event=event, image=upload)
    return redirect("business_guests", pk=event.id)


@login_required
def event_list(request):
    _need_module()
    lang = _lang(request)
    city = (request.GET.get("city") or "").strip()
    category = (request.GET.get("category") or "").strip()
    day = (request.GET.get("date") or "").strip()
    rows = _public_events()
    if city:
        rows = [event for event in rows if city.lower() in (event.city or "").lower()]
    if category in dict(CATEGORIES):
        rows = [event for event in rows if event.category == category]
    if day:
        rows = [event for event in rows if timezone.localtime(event.starts_at).date().isoformat() == day]
    return render(request, "events.html", {"events": rows, "categories": _cats(lang), "city": city, "category": category, "date": day})


@login_required
def event_page(request, pk):
    _need_module()
    event = get_object_or_404(Event.objects.select_related("business", "business__profile"), pk=pk)
    owner = _own(request) == event.business
    if (not event.published or not plan_active(event.business)) and not owner:
        raise Http404("evenement")
    if not owner:
        Event.objects.filter(pk=event.pk).update(views=F("views") + 1)
    mine = EventRsvp.objects.filter(event=event, user=request.user).first()
    going = event.rsvps.filter(status="going").count()
    return render(request, "event.html", {
        "event": event,
        "biz": event.business,
        "badge": verified_badge(event.business),
        "category": t(_lang(request), "biz_cat_" + event.category),
        "mine": mine,
        "going": going,
        "full": bool(event.capacity and going >= event.capacity),
        "photos": event.photos.all()[:8],
        "ticketing_on": ticketing_enabled(),
        "sale_ready": ticket_sale_ready(),
    })


@login_required
def event_ticket(request, pk):
    """Point d'entrée futur. Aucun encaissement et aucune commission."""
    _need_module()
    event = get_object_or_404(Event, pk=pk, published=True)
    if not ticketing_enabled() or not ticket_sale_ready():
        return render(request, "event_ticket.html", {"event": event, "standby": True}, status=200 if ticketing_enabled() else 404)
    return render(request, "event_ticket.html", {"event": event, "standby": True})


@login_required
@require_POST
def event_rsvp(request, pk):
    _need_module()
    if getattr(request.user.profile, "kind", "") == "business":
        return HttpResponseForbidden("entreprise")
    event = get_object_or_404(Event, pk=pk, published=True)
    if not plan_active(event.business):
        raise Http404("evenement")
    wanted = request.POST.get("status") if request.POST.get("status") in ("interested", "going") else "interested"
    anonymous = request.POST.get("anonymous") == "1"
    row = EventRsvp.objects.filter(event=event, user=request.user).first()
    status = wanted
    if wanted == "going":
        going = event.rsvps.filter(status="going")
        if row:
            going = going.exclude(pk=row.pk)
        if event.capacity and going.count() >= event.capacity:
            status = "waitlist"
    if row is None:
        EventRsvp.objects.create(event=event, user=request.user, status=status, anonymous=anonymous)
    else:
        row.status = status
        row.anonymous = anonymous
        row.save(update_fields=["status", "anonymous"])
    return redirect("event_page", pk=event.id)


@login_required
def business_guests(request, pk):
    _need_module()
    biz = _own(request)
    event = get_object_or_404(Event, pk=pk)
    if biz is None or event.business_id != biz.id:
        return HttpResponseForbidden("invités")
    guests = []
    for row in event.rsvps.select_related("user", "user__profile"):
        guests.append({
            "status": row.status,
            "anonymous": row.anonymous,
            "name": "" if row.anonymous else row.user.profile.display_name,
        })
    return render(request, "business_guests.html", {"event": event, "guests": guests, "biz": biz})


@login_required
def business_push(request):
    _need_module()
    biz = _own(request)
    if biz is None:
        return redirect("business_list")
    lang = _lang(request)
    preview = None
    error = ""
    if request.method == "POST":
        if not plan_active(biz):
            error = "plan"
        else:
            try:
                lat = float(request.POST.get("lat") or "")
                lng = float(request.POST.get("lng") or "")
                radius = int(request.POST.get("radius") or "30")
            except ValueError:
                lat = lng = None
                radius = 30
            category = request.POST.get("category") or ""
            if category not in dict(CATEGORIES):
                category = ""
            if lat is None:
                error = "place"
            else:
                people = push_audience(lat, lng, radius, category)
                preview = len(people)
                if request.POST.get("action") == "send":
                    if preview == 0:
                        error = "empty"
                    else:
                        event = None
                        raw_event = request.POST.get("event") or ""
                        if raw_event.isdigit():
                            event = biz.events.filter(pk=int(raw_event)).first()
                        amount = price_of("business_push_price")
                        body = (request.POST.get("body") or "").strip()[:2000] or (event.title if event else biz.profile.display_name)
                        campaign = Campaign.objects.create(
                            sender=request.user,
                            subject=(event.title if event else biz.profile.display_name)[:180],
                            body=body,
                            channel="notice",
                            is_promo=True,
                            criteria=f"city={request.POST.get('city','')};r={radius};cat={category}"[:300],
                            status="draft",
                        )
                        CampaignDelivery.objects.bulk_create([
                            CampaignDelivery(campaign=campaign, user=profile.user) for profile in people
                        ])
                        send_campaign(campaign)
                        push = BusinessPush.objects.create(
                            business=biz, event=event, city=(request.POST.get("city") or "")[:80],
                            lat=lat, lng=lng, radius_km=max(1, min(radius, 500)), category=category,
                            body=body, audience=preview, amount=amount, campaign=campaign, status="sent",
                        )
                        BusinessInvoice.objects.create(business=biz, kind="push", amount=amount, status="due", note=f"push {push.id}")
                        return redirect("business_home")
    return render(request, "business_push.html", {
        "biz": biz,
        "events": biz.events.filter(published=True),
        "categories": _cats(lang),
        "preview": preview,
        "reached": t(lang, "biz_reached").format(count=preview) if preview is not None else "",
        "error": error,
        "plan_on": plan_active(biz),
    })


@login_required
def business_media(request, kind, pk):
    _need_module()
    if kind == "logo":
        biz = get_object_or_404(BusinessAccount, pk=pk)
        handle = biz.logo
    elif kind == "photo":
        row = get_object_or_404(BusinessPhoto, pk=pk)
        handle = row.image
    elif kind == "event":
        row = get_object_or_404(EventPhoto, pk=pk)
        handle = row.image
    elif kind == "doc":
        row = get_object_or_404(BusinessDocument, pk=pk)
        owner = _own(request)
        if not request.user.is_staff and (owner is None or owner.id != row.business_id):
            return HttpResponseForbidden("document")
        handle = row.document
    else:
        raise Http404("media")
    if not handle:
        raise Http404("media")
    return FileResponse(handle.open("rb"))


@staff_only
def gestion_businesses(request):
    if request.method == "POST":
        action = request.POST.get("action") or "settings"
        if action == "settings":
            SiteSetting.objects.update_or_create(
                key="businesses_enabled",
                defaults={"value": "1" if request.POST.get("businesses_enabled") == "1" else "0"},
            )
            SiteSetting.objects.update_or_create(
                key="ticketing_enabled",
                defaults={"value": "1" if request.POST.get("ticketing_enabled") == "1" else "0"},
            )
            for key in ("business_plan_price", "business_push_price"):
                raw = (request.POST.get(key) or "0").strip()
                if raw.isdigit():
                    SiteSetting.objects.update_or_create(key=key, defaults={"value": raw[:12]})
        elif action == "plan":
            biz = get_object_or_404(BusinessAccount, pk=request.POST.get("business"))
            status = request.POST.get("plan_status") if request.POST.get("plan_status") in ("none", "active", "unpaid", "canceled") else "none"
            biz.plan_status = status
            until = (request.POST.get("plan_until") or "").strip()
            try:
                biz.plan_until = date.fromisoformat(until) if until else None
            except ValueError:
                biz.plan_until = None
            biz.save(update_fields=["plan_status", "plan_until"])
            if status == "active":
                BusinessInvoice.objects.create(business=biz, kind="plan", amount=price_of("business_plan_price"), status="due", note="abonnement")
        elif action == "doc":
            doc = get_object_or_404(BusinessDocument, pk=request.POST.get("document"))
            choice = request.POST.get("decision")
            if choice == "approve":
                doc.status = "approved"
                doc.business.verified = True
                doc.business.save(update_fields=["verified"])
            elif choice == "refuse":
                doc.status = "rejected"
                doc.note = (request.POST.get("note") or "")[:240]
                doc.business.verified = False
                doc.business.save(update_fields=["verified"])
            doc.save(update_fields=["status", "note"])
        return redirect("gestion_businesses")
    return render(request, "gestion/businesses.html", {
        "section": "businesses",
        "enabled": businesses_enabled(),
        "ticketing": ticketing_enabled(),
        "sale_ready": ticket_sale_ready(),
        "plan_price": SiteSetting.get("business_plan_price", "0"),
        "push_price": SiteSetting.get("business_push_price", "0"),
        "rows": BusinessAccount.objects.select_related("profile", "profile__user").prefetch_related("documents", "invoices"),
    })
