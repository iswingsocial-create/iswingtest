from django.apps import AppConfig


class PlatformConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "swingapp"
    verbose_name = "iSwing"

    def ready(self):
        try:
            import pillow_heif

            pillow_heif.register_heif_opener()
        except Exception:
            pass
