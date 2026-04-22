"""
eSewa Payment Gateway Integration
Handles direct payment processing with eSewa ePay v2.
"""
import json
import base64
import hashlib
import hmac
import requests
from decimal import Decimal
from urllib.parse import urlencode
from django.conf import settings
from django.utils import timezone
from tracker.models import Payment, Appointment
import logging

logger = logging.getLogger(__name__)


class ESewaClient:
    """eSewa Payment Gateway Client"""
    
    def __init__(self):
        self.merchant_code = settings.ESEWA_MERCHANT_CODE
        self.merchant_secret = settings.ESEWA_MERCHANT_SECRET
        self.api_url = settings.ESEWA_API_URL
        self.form_url = getattr(settings, 'ESEWA_FORM_URL', f'{self.api_url}/api/epay/main/v2/form')
        self.status_check_url = getattr(settings, 'ESEWA_STATUS_CHECK_URL', 'https://rc.esewa.com.np/api/epay/transaction/status/')
        self.success_url = settings.ESEWA_SUCCESS_URL
        self.failure_url = settings.ESEWA_FAILURE_URL

    def generate_signature(self, total_amount: Decimal, transaction_uuid: str) -> str:
        """
        Generate eSewa signature for transaction.
        eSewa v2 requires HMAC-SHA256 and Base64 output.
        """
        signed_field_names = 'total_amount,transaction_uuid,product_code'
        message = (
            f"total_amount={total_amount},"
            f"transaction_uuid={transaction_uuid},"
            f"product_code={self.merchant_code}"
        )
        digest = hmac.new(
            self.merchant_secret.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256,
        ).digest()
        return base64.b64encode(digest).decode('utf-8')

    def initiate_payment(
        self,
        appointment_id: int,
        esewa_id: str,
        amount: Decimal,
        success_url: str = None,
        failure_url: str = None,
    ) -> dict:
        """
        Initiate payment with eSewa
        Returns payment parameters for eSewa redirect
        """
        try:
            import uuid
            transaction_uuid = str(uuid.uuid4())
            
            # Generate signature
            signature = self.generate_signature(amount, transaction_uuid)

            callback_query = urlencode({'appointment_id': appointment_id})
            success_base_url = (success_url or self.success_url).strip()
            failure_base_url = (failure_url or self.failure_url).strip()
            success_redirect_url = (
                f"{success_base_url}&{callback_query}"
                if '?' in success_base_url
                else f"{success_base_url}?{callback_query}"
            )
            failure_redirect_url = (
                f"{failure_base_url}&{callback_query}"
                if '?' in failure_base_url
                else f"{failure_base_url}?{callback_query}"
            )
            
            # Prepare payment parameters
            payment_params = {
                'amount': str(amount),
                'failure_url': failure_redirect_url,
                'product_delivery_charge': '0',
                'product_service_charge': '0',
                'product_code': self.merchant_code,
                'signature': signature,
                'signed_field_names': 'total_amount,transaction_uuid,product_code',
                'success_url': success_redirect_url,
                'tax_amount': '0',
                'total_amount': str(amount),
                'transaction_uuid': transaction_uuid,
            }
            
            return {
                'success': True,
                'data': payment_params,
                'transaction_uuid': transaction_uuid,
                'api_url': self.form_url,
            }
        except Exception as e:
            logger.error(f"Error initiating payment: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }

    def verify_payment(self, transaction_uuid: str, total_amount: Decimal, status: str) -> dict:
        """
        Verify payment with eSewa
        Called when user returns from eSewa portal
        """
        try:
            if status != 'COMPLETE':
                return {
                    'success': False,
                    'error': 'Payment not completed'
                }
            
            # Call eSewa verification API
            verify_url = self.status_check_url
            
            response = requests.get(
                verify_url,
                params={
                    'product_code': self.merchant_code,
                    'total_amount': str(total_amount),
                    'transaction_uuid': transaction_uuid,
                },
                timeout=10,
            )
            response.raise_for_status()
            
            data = response.json()
            
            # Verify response
            if data.get('status') == 'COMPLETE':
                return {
                    'success': True,
                    'transaction_id': data.get('ref_id') or data.get('transaction_uuid'),
                    'amount': data.get('total_amount'),
                }
            else:
                return {
                    'success': False,
                    'error': 'Payment verification failed'
                }
                
        except requests.exceptions.RequestException as e:
            logger.error(f"eSewa verification request failed: {str(e)}")
            return {
                'success': False,
                'error': 'Payment verification failed'
            }
        except Exception as e:
            logger.error(f"Error verifying payment: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }

    def verify_callback_payload(self, encoded_data: str) -> dict:
        """Decode and validate eSewa callback payload from Base64 response data."""
        try:
            normalized = (encoded_data or '').strip().replace(' ', '+')
            # Fix missing Base64 padding sent via URL query in some flows.
            normalized += '=' * ((4 - len(normalized) % 4) % 4)
            decoded = base64.b64decode(normalized.encode('utf-8')).decode('utf-8')
            payload = json.loads(decoded)

            transaction_uuid = payload.get('transaction_uuid')
            total_amount = payload.get('total_amount')
            status = payload.get('status')
            response_signature = payload.get('signature')
            signed_field_names = payload.get('signed_field_names', '')

            if not transaction_uuid or total_amount is None:
                return {'success': False, 'error': 'Invalid callback payload'}

            # Rebuild the signature string using the fields eSewa says were signed.
            signed_parts = []
            for field_name in signed_field_names.split(','):
                field_name = field_name.strip()
                if not field_name:
                    continue
                if field_name not in payload:
                    continue
                signed_parts.append(f"{field_name}={payload[field_name]}")

            message = ','.join(signed_parts)
            digest = hmac.new(
                self.merchant_secret.encode('utf-8'),
                message.encode('utf-8'),
                hashlib.sha256,
            ).digest()
            expected_signature = base64.b64encode(digest).decode('utf-8')

            if response_signature and response_signature != expected_signature:
                return {'success': False, 'error': 'Invalid callback signature'}

            return {
                'success': True,
                'transaction_uuid': transaction_uuid,
                'total_amount': Decimal(str(total_amount)),
                'status': status,
                'ref_id': payload.get('ref_id'),
                'raw': payload,
            }
        except Exception as e:
            logger.error(f"Error decoding eSewa callback payload: {str(e)}")
            return {'success': False, 'error': str(e)}

    def calculate_commission(self, amount: Decimal) -> dict:
        """
        Calculate commission breakdown
        Platform: 25%, Doctor: 75%
        """
        commission = amount * Decimal(settings.PLATFORM_COMMISSION_PERCENTAGE) / Decimal(100)
        doctor_earning = amount - commission
        
        return {
            'total': amount,
            'commission': commission,
            'doctor_earning': doctor_earning,
        }


def process_payment_success(appointment_id: int, transaction_uuid: str, amount: Decimal) -> dict:
    """
    Process successful payment and auto-book appointment
    """
    try:
        appointment = Appointment.objects.get(id=appointment_id)

        existing_payment = Payment.objects.filter(
            appointment=appointment,
            transaction_id=transaction_uuid,
            status='completed',
        ).first()
        if existing_payment:
            if appointment.status != 'upcoming':
                appointment.status = 'upcoming'
                appointment.responded_at = timezone.now()
                appointment.save(update_fields=['status', 'responded_at'])
            return {
                'success': True,
                'payment_id': existing_payment.id,
                'appointment_id': appointment.id,
            }

        payment = Payment.objects.filter(appointment=appointment).first()
        
        # Calculate commission
        esewa = ESewaClient()
        commission_data = esewa.calculate_commission(amount)

        # Create or update the payment record
        if payment:
            payment.amount = amount
            payment.transaction_id = transaction_uuid
            payment.status = 'completed'
            payment.commission_amount = commission_data['commission']
            payment.doctor_earning = commission_data['doctor_earning']
            payment.payout_status = 'pending'
            payment.payout_batch = None
            payment.payout_paid_at = None
            payment.completed_at = timezone.now()
            payment.save()
        else:
            payment = Payment.objects.create(
                user=appointment.user,
                appointment=appointment,
                amount=amount,
                transaction_id=transaction_uuid,
                status='completed',
                commission_amount=commission_data['commission'],
                doctor_earning=commission_data['doctor_earning'],
                payout_status='pending',
                completed_at=timezone.now(),
            )
        
        # Auto-book appointment
        appointment.status = 'upcoming'
        appointment.responded_at = timezone.now()
        appointment.payment_due_at = None
        appointment.payment_expired_at = None
        appointment.save(update_fields=['status', 'responded_at', 'payment_due_at', 'payment_expired_at'])
        
        # Send confirmation emails (you'll need to implement this)
        # send_payment_confirmation(appointment, payment)
        
        return {
            'success': True,
            'payment_id': payment.id,
            'appointment_id': appointment.id,
        }
        
    except Appointment.DoesNotExist:
        logger.error(f"Appointment {appointment_id} not found")
        return {
            'success': False,
            'error': 'Appointment not found'
        }
    except Exception as e:
        logger.error(f"Error processing payment success: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }


def process_payment_failure(appointment_id: int, reason: str = None) -> dict:
    """
    Process failed payment
    """
    try:
        appointment = Appointment.objects.get(id=appointment_id)
        
        # Create failed payment record
        Payment.objects.create(
            user=appointment.user,
            appointment=appointment,
            amount=Decimal('0'),
            transaction_id=f"FAILED_{appointment_id}_{timezone.now().timestamp()}",
            status='failed',
        )
        
        # Keep appointment in awaiting_payment status
        # User can retry payment
        
        return {
            'success': True,
            'appointment_id': appointment.id,
        }
        
    except Exception as e:
        logger.error(f"Error processing payment failure: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }
