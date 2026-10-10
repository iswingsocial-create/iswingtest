from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("swingapp", "0008_like_client_key"),
    ]

    operations = [
        migrations.AddField(
            model_name="partner",
            name="user",
            field=models.OneToOneField(blank=True, null=True, on_delete=models.SET_NULL, related_name="partner_seat", to="swingapp.user"),
        ),
        migrations.AddField(
            model_name="message",
            name="author_label",
            field=models.CharField(blank=True, default="", max_length=90),
        ),
    ]
