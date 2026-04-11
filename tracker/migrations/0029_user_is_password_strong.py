from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0028_emergencyrequest'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='is_password_strong',
            field=models.BooleanField(default=False),
        ),
    ]
