from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("swingapp", "0007_media_integrations"),
    ]

    operations = [
        migrations.AddField(
            model_name="like",
            name="client_key",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddConstraint(
            model_name="like",
            constraint=models.UniqueConstraint(condition=models.Q(("client_key", ""), _negated=True), fields=("actor", "client_key"), name="uniq_like_client_key"),
        ),
    ]
