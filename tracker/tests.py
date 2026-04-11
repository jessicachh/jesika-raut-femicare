import json
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .forms import DoctorProfileForm
from .models import (
    Appointment,
    ChatMessage,
    Conversation,
    CycleLog,
    DoctorAvailability,
    DoctorProfile,
    Notification,
    SymptomLog,
    User,
    UserProfile,
)
from .views import trigger_emergency_alert


class TrackerTestCase(TestCase):
    def setUp(self):
        self.client = Client()

        self.patient_password = 'StrongPassw0rd!123'
        self.doctor_password = 'DoctorPassw0rd!123'

        self.patient = User.objects.create_user(
            username='patient-user',
            email='patient@example.com',
            password=self.patient_password,
            role='user',
            has_accepted_terms=True,
        )
        self.patient_profile = UserProfile.objects.create(
            user=self.patient,
            date_of_birth='1995-05-12',
            height_cm=165,
            weight_kg=62,
            address='Main Street',
            has_accepted_terms=True,
        )

        self.doctor = User.objects.create_user(
            username='doctor-user',
            email='doctor@example.com',
            password=self.doctor_password,
            role='doctor',
            has_accepted_terms=True,
        )
        self.doctor_profile = DoctorProfile.objects.create(
            user=self.doctor,
            full_name='Dr Test',
            license_number='abc-123',
            specialization='Gynecologist',
            experience_years=8,
            hospital_name='FemiCare Hospital',
            location='City Center',
            photo=SimpleUploadedFile('doctor.jpg', b'doctor-photo', content_type='image/jpeg'),
            bio='Experienced doctor',
            qualifications='MBBS, MD',
            languages_spoken='English',
            is_verified=True,
        )

        self.outsider = User.objects.create_user(
            username='outsider-user',
            email='outsider@example.com',
            password='OutsiderPassw0rd!123',
            role='user',
            has_accepted_terms=True,
        )

        self.chat_now = timezone.now().replace(hour=12, minute=0, second=0, microsecond=0)
        self.chat_room_name = self._chat_room_name(self.patient, self.doctor)

        self.active_chat_slot = self._create_availability(
            self.doctor,
            self.chat_now.date(),
            (self.chat_now - timedelta(minutes=30)).time().replace(microsecond=0),
            (self.chat_now + timedelta(minutes=30)).time().replace(microsecond=0),
        )
        self.active_chat_appointment = Appointment.objects.create(
            user=self.patient,
            doctor=self.doctor,
            availability=self.active_chat_slot,
            status='approved',
            patient_message='Consultation request',
        )
        self.conversation = Conversation.objects.create(
            doctor=self.doctor,
            patient=self.patient,
            room_name=self.chat_room_name,
        )

    def _login_as(self, user):
        self.client.force_login(user)

    def _chat_room_name(self, patient, doctor):
        return f'chat_{patient.id}_{doctor.id}'

    def _create_availability(self, doctor, date_value, start_time, end_time, is_active=True):
        return DoctorAvailability.objects.create(
            doctor=doctor,
            date=date_value,
            start_time=start_time,
            end_time=end_time,
            is_active=is_active,
        )


