"""
Migration for eSewa Direct Payment Integration
- Simplified DoctorPaymentDetails to only have esewa_id and consultation_fee
- Updated Payment model with transaction_id and removed payment_proof
- Removed payment_verification status from Appointment
"""

from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0033_manual_payment_verification'),
    ]

    operations = [
        # Update Appointment statuses - remove payment_verification
        migrations.AlterField(
            model_name='appointment',
            name='status',
            field=models.CharField(
                choices=[
                    ('pending', 'Pending'),
                    ('awaiting_payment', 'Awaiting Payment'),
                    ('upcoming', 'Upcoming'),
                    ('completed', 'Completed'),
                    ('rejected', 'Rejected'),
                ],
                default='pending',
                max_length=20
            ),
        ),

        # Remove old fields from DoctorPaymentDetails
        migrations.RemoveField(
            model_name='doctorpaymentdetails',
            name='payment_method',
        ),
        migrations.RemoveField(
            model_name='doctorpaymentdetails',
            name='account_name',
        ),
        migrations.RemoveField(
            model_name='doctorpaymentdetails',
            name='account_number',
        ),
        migrations.RemoveField(
            model_name='doctorpaymentdetails',
            name='bank_name',
        ),
        migrations.RemoveField(
            model_name='doctorpaymentdetails',
            name='khalti_id',
        ),
        migrations.RemoveField(
            model_name='doctorpaymentdetails',
            name='qr_code_image',
        ),
        migrations.RemoveField(
            model_name='doctorpaymentdetails',
            name='is_completed',
        ),

        # Add new fields to DoctorPaymentDetails
        migrations.AlterField(
            model_name='doctorpaymentdetails',
            name='esewa_id',
            field=models.CharField(
                max_length=255,
                unique=True,
                help_text='eSewa merchant ID'
            ),
        ),
        migrations.AddField(
            model_name='doctorpaymentdetails',
            name='consultation_fee',
            field=models.DecimalField(
                decimal_places=2,
                default=500,
                max_digits=10,
                validators=[django.core.validators.MinValueValidator(0)],
                help_text='Consultation fee in NPR'
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='doctorpaymentdetails',
            name='is_payment_setup_complete',
            field=models.BooleanField(default=False),
        ),

        # Update Payment model
        migrations.RemoveField(
            model_name='payment',
            name='total_amount',
        ),
        migrations.RemoveField(
            model_name='payment',
            name='payment_proof',
        ),
        migrations.AlterField(
            model_name='payment',
            name='status',
            field=models.CharField(
                choices=[
                    ('pending', 'Pending'),
                    ('completed', 'Completed'),
                    ('failed', 'Failed'),
                    ('cancelled', 'Cancelled'),
                ],
                default='pending',
                max_length=20
            ),
        ),
        migrations.AddField(
            model_name='payment',
            name='amount',
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                max_digits=10
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='payment',
            name='transaction_id',
            field=models.CharField(
                default='temp_id',
                max_length=255,
                unique=True,
                help_text='eSewa transaction ID'
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='payment',
            name='completed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='payment',
            name='commission_amount',
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                max_digits=10
            ),
        ),
        migrations.AlterField(
            model_name='payment',
            name='doctor_earning',
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                max_digits=10
            ),
        ),
    ]
