from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("swingapp", "0010_badges_certification_notices"),
    ]

    operations = [
        migrations.AddField(
            model_name="partner",
            name="orientation",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
        migrations.AddField(
            model_name="photo",
            name="title",
            field=models.CharField(blank=True, default="", max_length=80),
        ),
    ]
