from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0026_cyclelog_actual_start_date_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='cyclelog',
            name='end_date',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='cyclelog',
            name='expected_end_date',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='cyclelog',
            name='start_date',
            field=models.DateField(blank=True, null=True),
        ),
    ]
