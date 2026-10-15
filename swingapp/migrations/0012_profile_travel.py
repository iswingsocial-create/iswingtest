from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("swingapp", "0011_partner_orientation_photo_title"),
    ]

    operations = [
        migrations.AddField(model_name="profile", name="travel_city", field=models.CharField(blank=True, default="", max_length=80)),
        migrations.AddField(model_name="profile", name="travel_country", field=models.CharField(blank=True, default="", max_length=2)),
        migrations.AddField(model_name="profile", name="travel_lat", field=models.FloatField(blank=True, null=True)),
        migrations.AddField(model_name="profile", name="travel_lng", field=models.FloatField(blank=True, null=True)),
        migrations.AddField(model_name="profile", name="travel_start", field=models.DateField(blank=True, null=True)),
        migrations.AddField(model_name="profile", name="travel_end", field=models.DateField(blank=True, null=True)),
    ]
