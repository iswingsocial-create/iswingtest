"""Comptes entreprise, événements et pushs. Hors découverte et hors messagerie."""

import json
import secrets
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
    Prospect,
    SellerPayout,
    SiteSetting,
    User,
)
from .services import haversine_km, is_seller, placed, queue_email, send_campaign

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


def push_audience(lat, lng, radius_km, kinds=None):
    radius = max(1, min(int(radius_km or 1), 500))
    qs = Profile.objects.select_related("user").exclude(kind="business").exclude(suspended=True)
    qs = qs.filter(user__promo_consent=True).exclude(lat__isnull=True)
    chosen = [kind for kind in (kinds or ["single", "couple"]) if kind in ("single", "couple")]
    if not chosen:
        return []
    qs = qs.filter(kind__in=chosen)
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
        if not email or User.objects.filter(email__iexact=email).exists():
            error = "email"
        elif len(password) < 10 or not name:
            error = "form"
        elif request.POST.get("accept") != "on":
            error = "accept"
        else:
            user = User.objects.create_user(
                email=email,
                password=password,
                birth_date=None,
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


def _kinds_from(request):
    if "kind" not in request.POST:
        return ["single", "couple"]
    return [kind for kind in request.POST.getlist("kind") if kind in ("single", "couple")]


def _invoice(biz, kind, amount, note):
    return BusinessInvoice.objects.create(
        business=biz, kind=kind, amount=amount, status="due", note=note[:180], sold_by=biz.sold_by,
    )


def settle_invoice_from_stripe(payload):
    meta = payload.get("metadata") or {}
    raw = str(meta.get("invoice_id") or "")
    if not raw.isdigit():
        return False
    row = BusinessInvoice.objects.filter(pk=int(raw), status="due").first()
    if row is None:
        return False
    row.status = "paid"
    row.paid_at = timezone.now()
    row.payment_ref = str(payload.get("id") or row.payment_ref or "")[:80]
    row.save(update_fields=["status", "paid_at", "payment_ref"])
    return True


def create_business_payment_link(invoice):
    if SiteSetting.get("business_pay_provider", "manual") != "stripe":
        return ""
    secret = SiteSetting.get("business_stripe_secret", "")
    if not secret:
        return ""
    import stripe

    stripe.api_key = secret
    currency = (SiteSetting.get("business_currency", "CAD") or "CAD").lower()
    link = stripe.PaymentLink.create(
        line_items=[{
            "price_data": {
                "currency": currency,
                "unit_amount": int(invoice.amount),
                "product_data": {"name": (invoice.note or invoice.kind)[:120] or "iSwing"},
            },
            "quantity": 1,
        }],
        metadata={"invoice_id": str(invoice.id)},
    )
    url = getattr(link, "url", "") or ""
    invoice.payment_url = str(url)[:300]
    invoice.payment_ref = str(getattr(link, "id", "") or "")[:80]
    invoice.save(update_fields=["payment_url", "payment_ref"])
    return invoice.payment_url


def commission_rate():
    raw = SiteSetting.get("business_commission_rate", "50")
    try:
        return max(0, min(100, int(str(raw).strip() or "50")))
    except ValueError:
        return 50


def commission_rows(seller=None):
    rate = commission_rate()
    qs = BusinessInvoice.objects.filter(status="paid", sold_by__isnull=False).select_related("sold_by")
    if seller is not None:
        qs = qs.filter(sold_by=seller)
    buckets = {}
    for row in qs:
        when = row.paid_at or row.created_at
        period = timezone.localtime(when).strftime("%Y-%m")
        key = (row.sold_by_id, period)
        bucket = buckets.setdefault(key, {"seller": row.sold_by, "period": period, "paid": 0, "count": 0})
        bucket["paid"] += row.amount
        bucket["count"] += 1
    marked = {(row.seller_id, row.period): row.paid_at for row in SellerPayout.objects.all()}
    out = []
    for key, bucket in sorted(buckets.items(), key=lambda item: (item[0][1], item[0][0] or 0), reverse=True):
        due = bucket["paid"] * rate // 100
        bucket["rate"] = rate
        bucket["due"] = due
        bucket["paid_out"] = marked.get(key)
        out.append(bucket)
    return out


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
            kinds = _kinds_from(request)
            purpose = request.POST.get("purpose") if request.POST.get("purpose") in ("ad", "event", "coupon") else "ad"
            if lat is None:
                error = "place"
            else:
                people = push_audience(lat, lng, radius, kinds)
                preview = len(people)
                if request.POST.get("action") == "send":
                    if preview == 0:
                        error = "empty"
                    else:
                        event = None
                        raw_event = request.POST.get("event") or ""
                        if raw_event.isdigit():
                            event = biz.events.filter(pk=int(raw_event), published=True).first()
                        if purpose == "event" and event is None:
                            error = "event"
                        else:
                            ends = None
                            if purpose == "coupon":
                                try:
                                    ends = date.fromisoformat(request.POST.get("offer_ends") or "")
                                except ValueError:
                                    ends = None
                            amount = price_of("business_push_price")
                            body = (request.POST.get("body") or "").strip()[:2000]
                            if purpose == "coupon":
                                extra = " ".join(part for part in (
                                    request.POST.get("promo_code") or "",
                                    request.POST.get("offer_details") or "",
                                ) if part).strip()
                                if extra:
                                    body = (body + "\n" + extra).strip()[:2000]
                            if not body:
                                body = event.title if event else biz.profile.display_name
                            campaign = Campaign.objects.create(
                                sender=request.user,
                                subject=(biz.profile.display_name)[:180],
                                body=body,
                                channel="notice",
                                is_promo=True,
                                criteria=f"city={request.POST.get('city','')};r={radius};kinds={','.join(kinds)};purpose={purpose}"[:300],
                                status="draft",
                            )
                            CampaignDelivery.objects.bulk_create([
                                CampaignDelivery(campaign=campaign, user=profile.user) for profile in people
                            ])
                            send_campaign(campaign)
                            import json
                            logo = f"/entreprises/fichier/logo/{biz.id}/" if biz.logo else ""
                            params = json.dumps({"biz_name": biz.profile.display_name, "biz_logo": logo}, ensure_ascii=False)
                            prefix = biz.profile.display_name
                            for delivery in campaign.deliveries.select_related("notice"):
                                note = delivery.notice
                                if note is None:
                                    continue
                                if prefix and not note.body.startswith(prefix):
                                    note.body = f"{prefix}\n{note.body}"[:4000]
                                note.params = params
                                note.url = f"/entreprises/{biz.profile_id}/"
                                note.save(update_fields=["body", "params", "url"])
                            push = BusinessPush.objects.create(
                                business=biz, event=event if purpose == "event" or event else None,
                                city=(request.POST.get("city") or "")[:80],
                                lat=lat, lng=lng, radius_km=max(1, min(radius, 500)),
                                purpose=purpose,
                                promo_code=(request.POST.get("promo_code") or "")[:40] if purpose == "coupon" else "",
                                offer_details=(request.POST.get("offer_details") or "")[:400] if purpose == "coupon" else "",
                                offer_ends_at=ends if purpose == "coupon" else None,
                                target_kinds=",".join(kinds)[:40],
                                body=body, audience=preview, amount=amount, campaign=campaign, status="sent",
                            )
                            _invoice(biz, "push", amount, f"push {push.id}")
                            return redirect("business_home")
    return render(request, "business_push.html", {
        "biz": biz,
        "events": biz.events.filter(published=True),
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
            if is_seller(request.user):
                return HttpResponseForbidden("vendeur")
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
            if is_seller(request.user):
                return HttpResponseForbidden("vendeur")
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
                _invoice(biz, "plan", price_of("business_plan_price"), "abonnement")
        elif action == "doc":
            doc = get_object_or_404(BusinessDocument, pk=request.POST.get("document"))
            choice = request.POST.get("decision")
            if choice == "approve":
                doc.status = "approved"
                doc.business.verified = True
                fields = ["verified"]
                if is_seller(request.user) and doc.business.sold_by_id is None:
                    doc.business.sold_by = request.user
                    fields.append("sold_by")
                doc.business.save(update_fields=fields)
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
        "rows": BusinessAccount.objects.select_related("profile", "profile__user", "sold_by").prefetch_related("documents", "invoices"),
        "seller": is_seller(request.user),
    })


def _owner_only(request):
    if is_seller(request.user):
        return HttpResponseForbidden("vendeur")
    return None


@staff_only
def gestion_invoices(request):
    if request.method == "POST" and request.POST.get("action") == "pay-settings":
        blocked = _owner_only(request)
        if blocked:
            return blocked
        provider = request.POST.get("provider") if request.POST.get("provider") in ("stripe", "manual") else "manual"
        currency = (request.POST.get("currency") or "CAD").strip().upper()[:8] or "CAD"
        SiteSetting.objects.update_or_create(key="business_pay_provider", defaults={"value": provider})
        SiteSetting.objects.update_or_create(key="business_currency", defaults={"value": currency})
        secret = (request.POST.get("stripe_secret") or "").strip()
        if secret:
            SiteSetting.objects.update_or_create(key="business_stripe_secret", defaults={"value": secret[:200]})
        raw_rate = (request.POST.get("commission_rate") or "").strip()
        if raw_rate.isdigit():
            SiteSetting.objects.update_or_create(key="business_commission_rate", defaults={"value": str(max(0, min(100, int(raw_rate))))})
        return redirect("gestion_invoices")
    seller = request.user if is_seller(request.user) else None
    rows = BusinessInvoice.objects.select_related("business", "business__profile", "sold_by").order_by("-id")
    if seller is not None:
        rows = rows.filter(sold_by=seller)
    return render(request, "gestion/invoices.html", {
        "section": "invoices",
        "rows": rows,
        "seller": seller is not None,
        "provider": SiteSetting.get("business_pay_provider", "manual"),
        "currency": SiteSetting.get("business_currency", "CAD"),
        "rate": commission_rate(),
        "secret_set": bool(SiteSetting.get("business_stripe_secret", "")),
    })


@staff_only
@require_POST
def gestion_invoice_link(request, pk):
    invoice = get_object_or_404(BusinessInvoice, pk=pk, status="due")
    if is_seller(request.user) and invoice.sold_by_id not in (None, request.user.id):
        return HttpResponseForbidden("vendeur")
    create_business_payment_link(invoice)
    return redirect("gestion_invoices")


@staff_only
@require_POST
def gestion_invoice_mail(request, pk):
    invoice = get_object_or_404(BusinessInvoice.objects.select_related("business", "business__profile", "business__profile__user"), pk=pk)
    if not invoice.payment_url:
        return redirect("gestion_invoices")
    if is_seller(request.user) and invoice.sold_by_id not in (None, request.user.id):
        return HttpResponseForbidden("vendeur")
    email = invoice.business.profile.user.email
    queue_email(email, "Lien de paiement iSwing", invoice.payment_url, kind="billing", ref=f"invoice-{invoice.id}")
    return redirect("gestion_invoices")


@staff_only
@require_POST
def gestion_invoice_paid(request, pk):
    blocked = _owner_only(request)
    if blocked:
        return blocked
    invoice = get_object_or_404(BusinessInvoice, pk=pk, status="due")
    invoice.status = "paid"
    invoice.paid_at = timezone.now()
    invoice.save(update_fields=["status", "paid_at"])
    return redirect("gestion_invoices")


@staff_only
def gestion_crm(request):
    seller = is_seller(request.user)
    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()[:120]
        if name:
            status = request.POST.get("status") if request.POST.get("status") in dict(Prospect.STATUS) else "new"
            follow = None
            try:
                if request.POST.get("next_follow"):
                    follow = date.fromisoformat(request.POST.get("next_follow"))
            except ValueError:
                follow = None
            category = request.POST.get("category") if request.POST.get("category") in dict(CATEGORIES) else "other"
            owner = request.user if seller else None
            if not seller and (request.POST.get("seller") or "").isdigit():
                owner = User.objects.filter(pk=int(request.POST.get("seller")), groups__name="Vendeurs").first()
            Prospect.objects.create(
                name=name,
                contact=(request.POST.get("contact") or "")[:80],
                email=(request.POST.get("email") or "").strip().lower()[:254],
                phone=(request.POST.get("phone") or "")[:40],
                category=category,
                status=status,
                notes=(request.POST.get("notes") or "")[:4000],
                next_follow=follow,
                seller=owner or request.user,
            )
        return redirect("gestion_crm")
    rows = Prospect.objects.select_related("seller", "business")
    if seller:
        rows = rows.filter(seller=request.user)
    status = (request.GET.get("status") or "").strip()
    if status in dict(Prospect.STATUS):
        rows = rows.filter(status=status)
    query = (request.GET.get("q") or "").strip()
    if query:
        rows = rows.filter(Q(name__icontains=query) | Q(email__icontains=query) | Q(contact__icontains=query))
    return render(request, "gestion/crm.html", {
        "section": "crm",
        "rows": rows,
        "seller": seller,
        "statuses": Prospect.STATUS,
        "categories": CATEGORIES,
        "status": status,
        "q": query,
    })


@staff_only
@require_POST
def gestion_crm_convert(request, pk):
    row = get_object_or_404(Prospect, pk=pk)
    if is_seller(request.user) and row.seller_id != request.user.id:
        return HttpResponseForbidden("vendeur")
    if row.business_id:
        return redirect("gestion_crm")
    email = (row.email or "").strip().lower()
    if not email or User.objects.filter(email__iexact=email).exists():
        return redirect("gestion_crm")
    seller = row.seller or request.user
    user = User.objects.create_user(
        email=email, password=secrets.token_urlsafe(12), birth_date=None,
        terms_accepted_at=timezone.now(), adult_declared=True,
    )
    profile = Profile.objects.create(user=user, display_name=row.name[:40], kind="business", city="", bio="")
    biz = BusinessAccount.objects.create(
        profile=profile, category=row.category if row.category in dict(CATEGORIES) else "other",
        description=(row.notes or "")[:4000], sold_by=seller,
    )
    row.business = biz
    row.status = "client"
    row.save(update_fields=["business", "status"])
    return redirect("gestion_crm")


@staff_only
def gestion_commissions(request):
    seller = request.user if is_seller(request.user) else None
    if request.method == "POST":
        blocked = _owner_only(request)
        if blocked:
            return blocked
        period = (request.POST.get("period") or "")[:7]
        seller_id = request.POST.get("seller") or ""
        if period and seller_id.isdigit():
            target = User.objects.filter(pk=int(seller_id)).first()
            if target:
                payout, _created = SellerPayout.objects.get_or_create(seller=target, period=period)
                payout.paid_at = timezone.now()
                payout.save(update_fields=["paid_at"])
        return redirect("gestion_commissions")
    return render(request, "gestion/commissions.html", {
        "section": "commissions",
        "rows": commission_rows(seller),
        "seller": seller is not None,
        "rate": commission_rate(),
    })


@staff_only
def gestion_report(request):
    seller = request.user if is_seller(request.user) else None
    prospects = Prospect.objects.all()
    invoices = BusinessInvoice.objects.all()
    if seller is not None:
        prospects = prospects.filter(seller=seller)
        invoices = invoices.filter(sold_by=seller)
    by_status = {code: prospects.filter(status=code).count() for code, _label in Prospect.STATUS}
    total = sum(by_status.values())
    clients = by_status.get("client", 0)
    billed = sum(row.amount for row in invoices.exclude(status="void"))
    paid = sum(row.amount for row in invoices.filter(status="paid"))
    commissions = commission_rows(seller)
    due = sum(row["due"] for row in commissions if not row["paid_out"])
    sent = sum(row["due"] for row in commissions if row["paid_out"])
    payload = {
        "by_status": by_status,
        "prospects": total,
        "clients": clients,
        "conversion": (round(100 * clients / total) if total else 0),
        "billed": billed,
        "paid": paid,
        "commission_due": due,
        "commission_paid": sent,
    }
    if request.GET.get("export") == "csv":
        from django.http import HttpResponse

        lines = ["metric,value"]
        for key, value in payload.items():
            if key == "by_status":
                for status, count in value.items():
                    lines.append(f"prospects_{status},{count}")
            else:
                lines.append(f"{key},{value}")
        response = HttpResponse("\n".join(lines) + "\n", content_type="text/csv")
        response["Content-Disposition"] = "attachment; filename=rapport-entreprises.csv"
        return response
    return render(request, "gestion/report_sales.html", {"section": "report", "report": payload, "seller": seller is not None})


@staff_only
def gestion_sellers(request):
    blocked = _owner_only(request)
    if blocked:
        return blocked
    from django.contrib.auth.models import Group

    group, _created = Group.objects.get_or_create(name="Vendeurs")
    error = ""
    if request.method == "POST":
        email = (request.POST.get("email") or "").strip().lower()
        password = request.POST.get("password") or ""
        if not email or User.objects.filter(email__iexact=email).exists() or len(password) < 10:
            error = "form"
        else:
            user = User.objects.create_user(
                email=email, password=password, birth_date=None, is_staff=True,
                terms_accepted_at=timezone.now(), adult_declared=True,
            )
            user.groups.add(group)
            Profile.objects.create(
                user=user, display_name=email.split("@")[0][:40], city="", bio="", visibility="paused",
            )
            return redirect("gestion_sellers")
    return render(request, "gestion/sellers.html", {
        "section": "sellers",
        "rows": group.user_set.order_by("email"),
        "error": error,
    })