class AuthenticationTests(TrackerTestCase):
    @patch('tracker.views._issue_signup_email_code')
    @patch('tracker.views._send_signup_email_code')
    def test_successful_registration(self, mock_send_code, mock_issue_code):
        mock_issue_code.return_value = MagicMock(code='123456')

        payload = {
            'username': 'new-patient',
            'email': 'new-patient@example.com',
            'password': 'Str0ng!123',
            'confirm_password': 'Str0ng!123',
            'role': 'user',
            'has_accepted_terms': 'true',
        }

        response = self.client.post(reverse('signup'), payload)

        self.assertEqual(response.status_code, 302)

        # ✅ Correct validation (based on your system logic)
        created_user = User.objects.filter(username='new-patient').first()
        self.assertIsNotNone(created_user)
        self.assertEqual(created_user.email, 'new-patient@example.com')
        self.assertFalse(created_user.is_active)  # Email verification pending

        # ✅ Check session
        self.assertEqual(self.client.session.get('pending_signup_user_id'), created_user.id)

        # ✅ Check email function triggered
        mock_send_code.assert_called_once()


    def test_registration_rejects_invalid_input(self):
        response = self.client.post(
            reverse('signup'),
            {
                'username': 'broken-patient',
                'email': 'broken@example.com',
                'password': 'Str0ng!123',
                'confirm_password': 'Diff3rent!1',
                'role': 'user',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(User.objects.filter(username='broken-patient').count(), 0)

    def test_login_with_valid_credentials(self):
        response = self.client.post(
            reverse('login'),
            {
                'username': self.patient.username,
                'password': self.patient_password,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session.get('_auth_user_id'), str(self.patient.id))

    def test_login_failure_with_incorrect_credentials(self):
        response = self.client.post(
            reverse('login'),
            {
                'username': self.patient.username,
                'password': 'WrongPassword!123',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertIsNone(self.client.session.get('_auth_user_id'))


class AppointmentBookingTests(TrackerTestCase):
    @patch('tracker.views.send_appointment_template_email')
    @patch('tracker.views.send_notification_template_email')
    def test_successful_appointment_booking(self, mock_send_notification_email, mock_send_appointment_email):
        slot = self._create_availability(
            self.doctor,
            self.chat_now.date() + timedelta(days=1),
            (self.chat_now + timedelta(days=1, hours=1)).time().replace(microsecond=0),
            (self.chat_now + timedelta(days=1, hours=2)).time().replace(microsecond=0),
        )

        self._login_as(self.patient)
        response = self.client.post(
            reverse('book_appointment', args=[slot.id]),
            {'reason': 'I need a consultation'},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Appointment.objects.filter(user=self.patient, availability=slot, status='pending').exists())
        self.assertFalse(DoctorAvailability.objects.get(id=slot.id).is_active)
        self.assertTrue(Notification.objects.filter(user=self.doctor, type='appointment').exists())
        self.assertTrue(Notification.objects.filter(user=self.patient, type='appointment').exists())
        mock_send_appointment_email.assert_called_once()
        mock_send_notification_email.assert_called_once()

    @patch('tracker.views.send_appointment_template_email')
    @patch('tracker.views.send_notification_template_email')
    def test_prevents_duplicate_booking_on_same_day(self, mock_send_notification_email, mock_send_appointment_email):
        first_slot = self._create_availability(
            self.doctor,
            self.chat_now.date() + timedelta(days=2),
            (self.chat_now + timedelta(days=2, hours=1)).time().replace(microsecond=0),
            (self.chat_now + timedelta(days=2, hours=2)).time().replace(microsecond=0),
        )
        duplicate_slot = self._create_availability(
            self.doctor,
            self.chat_now.date() + timedelta(days=2),
            (self.chat_now + timedelta(days=2, hours=3)).time().replace(microsecond=0),
            (self.chat_now + timedelta(days=2, hours=4)).time().replace(microsecond=0),
        )

        self._login_as(self.patient)
        first_response = self.client.post(
            reverse('book_appointment', args=[first_slot.id]),
            {'reason': 'First booking'},
        )
        second_response = self.client.post(
            reverse('book_appointment', args=[duplicate_slot.id]),
            {'reason': 'Second booking same day'},
        )

        self.assertEqual(first_response.status_code, 302)
        self.assertEqual(second_response.status_code, 302)
        self.assertEqual(
            Appointment.objects.filter(user=self.patient, availability__date=duplicate_slot.date).count(),
            1,
        )
        self.assertTrue(Notification.objects.filter(user=self.patient, type='appointment').exists())
        self.assertTrue(Notification.objects.filter(user=self.doctor, type='appointment').exists())
        mock_send_appointment_email.assert_called_once()
        mock_send_notification_email.assert_called_once()


class ChatAccessTests(TrackerTestCase):
    def test_chat_access_allowed_for_assigned_participants(self):
        self._login_as(self.patient)

        response = self.client.get(reverse('get_message_history', args=[self.active_chat_appointment.id]))
        payload = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload['consultation']['can_chat'])
        self.assertEqual(payload['consultation']['status'], 'approved')

    def test_chat_access_blocked_for_non_participant(self):
        outsider_client = Client()
        outsider_client.force_login(self.outsider)

        response = outsider_client.get(reverse('get_message_history', args=[self.active_chat_appointment.id]))

        self.assertEqual(response.status_code, 403)

    @patch('tracker.views.timezone.now')
    def test_chat_blocked_when_appointment_is_not_approved(self, mock_now):
        mock_now.return_value = self.chat_now
        pending_slot = self._create_availability(
            self.doctor,
            self.chat_now.date(),
            (self.chat_now - timedelta(minutes=30)).time().replace(microsecond=0),
            (self.chat_now + timedelta(minutes=30)).time().replace(microsecond=0),
        )
        pending_appointment = Appointment.objects.create(
            user=self.patient,
            doctor=self.doctor,
            availability=pending_slot,
            status='pending',
            patient_message='Awaiting approval',
        )

        self._login_as(self.patient)
        response = self.client.post(
            reverse('send_message'),
            data=json.dumps({
                'appointment_id': pending_appointment.id,
                'room_name': self.chat_room_name,
                'content': 'Hello doctor',
            }),
            content_type='application/json',
        )

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(payload['success'])
        self.assertEqual(payload['error'], 'Consultation chat is locked right now')
        self.assertEqual(ChatMessage.objects.count(), 0)

    @patch('tracker.views.timezone.now')
    def test_chat_blocked_outside_time_window(self, mock_now):
        mock_now.return_value = self.chat_now
        future_start = self.chat_now + timedelta(days=1)
        future_end = future_start + timedelta(hours=1)
        future_slot = self._create_availability(
            self.doctor,
            future_start.date(),
            future_start.time().replace(microsecond=0),
            future_end.time().replace(microsecond=0),
        )
        future_appointment = Appointment.objects.create(
            user=self.patient,
            doctor=self.doctor,
            availability=future_slot,
            status='approved',
            patient_message='Future appointment',
        )

        self._login_as(self.patient)
        response = self.client.post(
            reverse('send_message'),
            data=json.dumps({
                'appointment_id': future_appointment.id,
                'room_name': self.chat_room_name,
                'content': 'This should not send',
            }),
            content_type='application/json',
        )

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(payload['success'])
        self.assertEqual(payload['error'], 'Consultation chat is locked right now')
        self.assertEqual(ChatMessage.objects.count(), 0)

    @patch('channels.layers.get_channel_layer')
    @patch('asgiref.sync.async_to_sync', side_effect=lambda func: func)
    @patch('tracker.views.timezone.now')
    def test_sending_message_stores_message_and_notification(self, mock_now, mock_async_to_sync, mock_get_channel_layer):
        mock_now.return_value = self.chat_now
        mock_channel_layer = MagicMock()
        mock_channel_layer.group_send = MagicMock(return_value=None)
        mock_get_channel_layer.return_value = mock_channel_layer

        self._login_as(self.patient)
        response = self.client.post(
            reverse('send_message'),
            data=json.dumps({
                'appointment_id': self.active_chat_appointment.id,
                'room_name': self.chat_room_name,
                'content': 'Hello doctor, I am here.',
            }),
            content_type='application/json',
        )

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload['success'])
        self.assertEqual(ChatMessage.objects.count(), 1)
        message = ChatMessage.objects.get(room_name=self.chat_room_name)
        self.assertEqual(message.message, 'Hello doctor, I am here.')
        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.unread_count_doctor, 1)
        self.assertTrue(Notification.objects.filter(user=self.doctor, type='message_received').exists())


class DoctorProfileValidationTests(TrackerTestCase):
    def test_prevent_saving_profile_when_required_fields_are_empty(self):
        original_bio = self.doctor_profile.bio
        original_qualifications = self.doctor_profile.qualifications
        original_languages = self.doctor_profile.languages_spoken

        self._login_as(self.doctor)
        response = self.client.post(
            reverse('doctor_profile'),
            {
                'bio': '',
                'qualifications': '',
                'languages_spoken': '',
            },
        )

        self.doctor_profile.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.doctor_profile.bio, original_bio)
        self.assertEqual(self.doctor_profile.qualifications, original_qualifications)
        self.assertEqual(self.doctor_profile.languages_spoken, original_languages)

    def test_doctor_profile_form_reports_required_field_errors(self):
        form = DoctorProfileForm(
            data={
                'full_name': '',
                'specialization': '',
                'license_number': '',
                'experience_years': '',
                'hospital_name': '',
                'location': '',
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn('full_name', form.errors)
        self.assertIn('specialization', form.errors)
        self.assertIn('license_number', form.errors)
        self.assertIn('experience_years', form.errors)
        self.assertIn('location', form.errors)
        self.assertIn('certificate', form.errors)


class NotificationAndCycleLogTests(TrackerTestCase):
    @patch('tracker.views.update_cycle_prediction')
    def test_cycle_log_submission_saves_data_and_creates_notification(self, mock_update_cycle_prediction):
        self._login_as(self.patient)
        response = self.client.post(
            reverse('add_cycle_log'),
            {
                'last_period_start': self.chat_now.date().isoformat(),
                'length_of_cycle': '28',
                'length_of_menses': '5',
                'mean_bleeding_intensity': '2',
                'total_menses_score': '3',
                'unusual_bleeding': 'False',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(CycleLog.objects.filter(user=self.patient).count(), 1)

        cycle_log = CycleLog.objects.get(user=self.patient)
        self.assertEqual(cycle_log.last_period_start, self.chat_now.date())
        self.assertEqual(cycle_log.length_of_cycle, 28)
        self.assertEqual(cycle_log.length_of_menses, 5)
        self.assertEqual(cycle_log.mean_menses_length, 5)
        self.assertTrue(Notification.objects.filter(user=self.patient, title='Cycle prediction updated').exists())
        mock_update_cycle_prediction.assert_called_once_with(self.patient)

    @patch('tracker.views.send_email_alert')
    def test_medium_repeated_symptom_triggers_notification(self, mock_send_email_alert):
        symptom = 'Fatigue'
        today = timezone.localdate()

        for offset in range(3):
            SymptomLog.objects.create(
                user=self.patient,
                symptom=symptom,
                source='manual',
                date=today - timedelta(days=offset),
            )

        assessment = trigger_emergency_alert(self.patient)

        self.assertEqual(assessment['level'], 'medium')
        self.assertTrue(assessment['triggered'])
        self.assertTrue(Notification.objects.filter(user=self.patient, title='Health Warning').exists())
        mock_send_email_alert.assert_called_once_with(self.patient, symptom)
