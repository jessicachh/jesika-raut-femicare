from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0020_healthlog_notification'),
    ]

    operations = [
        migrations.CreateModel(
            name='MoodEntry',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('mood', models.CharField(choices=[('happy', 'Happy'), ('sad', 'Sad'), ('stressed', 'Stressed'), ('calm', 'Calm'), ('irritated', 'Irritated'), ('energetic', 'Energetic')], max_length=20)),
                ('date', models.DateField(default=django.utils.timezone.now)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='mood_entries', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-date', '-created_at'],
                'unique_together': {('user', 'date')},
            },
        ),
        migrations.CreateModel(
            name='PredictionFeedback',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('predicted_date', models.DateField()),
                ('actual_date', models.DateField(blank=True, null=True)),
                ('is_correct', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('cycle_log', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='feedback', to='tracker.cyclelog')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='prediction_feedbacks', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
