from datetime import date

from django import forms
from django.utils import timezone

from .choices import (
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
from .i18n import t
from .models import Profile


def _label(pairs, lang):
    return [(value, t(lang, key)) for value, key in pairs]


class RegisterForm(forms.Form):
    email = forms.EmailField()
    password = forms.CharField(min_length=10, widget=forms.PasswordInput)
    birth_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    display_name = forms.CharField(max_length=40)
    kind = forms.ChoiceField(choices=Profile.KIND)
    accept = forms.BooleanField()

    def clean_birth_date(self):
        value = self.cleaned_data["birth_date"]
        today = timezone.now().date()
        years = today.year - value.year - ((today.month, today.day) < (value.month, value.day))
        if years < 18:
            raise forms.ValidationError("18+")
        if value > today or value < date(1920, 1, 1):
            raise forms.ValidationError("date")
        return value


def _split(value):
    return [part.strip() for part in (value or "").split(",") if part.strip()]


class ProfileForm(forms.ModelForm):
    gender = forms.ChoiceField(choices=GENDERS, required=False)
    orientation = forms.ChoiceField(choices=ORIENTATIONS, required=False)
    city = forms.CharField(max_length=80, required=False)
    city_lat = forms.FloatField(required=False, widget=forms.HiddenInput)
    city_lng = forms.FloatField(required=False, widget=forms.HiddenInput)
    language_list = forms.MultipleChoiceField(choices=LANGUAGES, widget=forms.CheckboxSelectMultiple, required=False)
    language_other = forms.CharField(max_length=40, required=False)
    seeking_list = forms.MultipleChoiceField(choices=SEEKING, widget=forms.CheckboxSelectMultiple, required=False)
    taste_list = forms.MultipleChoiceField(choices=TASTES, widget=forms.CheckboxSelectMultiple, required=False)
    activity_list = forms.MultipleChoiceField(choices=ACTIVITIES, widget=forms.CheckboxSelectMultiple, required=False)
    desire_list = forms.MultipleChoiceField(choices=[(c, c) for c in CATEGORY_CODES], widget=forms.CheckboxSelectMultiple, required=False)
    availability_list = forms.MultipleChoiceField(choices=AVAILABILITY, widget=forms.CheckboxSelectMultiple, required=False)
    limit_list = forms.MultipleChoiceField(choices=[(c, c) for c in LIMIT_CODES], widget=forms.CheckboxSelectMultiple, required=False)
    show_prefs = forms.BooleanField(required=False)

    class Meta:
        model = Profile
        fields = [
            "kind", "display_name", "gender", "orientation", "city", "bio", "language_other",
            "hide_orientation", "hide_desires", "show_distance", "show_online", "visibility", "read_receipts",
        ]

    def __init__(self, *args, lang="fr", **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["kind"].choices = [("single", t(lang, "single")), ("couple", t(lang, "couple"))]
        self.fields["gender"].choices = [("", "—")] + _label(GENDERS, lang)
        self.fields["orientation"].choices = _label(ORIENTATIONS, lang)
        self.fields["visibility"].choices = [
            ("public", t(lang, "vis_public")),
            ("discrete", t(lang, "vis_discrete")),
            ("paused", t(lang, "vis_paused")),
        ]
        self.fields["language_list"].choices = _label(LANGUAGES, lang)
        self.fields["seeking_list"].choices = _label(SEEKING, lang)
        self.fields["taste_list"].choices = _label(TASTES, lang)
        self.fields["activity_list"].choices = _label(ACTIVITIES, lang)
        self.fields["availability_list"].choices = _label(AVAILABILITY, lang)
        self.fields["desire_list"].choices = [
            (code, t(lang, "cat_" + code) + " — " + t(lang, "cat_" + code + "_d")) for code in CATEGORY_CODES
        ]
        self.fields["limit_list"].choices = [(code, t(lang, "lim_" + code)) for code in LIMIT_CODES]
        labels = {
            "kind": "kind", "display_name": "display_name", "gender": "gender", "orientation": "orientation",
            "city": "city", "bio": "bio", "hide_orientation": "hide_orientation", "hide_desires": "hide_desires",
            "show_distance": "show_distance", "show_online": "show_online", "visibility": "visibility",
            "read_receipts": "read_receipts", "language_list": "languages_title", "language_other": "other_language",
            "seeking_list": "seeking_title", "taste_list": "tastes_title", "activity_list": "activities_title",
            "desire_list": "desires_title", "availability_list": "availability_title", "limit_list": "limits_title",
            "show_prefs": "prefs_consent",
        }
        for name, key in labels.items():
            self.fields[name].label = t(lang, key)
        self.fields["bio"].widget.attrs["rows"] = 4
        self.fields["city"].widget.attrs["autocomplete"] = "off"
        self.fields["city"].widget.attrs["data-city"] = "1"
        profile = self.instance
        if profile.pk:
            self.fields["language_list"].initial = _split(profile.languages)
            self.fields["seeking_list"].initial = _split(profile.seeking)
            self.fields["taste_list"].initial = _split(profile.tastes)
            self.fields["activity_list"].initial = _split(profile.activities)
            self.fields["desire_list"].initial = _split(profile.desires)
            self.fields["availability_list"].initial = _split(profile.availability)
            self.fields["limit_list"].initial = _split(profile.limits)
            self.fields["city_lat"].initial = profile.lat
            self.fields["city_lng"].initial = profile.lng
            self.fields["show_prefs"].initial = bool(profile.user.prefs_consent)

    def save(self, commit=True):
        profile = super().save(commit=False)
        data = self.cleaned_data
        langs = list(data.get("language_list") or [])
        profile.languages = ", ".join(langs)[:300]
        if "autre" not in langs:
            profile.language_other = ""
        profile.seeking = ", ".join(data.get("seeking_list") or [])
        profile.tastes = ", ".join(data.get("taste_list") or [])
        profile.activities = ", ".join(data.get("activity_list") or [])[:200]
        profile.desires = ", ".join(data.get("desire_list") or [])
        profile.availability = ", ".join(data.get("availability_list") or [])[:120]
        profile.limits = ", ".join(data.get("limit_list") or [])
        if data.get("city_lat") is not None and data.get("city_lng") is not None:
            profile.lat = data["city_lat"]
            profile.lng = data["city_lng"]
        profile.user.prefs_consent = bool(data.get("show_prefs"))
        profile.user.save(update_fields=["prefs_consent"])
        if commit:
            profile.save()
        return profile


class PartnerForm(forms.Form):
    display_name = forms.CharField(max_length=40, required=False)
    birth_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}), required=False)
    gender = forms.ChoiceField(choices=[("", "—")] + GENDERS, required=False)
    consent = forms.BooleanField(required=False)
    consent_email = forms.EmailField(required=False)

    def __init__(self, *args, lang="fr", **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["display_name"].label = t(lang, "partner_name")
        self.fields["birth_date"].label = t(lang, "partner_birth")
        self.fields["gender"].label = t(lang, "partner_gender")
        self.fields["gender"].choices = [("", "—")] + _label(GENDERS, lang)
        self.fields["consent"].label = t(lang, "partner_consent")
        self.fields["consent_email"].label = t(lang, "partner_email")

    def clean(self):
        data = super().clean()
        if data.get("display_name") or data.get("consent"):
            if not data.get("birth_date"):
                self.add_error("birth_date", "Date requise")
            elif data.get("birth_date"):
                today = timezone.now().date()
                years = today.year - data["birth_date"].year - ((today.month, today.day) < (data["birth_date"].month, data["birth_date"].day))
                if years < 18:
                    self.add_error("birth_date", "18+")
        return data
