from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("swingapp", "0002_legal_and_consents"),
    ]

    operations = [
        migrations.AddField(
            model_name="photo",
            name="media_type",
            field=models.CharField(default="photo", max_length=8),
        ),
        migrations.AddField(
            model_name="photo",
            name="video",
            field=models.FileField(blank=True, upload_to="videos/%Y/%m/"),
        ),
        migrations.AddField(
            model_name="report",
            name="reason_code",
            field=models.CharField(blank=True, default="", max_length=40),
        ),
        migrations.AddField(
            model_name="report",
            name="comment",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.CreateModel(
            name="PrivateAccess",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(default="pending", max_length=16)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                ("grantee", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="private_access", to="swingapp.profile")),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="private_grants", to="swingapp.profile")),
            ],
        ),
        migrations.AddConstraint(
            model_name="privateaccess",
            constraint=models.UniqueConstraint(fields=("owner", "grantee"), name="uniq_private_access"),
        ),
        migrations.CreateModel(
            name="Notice",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(max_length=40)),
                ("body", models.CharField(blank=True, max_length=80)),
                ("url", models.CharField(blank=True, max_length=200)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("read_at", models.DateTimeField(blank=True, null=True)),
                ("profile", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="notices", to="swingapp.profile")),
            ],
            options={"ordering": ["-id"]},
        ),
    ]
