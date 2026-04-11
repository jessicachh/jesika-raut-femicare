from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0025_userprofile_has_accepted_terms'),
    ]

    operations = [
        migrations.AddField(
            model_name='cyclelog',
            name='actual_start_date',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='cyclelog',
            name='is_confirmed',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='cyclelog',
            name='predicted_start_date',
            field=models.DateField(blank=True, null=True),
        ),
    ]
