from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0022_symptomlog'),
    ]

    operations = [
        migrations.AddField(
            model_name='symptomlog',
            name='cycle_log',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='symptom_logs', to='tracker.cyclelog'),
        ),
        migrations.AddField(
            model_name='symptomlog',
            name='source',
            field=models.CharField(choices=[('manual', 'Manual Add Symptom'), ('first_login', 'First Login Period Form')], default='manual', max_length=20),
        ),
        migrations.CreateModel(
            name='PeriodCheckIn',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('pain_level', models.CharField(choices=[('low', 'Low'), ('medium', 'Medium'), ('high', 'High')], max_length=20)),
                ('blood_flow', models.CharField(choices=[('light', 'Light'), ('normal', 'Normal'), ('heavy', 'Heavy')], max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('cycle_log', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='period_checkins', to='tracker.cyclelog')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='period_checkins', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
                'unique_together': {('user', 'cycle_log')},
            },
        ),
    ]
