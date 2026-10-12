from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("swingapp", "0009_partner_access_message_label"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="certified",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="photo",
            name="role",
            field=models.CharField(default="gallery", max_length=16),
        ),
        migrations.AddField(
            model_name="notice",
            name="code",
            field=models.CharField(blank=True, default="", max_length=40),
        ),
        migrations.AddField(
            model_name="notice",
            name="params",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.CreateModel(
            name="CertificationRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(default="pending", max_length=16)),
                ("note", models.CharField(blank=True, default="", max_length=240)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                ("photo", models.ForeignKey(blank=True, null=True, on_delete=models.SET_NULL, to="swingapp.photo")),
                ("profile", models.ForeignKey(on_delete=models.CASCADE, related_name="certifications", to="swingapp.profile")),
            ],
            options={"ordering": ["-id"]},
        ),
    ]
