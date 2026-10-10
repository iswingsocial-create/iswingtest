from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import (
    AuditLog,
    Match,
    Message,
    PaymentEvent,
    Photo,
    Profile,
    Report,
    Subscription,
    TestBatch,
    User,
)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("email",)
    list_display = ("email", "is_staff", "age_proof_status", "email_verified_at", "is_demo")
    search_fields = ("email",)
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Majorité", {"fields": ("birth_date", "adult_declared", "age_proof_status", "email_verified_at")}),
        ("Droits", {"fields": ("is_active", "is_staff", "is_superuser", "can_moderate", "can_manage_members", "can_manage_billing", "can_manage_comms", "can_configure", "groups", "user_permissions")}),
    )
    add_fieldsets = ((None, {"fields": ("email", "birth_date", "password1", "password2")}),)


admin.site.register(TestBatch)
admin.site.register(Profile)
admin.site.register(Photo)
admin.site.register(Match)
admin.site.register(Message)
admin.site.register(Report)
admin.site.register(Subscription)
admin.site.register(PaymentEvent)
admin.site.register(AuditLog)
admin.site.site_header = "iSwing"
admin.site.site_title = "iSwing"
admin.site.index_title = "Administration technique — la gestion courante est sur /gestion/"
