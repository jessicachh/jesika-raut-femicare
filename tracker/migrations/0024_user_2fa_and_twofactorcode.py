from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0023_periodcheckin_and_symptomlog_updates'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='is_two_factor_enabled',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='user',
            name='two_factor_enabled_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='user',
            name='role',
            field=models.CharField(choices=[('user', 'User'), ('doctor', 'Doctor')], default='user', max_length=10),
        ),
        migrations.CreateModel(
            name='TwoFactorCode',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(max_length=6)),
                ('purpose', models.CharField(choices=[('login', 'Login Verification'), ('setup', '2FA Setup Verification'), ('settings_enable', 'Enable 2FA'), ('settings_disable', 'Disable 2FA')], max_length=30)),
                ('expires_at', models.DateTimeField()),
                ('used_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='two_factor_codes', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
