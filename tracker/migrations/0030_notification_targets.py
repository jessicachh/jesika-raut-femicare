from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0029_user_is_password_strong'),
    ]

    operations = [
        migrations.AddField(
            model_name='notification',
            name='target_section_id',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
        migrations.AddField(
            model_name='notification',
            name='target_url',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
    ]
