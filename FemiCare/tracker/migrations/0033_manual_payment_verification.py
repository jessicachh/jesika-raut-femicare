# Generated manually for manual payment verification flow
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0032_alter_doctorprofile_license_number_unique'),
    ]

    operations = [
        migrations.AddField(
            model_name='doctorprofile',
            name='consultation_fee',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
        ),
        migrations.CreateModel(
            name='DoctorPaymentDetails',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('payment_method', models.CharField(choices=[('bank', 'Bank Transfer'), ('esewa', 'eSewa'), ('khalti', 'Khalti'), ('qr', 'QR Code')], max_length=20)),
                ('account_name', models.CharField(blank=True, max_length=255, null=True)),
                ('account_number', models.CharField(blank=True, max_length=255, null=True)),
                ('bank_name', models.CharField(blank=True, max_length=255, null=True)),
                ('esewa_id', models.CharField(blank=True, max_length=255, null=True)),
                ('khalti_id', models.CharField(blank=True, max_length=255, null=True)),
                ('qr_code_image', models.ImageField(blank=True, null=True, upload_to='payment_qr/')),
                ('is_completed', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('doctor', models.OneToOneField(limit_choices_to={'role': 'doctor'}, on_delete=django.db.models.deletion.CASCADE, related_name='payment_details', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='Payment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('total_amount', models.DecimalField(decimal_places=2, max_digits=10)),
                ('commission_amount', models.DecimalField(decimal_places=2, max_digits=10)),
                ('doctor_earning', models.DecimalField(decimal_places=2, max_digits=10)),
                ('payment_proof', models.ImageField(blank=True, null=True, upload_to='payment_proofs/')),
                ('status', models.CharField(choices=[('pending', 'Pending Verification'), ('approved', 'Approved'), ('rejected', 'Rejected')], default='pending', max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('appointment', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='payment', to='tracker.appointment')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='payments', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AlterField(
            model_name='appointment',
            name='status',
            field=models.CharField(choices=[('pending', 'Pending'), ('awaiting_payment', 'Awaiting Payment'), ('payment_verification', 'Payment Verification'), ('upcoming', 'Upcoming'), ('completed', 'Completed'), ('rejected', 'Rejected')], default='pending', max_length=20),
        ),
    ]
