from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0024_user_2fa_and_twofactorcode'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='has_accepted_terms',
            field=models.BooleanField(default=False),
        ),
    ]
