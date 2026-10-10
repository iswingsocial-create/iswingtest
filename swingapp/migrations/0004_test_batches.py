from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("swingapp", "0003_media_access_reports"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="lifetime_member",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="profile",
            name="origins",
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name="profile",
            name="city_ref",
            field=models.CharField(blank=True, max_length=180),
        ),
        migrations.AddField(
            model_name="profile",
            name="external_key",
            field=models.CharField(blank=True, max_length=80, null=True, unique=True),
        ),
        migrations.CreateModel(
            name="TestBatch",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("batch_id", models.SlugField(max_length=40, unique=True)),
                ("name", models.CharField(max_length=80)),
                ("seed", models.CharField(max_length=64)),
                ("reference_date", models.DateField()),
                ("status", models.CharField(default="queued", max_length=24)),
                ("params", models.JSONField(blank=True, default=dict)),
                ("report", models.JSONField(blank=True, default=dict)),
                ("zip_path", models.CharField(blank=True, max_length=300)),
                ("error", models.CharField(blank=True, max_length=300)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
            ],
        ),
        migrations.CreateModel(
            name="TestPersona",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("external_key", models.CharField(max_length=80, unique=True)),
                ("visual", models.JSONField(blank=True, default=dict)),
                ("sheet", models.JSONField(blank=True, default=dict)),
                ("simulated", models.JSONField(blank=True, default=dict)),
                ("batch", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="personas", to="swingapp.testbatch")),
                ("profile", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="test_persona", to="swingapp.profile")),
            ],
        ),
    ]
