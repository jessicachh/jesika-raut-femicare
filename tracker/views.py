from collections import Counter
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout, logout
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.views import PasswordResetConfirmView
from django.contrib import messages
import random
import time
from django.http import JsonResponse, HttpResponse, FileResponse
from .models import User
from django.contrib.auth.decorators import login_required
from .models import (
    UserProfile,
    DoctorProfile,
    DoctorPaymentDetails,
    DoctorAvailability,
    Appointment,
    Payment,
    DoctorReview,
    UserDocument,
    HealthLog,
    Notification,
    MoodEntry,
    PredictionFeedback,
    SymptomLog,
    PeriodCheckIn,
    TwoFactorCode,
    EmergencyRequest,
)
from .forms import (
    CycleLogForm,
    PeriodLogForm,
    EndPeriodForm,
    UserProfileForm,
    MIN_HEIGHT_CM,
    MAX_HEIGHT_CM,
    MIN_WEIGHT_KG,
    MAX_WEIGHT_KG,
    is_height_valid,
    is_weight_valid,
    AccountSettingsForm,
    EmailVerificationForm,
    UserDocumentUploadForm,
    RegistrationForm,
    StrongPasswordChangeForm,
    StrongSetPasswordForm,
    DoctorEmailChangeRequestForm,
    DeleteAccountForm,
    DoctorProfileForm,
    SignupEmailVerificationForm,
)
from .models import CycleLog
from tracker.ml.predict import predict_cycle
from datetime import timedelta, datetime
from django.utils import timezone
from django.core.paginator import Paginator
from django.conf import settings
from django.db.models import Avg, Count, Q
from django.db import IntegrityError, transaction
from django.utils.dateparse import parse_date
from django.urls import reverse
import logging
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from tracker.emails.utils import (
    send_appointment_email as send_appointment_template_email,
    send_emergency_email as send_emergency_template_email,
    send_doctor_verification_submission_email,
    send_notification_email as send_notification_template_email,
    send_profile_settings_change_email,
    send_verification_email,
)


SYMPTOM_OPTIONS = [
    'Abdominal Cramps',
    'Appetite Changes',
    'Bladder Incontinence',
    'Bloating',
    'Breast Pain',
    'Chills',
    'Constipation',
    'Diarrhea',
    'Dry Skin',
    'Fatigue',
    'Hair Loss',
    'Headache',
    'Hot Flashes',
    'Lower Back Pain',
    'Memory Lapse',
    'Mood Changes',
    'Nausea',
    'Night Sweats',
    'Pelvic Pain',
    'Sleep Changes',
    'Vaginal Dryness',
    'Acne',
]

HIGH_RISK_SYMPTOMS = {
    'Pelvic Pain',
    'Abdominal Cramps',
    'Bladder Incontinence',
    'Night Sweats',
    'Hair Loss',
    'Memory Lapse',
    'Hot Flashes',
    'Vaginal Dryness',
}

MEDIUM_RISK_SYMPTOMS = {
    'Fatigue',
    'Nausea',
    'Headache',
    'Diarrhea',
    'Constipation',
    'Sleep Changes',
    'Mood Changes',
}

RISK_SYMPTOMS = HIGH_RISK_SYMPTOMS | MEDIUM_RISK_SYMPTOMS
logger = logging.getLogger(__name__)

EMERGENCY_ALERT_TITLE = 'Health Alert'
EMERGENCY_ALERT_MESSAGE = (
    'You may be experiencing symptoms that require attention. '
    'Please monitor your health and consult a doctor if needed. Do not panic.'
)
DELAYED_PERIOD_MESSAGE = 'Your period seems delayed. Please monitor your health and consult a doctor if needed.'


def _set_login_session_expiry(request, remember_me):
    if remember_me:
        request.session.set_expiry(getattr(settings, 'REMEMBER_ME_AGE', 60 * 60 * 24 * 14))
    else:
        request.session.set_expiry(0)


def _issue_two_factor_code(user, purpose):
    code_value = f"{random.SystemRandom().randint(0, 999999):06d}"
    expires_at = timezone.now() + timedelta(seconds=getattr(settings, 'TWO_FACTOR_CODE_TTL', 600))
    return TwoFactorCode.objects.create(
        user=user,
        code=code_value,
        purpose=purpose,
        expires_at=expires_at,
    )


def _send_two_factor_code_email(user, code_obj):
    send_verification_email(
        user,
        'two_factor',
        {
            'code': code_obj.code,
            'expires_minutes': 10,
            'subject': 'FemiCare Verification Code',
            'action_url': reverse('dashboard_home'),
            'action_label': 'Open Dashboard',
        },
    )


def _validate_two_factor_code(user, purpose, submitted_code):
    now = timezone.now()
    code_obj = (
        TwoFactorCode.objects
        .filter(
            user=user,
            purpose=purpose,
            used_at__isnull=True,
            expires_at__gt=now,
        )
        .order_by('-created_at')
        .first()
    )

    if not code_obj or code_obj.code != (submitted_code or '').strip():
        return False

    code_obj.used_at = now
    code_obj.save(update_fields=['used_at'])
    return True


def _issue_signup_email_code(user):
    return _issue_two_factor_code(user, 'signup_email')


def _send_signup_email_code(user, code_obj):
    send_verification_email(
        user,
        'email_verification',
        {
            'code': code_obj.code,
            'expires_minutes': 10,
            'subject': 'FemiCare Signup Verification Code',
            'action_url': reverse('verify_signup_email'),
            'action_label': 'Verify Email',
        },
    )


def _validate_signup_email_code(user, submitted_code):
    return _validate_two_factor_code(user, 'signup_email', submitted_code)


def _to_positive_int(value, fallback=None):
    try:
        parsed = int(round(float(value)))
        return parsed if parsed > 0 else fallback
    except (TypeError, ValueError):
        return fallback


def _period_end_exclusive(start_date, length_days):
    safe_length = max(_to_positive_int(length_days, 1), 1)
    return start_date + timedelta(days=safe_length)


def _serialize_period_range(start_date, length_days, kind, title):
    if not start_date:
        return None
    return {
        'title': title,
        'start': start_date.isoformat(),
        'end': _period_end_exclusive(start_date, length_days).isoformat(),
        'kind': kind,
    }


def _build_logged_period_ranges(cycle_logs, fallback_menses_length):
    ranges = []
    for log in cycle_logs:
        if not log.last_period_start:
            continue

        menses_length = log.length_of_menses or fallback_menses_length
        serialized = _serialize_period_range(
            log.last_period_start,
            menses_length,
            'actual',
            'Past cycle',
        )
        if serialized:
            ranges.append(serialized)
    return ranges


def _generate_rolling_prediction_starts(last_period_start, cycle_length_days, reference_date, count=3):
    cycle_length = _to_positive_int(cycle_length_days)
    if not last_period_start or not cycle_length:
        return []

    starts = []
    next_start = last_period_start + timedelta(days=cycle_length)

    for _ in range(count):
        starts.append(next_start)
        next_start = next_start + timedelta(days=cycle_length)

    while starts and starts[-1] <= reference_date and len(starts) < 24:
        for _ in range(count):
            starts.append(next_start)
            next_start = next_start + timedelta(days=cycle_length)

    upcoming = [item for item in starts if item >= reference_date]
    return upcoming[:count] if upcoming else starts[:count]


def _redirect_user_after_login(request, user):
    if user.is_staff or user.is_superuser:
        return redirect('admin:index')

    if user.role == 'doctor':
        try:
            profile = user.doctor_profile
        except DoctorProfile.DoesNotExist:
            return redirect('doctor_details')

        terms_accepted = bool(getattr(user, 'has_accepted_terms', False))
        if not terms_accepted:
            return redirect('terms_and_conditions')

        if not profile.is_verified:
            return render(request, 'doctor_pending.html', {'profile': profile})
        return redirect('doctor_dashboard')

    profile, _ = UserProfile.objects.get_or_create(user=user)

    profile_incomplete = (
        not profile.date_of_birth or
        profile.height_cm in (None, 0) or
        profile.weight_kg in (None, 0)
    )
    if profile_incomplete:
        return redirect('user_profile')

    terms_accepted = bool(profile.has_accepted_terms or getattr(user, 'has_accepted_terms', False))
    if not terms_accepted:
        return redirect('terms_and_conditions')

    _ensure_password_security_notice(user)

    return redirect('dashboard_home')


def _ensure_user_access(request):
    if request.user.is_staff or request.user.is_superuser:
        return redirect('admin:index')
    if request.user.role != 'user':
        return redirect('doctor_dashboard' if request.user.role == 'doctor' else 'home')
    return None


def _ensure_chat_access(request):
    if request.user.is_staff or request.user.is_superuser:
        messages.error(request, 'Admin accounts can only access the admin area.')
        return redirect('admin:index')
    if request.user.role not in {'user', 'doctor'}:
        messages.error(request, 'Your account role cannot access chat.')
        return redirect('home')
    return None


def _is_google_oauth_ready():
    has_env_config = bool(getattr(settings, 'GOOGLE_CLIENT_ID', '')) and bool(getattr(settings, 'GOOGLE_CLIENT_SECRET', ''))
    if has_env_config:
        return True

    try:
        from allauth.socialaccount.models import SocialApp
    except Exception:
        return False

    return SocialApp.objects.filter(provider='google').exists()
# -----------------------------
# Public pages
# -----------------------------
def main(request):
    return render(request, 'main.html')

def home(request):
    return render(request, 'home.html')

def service(request):
    return render(request, 'how-it-works.html')

def contact(request):
    return render(request, 'contact.html')


def resources(request):
    return render(request, 'resources.html')


@login_required
def terms_and_conditions(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)

    if request.method == "POST":
        user = request.user
        user.has_accepted_terms = True
        user.save(update_fields=['has_accepted_terms'])
        profile.has_accepted_terms = True
        profile.save(update_fields=['has_accepted_terms'])

        return _redirect_user_after_login(request, user)
            
    return render(request, 'terms_and_conditions.html')

def explore_doctors(request):
    doctors = DoctorProfile.objects.filter(
        is_verified=True,
        is_profile_complete=True,
        consultation_fee__isnull=False,
        user__payment_details__is_completed=True,
    ).exclude(consultation_fee__lte=0)

    specialization = request.GET.get('specialization')
    if specialization:
        doctors = doctors.filter(specialization__icontains=specialization)

    paginator = Paginator(doctors, 6)
    page = request.GET.get('page')
    doctors = paginator.get_page(page)

    return render(request, 'doctor.html', {
        'doctors': doctors
    })
# -----------------------------
# Authentication
# -----------------------------
from django.http import JsonResponse
def signup_view(request):
    if request.method == 'POST':
        form = RegistrationForm(request.POST)
        if not form.is_valid():
            for errors in form.errors.values():
                for error in errors:
                    messages.error(request, error)
            return redirect('signup')

        username = form.cleaned_data['username']
        email = form.cleaned_data['email']
        password = form.cleaned_data['password']
        role = form.cleaned_data['role'] or 'user'

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            role=role,
            is_password_strong=True,
            is_active=False,
        )

        try:
            signup_code = _issue_signup_email_code(user)
            _send_signup_email_code(user, signup_code)
        except Exception:
            user.delete()
            messages.error(request, 'Unable to send verification code. Please try signing up again.')
            return redirect('signup')

        request.session['pending_signup_user_id'] = user.id

        # API Testing
        if request.headers.get('Accept') == 'application/json':
            return JsonResponse({
                "message": "Account created. Verify your email before login.",
                "username": username,
                "role": role
            }, status=201)

        messages.info(request, f'A 6-digit verification code was sent to {email}.')
        return redirect('verify_signup_email')
    

    google_oauth_ready = _is_google_oauth_ready()
    return render(request, 'signup.html', {'google_oauth_ready': google_oauth_ready})



def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        remember_me = request.POST.get('remember_me') == 'on'

        user = authenticate(request, username=username, password=password)

        if user is None:
            pending_user = User.objects.filter(username=username).first()
            if pending_user and pending_user.check_password(password) and not pending_user.is_active:
                request.session['pending_signup_user_id'] = pending_user.id
                messages.error(request, 'Please verify your email before logging in.')
                return redirect('verify_signup_email')
            messages.error(request, "Invalid username or password")
            return redirect('login')

        if user.is_two_factor_enabled:
            if not user.email:
                messages.error(request, '2FA is enabled but your account has no email address.')
                return redirect('login')

            code_obj = _issue_two_factor_code(user, 'login')
            try:
                _send_two_factor_code_email(user, code_obj)
            except Exception:
                messages.error(request, 'Unable to send verification code. Please try again.')
                return redirect('login')

            request.session['pending_login_user_id'] = user.id
            request.session['pending_login_remember_me'] = remember_me
            request.session['pending_login_backend'] = getattr(
                user,
                'backend',
                settings.AUTHENTICATION_BACKENDS[0],
            )
            messages.info(request, 'A verification code was sent to your email.')
            return redirect('two_factor_login_verify')

        auth_login(request, user)
        _set_login_session_expiry(request, remember_me)
        # API Testing: Success Response
        if request.headers.get('Accept') == 'application/json':
            return JsonResponse({
                "message": "Login successful!",
                "username": user.username
            }, status=200)
        return _redirect_user_after_login(request, user)

    google_oauth_ready = _is_google_oauth_ready()
    return render(request, 'login.html', {'google_oauth_ready': google_oauth_ready})


def verify_signup_email(request):
    pending_user_id = request.session.get('pending_signup_user_id')
    pending_user = User.objects.filter(id=pending_user_id).first() if pending_user_id else None

    if request.user.is_authenticated and not request.user.is_active:
        pending_user = request.user
        request.session['pending_signup_user_id'] = request.user.id

    if not pending_user:
        messages.error(request, 'Your signup verification session expired. Please sign up again or login to continue.')
        return redirect('signup')

    if pending_user.is_active:
        request.session.pop('pending_signup_user_id', None)
        if request.user.is_authenticated and request.user.id == pending_user.id:
            return redirect('post_auth_redirect')
        messages.info(request, 'Your email is already verified. You can log in now.')
        return redirect('login')

    form = SignupEmailVerificationForm(request.POST or None)

    if request.method == 'POST' and form.is_valid():
        code = form.cleaned_data['code']

        if not _validate_signup_email_code(pending_user, code):
            messages.error(request, 'Invalid or expired verification code.')
            return redirect('verify_signup_email')

        pending_user.is_active = True
        pending_user.save(update_fields=['is_active'])

        request.session.pop('pending_signup_user_id', None)
        request.session['prompt_2fa_after_signup'] = True
        request.session['post_signup_next'] = 'post_auth_redirect'

        auth_login(request, pending_user, backend=settings.AUTHENTICATION_BACKENDS[0])
        messages.success(request, 'Email verified successfully.')
        return redirect('two_factor_setup_prompt')

    masked_email = pending_user.email
    if masked_email and '@' in masked_email:
        local_part, domain_part = masked_email.split('@', 1)
        masked_local = (local_part[:2] + '***') if len(local_part) > 2 else (local_part[:1] + '***')
        masked_email = f'{masked_local}@{domain_part}'

    return render(
        request,
        'two_factor_verify.html',
        {
            'title': 'Verify Your Email',
            'subtitle': f'Enter the 6-digit code sent to {masked_email}.',
            'verify_url_name': 'verify_signup_email',
            'resend_url_name': 'resend_signup_email_code',
        },
    )


def resend_signup_email_code(request):
    if request.method != 'POST':
        return redirect('verify_signup_email')

    pending_user_id = request.session.get('pending_signup_user_id')
    if not pending_user_id:
        messages.error(request, 'Your signup verification session expired. Please sign up again.')
        return redirect('signup')

    pending_user = User.objects.filter(id=pending_user_id).first()
    if not pending_user or pending_user.is_active:
        request.session.pop('pending_signup_user_id', None)
        messages.info(request, 'This account is already verified. You can log in now.')
        return redirect('login')

    code_obj = _issue_signup_email_code(pending_user)
    try:
        _send_signup_email_code(pending_user, code_obj)
        messages.info(request, 'A new verification code was sent to your email.')
    except Exception:
        messages.error(request, 'Unable to resend verification code right now. Please try again.')

    return redirect('verify_signup_email')


@login_required
def post_auth_redirect(request):
    if request.session.pop('prompt_2fa_after_signup', False):
        return redirect('two_factor_setup_prompt')
    return _redirect_user_after_login(request, request.user)


@login_required
def two_factor_setup_prompt(request):
    next_route = request.session.get('post_signup_next') or ('doctor_details' if request.user.role == 'doctor' else 'user_profile')

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'later':
            messages.info(request, 'You can enable 2FA later from Settings.')
            request.session.pop('prompt_2fa_after_signup', None)
            return redirect(next_route)

        if action == 'enable':
            if not request.user.email:
                messages.error(request, 'Please add a valid email address before enabling 2FA.')
                return redirect(next_route)

            code_obj = _issue_two_factor_code(request.user, 'setup')
            try:
                _send_two_factor_code_email(request.user, code_obj)
            except Exception:
                messages.error(request, 'Unable to send verification code. Please try again.')
                return redirect('two_factor_setup_prompt')

            messages.info(request, 'Verification code sent to your email.')
            return redirect('two_factor_setup_verify')

    return render(request, 'two_factor_setup_prompt.html', {'next_route': next_route})


@login_required
def two_factor_setup_verify(request):
    next_route = request.session.get('post_signup_next') or ('doctor_details' if request.user.role == 'doctor' else 'user_profile')

    if request.method == 'POST':
        code = request.POST.get('code')
        if _validate_two_factor_code(request.user, 'setup', code):
            request.user.is_two_factor_enabled = True
            request.user.two_factor_enabled_at = timezone.now()
            request.user.save(update_fields=['is_two_factor_enabled', 'two_factor_enabled_at'])
            request.session.pop('prompt_2fa_after_signup', None)
            messages.success(request, 'Two-factor authentication enabled successfully.')
            return redirect(next_route)

        messages.error(request, 'Invalid or expired verification code.')

    return render(
        request,
        'two_factor_verify.html',
        {
            'title': 'Enable Two-Factor Authentication',
            'subtitle': 'Enter the 6-digit code sent to your email to complete setup.',
            'verify_url_name': 'two_factor_setup_verify',
            'resend_url_name': 'two_factor_setup_resend',
        },
    )


@login_required
def two_factor_setup_resend(request):
    if request.method != 'POST':
        return redirect('two_factor_setup_verify')

    code_obj = _issue_two_factor_code(request.user, 'setup')
    try:
        _send_two_factor_code_email(request.user, code_obj)
        messages.info(request, 'A new verification code was sent.')
    except Exception:
        messages.error(request, 'Unable to resend verification code. Please try again.')
    return redirect('two_factor_setup_verify')


def two_factor_login_verify(request):
    pending_user_id = request.session.get('pending_login_user_id')
    if not pending_user_id:
        messages.error(request, 'Your login session expired. Please login again.')
        return redirect('login')

    user = User.objects.filter(id=pending_user_id).first()
    if not user:
        request.session.pop('pending_login_user_id', None)
        request.session.pop('pending_login_remember_me', None)
        request.session.pop('pending_login_backend', None)
        messages.error(request, 'Invalid login session. Please login again.')
        return redirect('login')

    if request.method == 'POST':
        code = request.POST.get('code')
        if _validate_two_factor_code(user, 'login', code):
            remember_me = bool(request.session.pop('pending_login_remember_me', False))
            backend = request.session.pop('pending_login_backend', settings.AUTHENTICATION_BACKENDS[0])
            request.session.pop('pending_login_user_id', None)
            auth_login(request, user, backend=backend)
            _set_login_session_expiry(request, remember_me)
            return _redirect_user_after_login(request, user)

        messages.error(request, 'Invalid or expired verification code.')

    return render(
        request,
        'two_factor_verify.html',
        {
            'title': 'Login Verification',
            'subtitle': f'Enter the 6-digit code sent to {user.email}.',
            'verify_url_name': 'two_factor_login_verify',
            'resend_url_name': 'two_factor_login_resend',
        },
    )


def two_factor_login_resend(request):
    pending_user_id = request.session.get('pending_login_user_id')
    if not pending_user_id:
        messages.error(request, 'Your login session expired. Please login again.')
        return redirect('login')

    user = User.objects.filter(id=pending_user_id).first()
    if not user:
        messages.error(request, 'Unable to resend code. Please login again.')
        return redirect('login')

    code_obj = _issue_two_factor_code(user, 'login')
    try:
        _send_two_factor_code_email(user, code_obj)
        messages.info(request, 'A new verification code was sent to your email.')
    except Exception:
        messages.error(request, 'Unable to resend code right now.')
    return redirect('two_factor_login_verify')


class StrongPasswordResetConfirmView(PasswordResetConfirmView):
    form_class = StrongSetPasswordForm
    template_name = 'registration/password_reset_confirm.html'

    def form_valid(self, form):
        response = super().form_valid(form)

        reset_user = getattr(self, 'user', None)
        if reset_user:
            reset_user.is_password_strong = True
            reset_user.save(update_fields=['is_password_strong'])

            Notification.objects.filter(
                user=reset_user,
                title='Security Update Required',
                is_read=False,
            ).update(is_read=True)

            _create_notification(
                reset_user,
                'Password updated',
                'Your password has been updated through password reset.',
                'system',
            )

        return response


@login_required
def enable_two_factor(request):
    if request.method != 'POST':
        return redirect('dashboard_settings')

    if not request.user.email:
        messages.error(request, 'Please set an email before enabling 2FA.')
        return redirect('dashboard_settings')

    code_obj = _issue_two_factor_code(request.user, 'settings_enable')
    try:
        _send_two_factor_code_email(request.user, code_obj)
    except Exception:
        messages.error(request, 'Unable to send verification code.')
        return redirect('dashboard_settings')

    request.session['pending_2fa_action'] = 'enable'
    messages.info(request, 'Verification code sent to your email.')
    return redirect('two_factor_settings_verify')


@login_required
def disable_two_factor(request):
    if request.method != 'POST':
        return redirect('dashboard_settings')

    code_obj = _issue_two_factor_code(request.user, 'settings_disable')
    try:
        _send_two_factor_code_email(request.user, code_obj)
    except Exception:
        messages.error(request, 'Unable to send verification code.')
        return redirect('dashboard_settings')

    request.session['pending_2fa_action'] = 'disable'
    messages.info(request, 'Verification code sent to your email.')
    return redirect('two_factor_settings_verify')


@login_required
def two_factor_settings_verify(request):
    action = request.session.get('pending_2fa_action')
    if action not in {'enable', 'disable'}:
        messages.error(request, 'No pending 2FA action found.')
        return redirect('dashboard_settings')

    purpose = 'settings_enable' if action == 'enable' else 'settings_disable'

    if request.method == 'POST':
        code = request.POST.get('code')
        if _validate_two_factor_code(request.user, purpose, code):
            request.user.is_two_factor_enabled = action == 'enable'
            request.user.two_factor_enabled_at = timezone.now() if action == 'enable' else None
            request.user.save(update_fields=['is_two_factor_enabled', 'two_factor_enabled_at'])
            request.session.pop('pending_2fa_action', None)
            messages.success(request, 'Two-factor authentication settings updated.')
            return redirect('dashboard_settings')

        messages.error(request, 'Invalid or expired verification code.')

    return render(
        request,
        'two_factor_verify.html',
        {
            'title': 'Verify 2FA Change',
            'subtitle': 'Enter the 6-digit code sent to your email.',
            'verify_url_name': 'two_factor_settings_verify',
            'resend_url_name': 'enable_two_factor' if action == 'enable' else 'disable_two_factor',
        },
    )


@login_required
def user_profile(request):
    role_redirect = _ensure_user_access(request)
    if role_redirect:
        return role_redirect

    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    today = timezone.localdate()

    # If profile already filled, redirect to dashboard
    profile_complete = (
        profile.date_of_birth and
        profile.date_of_birth <= today and
        is_height_valid(profile.height_cm) and
        is_weight_valid(profile.weight_kg)
    )
    if profile_complete and request.method != 'POST':
        return _redirect_user_after_login(request, request.user)

    if request.method == 'POST':
        dob_raw = request.POST.get('dob')
        dob_value = parse_date(dob_raw) if dob_raw else None
        if dob_value is None:
            messages.error(request, 'Please provide a valid date of birth.')
            return render(request, 'user_profile.html', {'profile': profile})

        if dob_value > today:
            messages.error(request, 'Date of birth cannot be in the future.')
            return render(request, 'user_profile.html', {'profile': profile})

        height_raw = request.POST.get('height_cm')
        weight_raw = request.POST.get('weight_kg')

        try:
            height_val = float(height_raw)
            weight_val = float(weight_raw)
            if (
                height_val < MIN_HEIGHT_CM or
                height_val > MAX_HEIGHT_CM or
                weight_val < MIN_WEIGHT_KG or
                weight_val > MAX_WEIGHT_KG
            ):
                raise ValueError
        except (TypeError, ValueError):
            messages.error(request, 'Please enter a valid height and weight.')
            return render(request, 'user_profile.html', {'profile': profile})

        profile.date_of_birth = dob_value
        profile.height_cm = height_val
        profile.weight_kg = weight_val
        profile.save()

        return _redirect_user_after_login(request, request.user)

    return render(request, 'user_profile.html', {'profile': profile})

@login_required
def doctor_details(request):
    if request.user.role != 'doctor':
        return redirect('home')

    profile, created = DoctorProfile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        form = DoctorProfileForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            try:
                with transaction.atomic():
                    profile = form.save(commit=False)
                    profile.user = request.user
                    profile.save()
            except IntegrityError:
                form.add_error('license_number', 'A doctor with this license number already exists.')
                return render(request, 'doctor_details.html', {'profile': profile, 'form': form})

            # Notify the admin inbox as soon as a doctor submits the verification packet.
            if not send_doctor_verification_submission_email(profile, submitted_at=timezone.localtime(timezone.now())):
                logger.warning(
                    'Doctor verification submission email could not be sent for user_id=%s',
                    request.user.id,
                )

            # IMPORTANT: Redirect to pending page
            return render(request, 'doctor_pending.html', {'profile': profile})

        return render(request, 'doctor_details.html', {'profile': profile, 'form': form})

    return render(request, 'doctor_details.html', {'profile': profile, 'form': DoctorProfileForm(instance=profile)})

@login_required
def public_doctor_profile(request, pk):
    doctor = get_object_or_404(
        DoctorProfile,
        pk=pk,
        is_verified=True,
        is_profile_complete=True,
    )
    
    # Use localtime to match your actual time zone
    now = timezone.localtime(timezone.now())
    today = now.date()
    current_time = now.time()
    two_weeks = today + timedelta(days=14)
    
    availabilities = DoctorAvailability.objects.filter(
        doctor=doctor.user,
        date__range=[today, two_weeks],
        is_active=True,
    ).exclude(
        appointment__status__in=['pending', 'awaiting_payment', 'payment_verification', 'upcoming']
    ).order_by('date', 'start_time')

    valid_slots = []
    for slot in availabilities:
        # If the slot is today, only show it if the start_time is in the future
        if slot.date == today:
            if slot.start_time > current_time:
                valid_slots.append(slot)
        else:
            # If the slot is any day after today, it's always valid
            valid_slots.append(slot)

    return render(request, "doctor_profile.html", {
        "doctor": doctor,
        "availabilities": valid_slots, 
        "reviews": doctor.reviews.all().select_related("patient"),
    })

@login_required
def book_appointment(request, slot_id):
    slot = get_object_or_404(DoctorAvailability, id=slot_id, is_active=True)

    if request.method == 'POST':
        # --- NEW: CHECK FOR EXISTING APPOINTMENT TODAY ---
        already_booked = Appointment.objects.filter(
            user=request.user,
            availability__date=slot.date,
            status__in=['pending', 'awaiting_payment', 'payment_verification', 'upcoming']
        ).exists()

        if already_booked:
            messages.error(request, "You already have an appointment scheduled for this day.")
            return redirect("public_doctor_profile", pk=slot.doctor.doctor_profile.id)
        # ------------------------------------------------

        reason = request.POST.get('reason', '').strip()
        
        appointment = Appointment.objects.create(
            user=request.user,
            doctor=slot.doctor,
            availability=slot,
            status="pending",
            patient_message=reason
        )

        slot.is_active = False
        slot.save()

        _create_notification(
            slot.doctor,
            'New appointment request',
            f'{request.user.username} requested an appointment on {slot.date}.',
            'appointment',
            target_url=reverse('doctor_appointment'),
            target_section_id='appointments-section',
        )
        _create_notification(
            request.user,
            'Appointment requested',
            'Your appointment request has been submitted.',
            'appointment',
            target_url=reverse('appointment'),
            target_section_id='appointments-section',
        )

        send_appointment_template_email(
            request.user,
            'request_confirmation',
            {
                'doctor_name': f"Dr. {slot.doctor.doctor_profile.full_name}" if hasattr(slot.doctor, 'doctor_profile') else slot.doctor.username,
                'appointment_date': slot.date.strftime('%Y-%m-%d'),
                'appointment_time': f"{slot.start_time.strftime('%H:%M')} - {slot.end_time.strftime('%H:%M')}",
                'reason': reason,
                'action_url': reverse('appointment'),
                'action_label': 'View Appointment',
            },
        )

        send_notification_template_email(
            slot.doctor,
            f"You have a new appointment request from {request.user.username} for {slot.date:%Y-%m-%d}.",
            {
                'notification_title': 'New Appointment Request',
                'subject': 'New Appointment Request - FemiCare',
                'action_url': reverse('doctor_appointment'),
                'action_label': 'Review Requests',
            },
        )

        # Email logic remains same...
        messages.success(request, "Request sent!")
        return redirect("appointment")
    
    return redirect("public_doctor_profile", pk=slot.doctor.doctorprofile.id)


@login_required
def submit_emergency_request(request):
    if request.method != 'POST':
        return redirect('dashboard_home')

    if request.user.role != 'user':
        messages.error(request, 'Only users can submit emergency requests.')
        return redirect('dashboard_home')

    reason = request.POST.get('reason', '').strip()
    emergency_request = create_emergency_request(request.user, reason=reason)
    if not emergency_request:
        messages.error(request, 'Unable to create emergency request right now.')
        return redirect('dashboard_home')

    if emergency_request.status != 'pending':
        messages.info(request, 'You already have an active emergency request.')
        return redirect('dashboard_home')

    notified = notify_available_doctors(emergency_request)
    if notified:
        messages.success(request, 'Emergency request submitted. Available doctors have been notified.')
    else:
        messages.warning(request, 'Emergency request submitted. No doctors are currently available; we will keep trying.')

    return redirect('dashboard_home')


@login_required
def accept_emergency_request(request, emergency_request_id):
    if request.method != 'POST':
        return redirect('doctor_appointment')

    if request.user.role != 'doctor':
        return redirect('home')

    emergency_request = get_object_or_404(EmergencyRequest, id=emergency_request_id)
    assigned = assign_doctor_to_request(emergency_request, request.user)
    if not assigned:
        messages.error(request, 'This emergency request is already assigned or no matching slot is available.')
        return redirect('doctor_appointment')

    messages.success(request, f'Emergency request #{assigned.id} accepted and appointment scheduled.')
    return redirect('doctor_appointment')

@login_required
def doctor_appointment(request):
    if request.user.role != 'doctor':
        return redirect('home')

    today = timezone.now().date()
    # Using localtime to match the user's expected wall-clock time
    now = timezone.localtime(timezone.now())

    appointments = Appointment.objects.filter(
        doctor=request.user
    ).select_related('user', 'availability').order_by('availability__date', 'availability__start_time')

    pending_appointments = []
    upcoming_appointments = []
    ongoing_appointments = []
    completed_appointments = []
    rejected_appointments = []

    pending_payment_verifications = list(
        Payment.objects.filter(
            appointment__doctor=request.user,
            status='pending'
        ).select_related('user', 'appointment__availability')
    )

    now = timezone.localtime(timezone.now())
    emergency_pending_requests = list(
        EmergencyRequest.objects.filter(status='pending')
        .exclude(user=request.user)
        .order_by('-created_at')
    )

    doctor_has_future_slots = DoctorAvailability.objects.filter(
        doctor=request.user,
        is_active=True,
    ).filter(
        Q(date__gt=now.date()) | Q(date=now.date(), start_time__gte=now.time())
    ).filter(appointment__isnull=True).exists()

    for appt in appointments:
        # Combine date and time into a full datetime object for comparison
        appt_time_start = timezone.make_aware(datetime.combine(appt.availability.date, appt.availability.start_time))
        appt_time_end = timezone.make_aware(datetime.combine(appt.availability.date, appt.availability.end_time))

        if appt.status == 'pending':
            appt.display_status = "Pending" if appt.availability.date >= today else "Expired / Missed"
            appt.status_color = "info" if appt.availability.date >= today else "secondary"
            pending_appointments.append(appt)

        elif appt.status == 'awaiting_payment':
            appt.display_status = "Awaiting Payment"
            appt.status_color = "secondary"
            upcoming_appointments.append(appt)

        elif appt.status == 'payment_verification':
            appt.display_status = "Payment Verification"
            appt.status_color = "warning"
            upcoming_appointments.append(appt)

        elif appt.status == 'upcoming':
            if appt_time_start > now:
                # Still in the future
                appt.display_status = "Upcoming"
                appt.status_color = "primary"
                upcoming_appointments.append(appt)
            elif appt_time_start <= now <= appt_time_end:
                # Active right now
                appt.display_status = "Ongoing"
                appt.status_color = "warning"
                ongoing_appointments.append(appt)
            else:
                # Time has passed
                appt.display_status = "Completed"
                appt.status_color = "success"
                completed_appointments.append(appt)

        elif appt.status == 'completed':
            appt.display_status = "Completed"
            appt.status_color = "success"
            completed_appointments.append(appt)

        elif appt.status == 'rejected':
            appt.display_status = "Rejected"
            appt.status_color = "danger"
            rejected_appointments.append(appt)

    return render(request, 'doctor/doctor_appointment.html', {
        'emergency_pending_requests': emergency_pending_requests,
        'doctor_has_future_slots': doctor_has_future_slots,
        'pending_appointments': pending_appointments,
        'upcoming_appointments': upcoming_appointments,
        'ongoing_appointments': ongoing_appointments,
        'completed_appointments': completed_appointments,
        'rejected_appointments': rejected_appointments,
        'pending_payment_verifications': pending_payment_verifications,
        'today': today,
    })

@login_required
def respond_appointment(request, appointment_id):
    appointment = get_object_or_404(Appointment, id=appointment_id, doctor=request.user)
    
    if request.method == 'POST':
        action = request.POST.get('action') 
        reject_reason = request.POST.get('reject_reason', '')

        if action == 'approve':
            appointment.status = 'awaiting_payment'
        
        elif action == 'reject':
            appointment.status = 'rejected'
            appointment.reject_reason = reject_reason
            
            # Re-activate the slot so other patients can see/book it again
            slot = appointment.availability
            slot.is_active = True 
            # If you use 'appointment__isnull' in public profile, 
            # you might want to nullify the relation or delete the appt.
            # But keeping it as 'rejected' is better for history.
            slot.save()
            
        appointment.save()

        if action == 'approve':
            _create_notification(
                appointment.user,
                'Appointment accepted',
                f'Your appointment with Dr. {request.user.doctor_profile.full_name} was accepted. Consultation will begin only after payment is completed.',
                'appointment_accepted',
                target_url=reverse('appointment'),
                target_section_id='upcoming-appointments-section',
            )
        elif action == 'reject':
            _create_notification(
                appointment.user,
                'Appointment rejected',
                f'Your appointment was rejected. Reason: {reject_reason or "Not provided"}.',
                'appointment_rejected',
                target_url=reverse('appointment'),
                target_section_id='appointments-section',
            )

        if action == 'approve':
            send_appointment_template_email(
                appointment.user,
                'accepted',
                {
                    'doctor_name': f"Dr. {request.user.doctor_profile.full_name}",
                    'appointment_date': appointment.availability.date.strftime('%Y-%m-%d'),
                    'appointment_time': f"{appointment.availability.start_time.strftime('%H:%M')} - {appointment.availability.end_time.strftime('%H:%M')}",
                    'action_url': reverse('appointment'),
                    'action_label': 'Open Appointments & Pay',
                },
            )
        elif action == 'reject':
            send_appointment_template_email(
                appointment.user,
                'rejected',
                {
                    'doctor_name': f"Dr. {request.user.doctor_profile.full_name}",
                    'appointment_date': appointment.availability.date.strftime('%Y-%m-%d'),
                    'reject_reason': reject_reason or 'No specific reason was provided.',
                    'action_url': reverse('explore_doctors'),
                    'action_label': 'Book Another Doctor',
                },
            )

        messages.success(request, f"Appointment {appointment.status} successfully.")
    
    return redirect('doctor_appointment') # Redirect back to the requests list


@login_required
def payment_page(request, appointment_id):
    """Display doctor's payment receiving details for a patient appointment."""
    appointment = get_object_or_404(Appointment, id=appointment_id, user=request.user)

    if appointment.status != 'awaiting_payment':
        messages.error(request, 'Payment page is available only for appointments awaiting payment.')
        return redirect('appointment')

    doctor_profile = get_object_or_404(DoctorProfile, user=appointment.doctor)
    payment_details = get_object_or_404(DoctorPaymentDetails, doctor=appointment.doctor, is_completed=True)

    existing_payment = Payment.objects.filter(appointment=appointment).first()
    if existing_payment and existing_payment.status in ['pending', 'approved']:
        messages.info(request, 'Payment has already been submitted for this appointment.')
        return redirect('appointment')

    return render(
        request,
        'payment/payment_page.html',
        {
            'appointment': appointment,
            'doctor_profile': doctor_profile,
            'payment_details': payment_details,
        }
    )


@login_required
def submit_payment(request, appointment_id):
    """Submit payment proof for manual doctor-side verification."""
    if request.method != 'POST':
        return redirect('payment_page', appointment_id=appointment_id)

    appointment = get_object_or_404(Appointment, id=appointment_id, user=request.user)
    if appointment.status != 'awaiting_payment':
        messages.error(request, 'You cannot submit payment for this appointment right now.')
        return redirect('appointment')

    payment_proof = request.FILES.get('payment_proof')
    if not payment_proof:
        messages.error(request, 'Please upload payment proof screenshot/image.')
        return redirect('payment_page', appointment_id=appointment.id)

    doctor_profile = get_object_or_404(DoctorProfile, user=appointment.doctor)
    total = doctor_profile.consultation_fee
    if not total or total <= 0:
        messages.error(request, 'Doctor consultation fee is not configured yet.')
        return redirect('appointment')

    commission = (total * Decimal('0.25')).quantize(Decimal('0.01'))
    doctor_earning = (total * Decimal('0.75')).quantize(Decimal('0.01'))

    existing_payment = Payment.objects.filter(appointment=appointment).first()
    if existing_payment and existing_payment.status in ['pending', 'approved']:
        messages.error(request, 'Payment has already been submitted for this appointment.')
        return redirect('appointment')

    if existing_payment and existing_payment.status == 'rejected':
        existing_payment.total_amount = total
        existing_payment.commission_amount = commission
        existing_payment.doctor_earning = doctor_earning
        existing_payment.payment_proof = payment_proof
        existing_payment.status = 'pending'
        existing_payment.save()
    else:
        Payment.objects.create(
            user=request.user,
            appointment=appointment,
            total_amount=total,
            commission_amount=commission,
            doctor_earning=doctor_earning,
            payment_proof=payment_proof,
            status='pending',
        )

    appointment.status = 'payment_verification'
    appointment.save(update_fields=['status'])

    _create_notification(
        appointment.doctor,
        'Payment Submitted',
        f'{request.user.username} submitted payment proof for appointment #{appointment.id}.',
        'appointment',
        target_url=reverse('doctor_dashboard'),
        target_section_id='payment-verification-section',
    )

    messages.success(request, 'Payment successful. Your consultation is now pending doctor verification.')
    return redirect('appointment')


@login_required
def verify_payment(request, payment_id):
    """Doctor verifies submitted payment proof for own appointment only."""
    if request.user.role != 'doctor':
        return redirect('home')

    payment = get_object_or_404(
        Payment.objects.select_related('appointment', 'user'),
        id=payment_id,
        appointment__doctor=request.user,
    )

    if request.method != 'POST':
        messages.error(request, 'Invalid verification request.')
        return redirect('doctor_dashboard')

    action = (request.POST.get('action') or '').strip().lower()
    if payment.status != 'pending':
        messages.error(request, 'This payment has already been verified.')
        return redirect('doctor_dashboard')

    if action == 'approve':
        payment.status = 'approved'
        payment.save(update_fields=['status'])
        payment.appointment.status = 'upcoming'
        payment.appointment.save(update_fields=['status'])

        _create_notification(
            payment.user,
            'Payment Approved',
            'Payment successful. Your consultation is now scheduled.',
            'appointment_accepted',
            target_url=reverse('appointment'),
            target_section_id='upcoming-appointments-section',
        )
        messages.success(request, 'Payment approved and consultation unlocked.')
    elif action == 'reject':
        payment.status = 'rejected'
        payment.save(update_fields=['status'])
        payment.appointment.status = 'awaiting_payment'
        payment.appointment.save(update_fields=['status'])

        _create_notification(
            payment.user,
            'Payment Rejected',
            'Your payment proof was rejected. Please submit a valid screenshot again.',
            'appointment_rejected',
            target_url=reverse('payment_page', kwargs={'appointment_id': payment.appointment.id}),
            target_section_id='upcoming-appointments-section',
        )
        messages.warning(request, 'Payment rejected. Appointment moved back to awaiting payment.')
    else:
        messages.error(request, 'Invalid action.')

    return redirect('doctor_dashboard')

@login_required
def doctor_profile(request):
    profile = get_object_or_404(DoctorProfile, user=request.user)
    payment_details, _ = DoctorPaymentDetails.objects.get_or_create(
        doctor=request.user,
        defaults={'payment_method': 'bank'}
    )

    if request.method == "POST":
        uploaded_photo = request.FILES.get("photo")
        bio = request.POST.get("bio", "").strip()
        qualifications = request.POST.get("qualifications", "").strip()
        languages_spoken = request.POST.get("languages_spoken", "").strip()
        consultation_fee_raw = (request.POST.get("consultation_fee") or "").strip()

        payment_method = (request.POST.get('payment_method') or '').strip()
        account_name = (request.POST.get('account_name') or '').strip()
        account_number = (request.POST.get('account_number') or '').strip()
        bank_name = (request.POST.get('bank_name') or '').strip()
        esewa_id = (request.POST.get('esewa_id') or '').strip()
        khalti_id = (request.POST.get('khalti_id') or '').strip()
        qr_code_image = request.FILES.get('qr_code_image')

        # Prevent making a previously browsable profile incomplete.
        has_photo_after_update = bool(uploaded_photo or (profile.photo and profile.photo.name))
        has_empty_required_field = not all([
            has_photo_after_update,
            bool(bio),
            bool(qualifications),
            bool(languages_spoken),
        ])

        consultation_fee = None
        if consultation_fee_raw:
            try:
                consultation_fee = Decimal(consultation_fee_raw)
            except (InvalidOperation, TypeError):
                messages.warning(request, "Please provide a valid consultation fee.")
                return render(request, "doctor/doctor_profile.html", {"profile": profile, "payment_details": payment_details})

        if consultation_fee is None or consultation_fee <= 0:
            messages.warning(request, "Consultation fee is required and must be greater than 0.")
            return render(request, "doctor/doctor_profile.html", {"profile": profile, "payment_details": payment_details})

        if has_empty_required_field:
            messages.warning(
                request,
                "Please fill all profile fields. If any field is empty, users will not be able to browse your profile."
            )
            return render(request, "doctor/doctor_profile.html", {"profile": profile, "payment_details": payment_details})

        if payment_method not in dict(DoctorPaymentDetails.PAYMENT_METHOD_CHOICES):
            messages.warning(request, "Please select a valid payment method.")
            return render(request, "doctor/doctor_profile.html", {"profile": profile, "payment_details": payment_details})

        payment_complete = False
        if payment_method == 'bank':
            payment_complete = bool(account_name and account_number and bank_name)
        elif payment_method == 'esewa':
            payment_complete = bool(esewa_id)
        elif payment_method == 'khalti':
            payment_complete = bool(khalti_id)
        elif payment_method == 'qr':
            payment_complete = bool(qr_code_image or payment_details.qr_code_image)

        if uploaded_photo:
            profile.photo = uploaded_photo

        profile.bio = bio
        profile.qualifications = qualifications
        profile.languages_spoken = languages_spoken
        profile.consultation_fee = consultation_fee

        payment_details.payment_method = payment_method
        payment_details.account_name = account_name or None
        payment_details.account_number = account_number or None
        payment_details.bank_name = bank_name or None
        payment_details.esewa_id = esewa_id or None
        payment_details.khalti_id = khalti_id or None
        if qr_code_image:
            payment_details.qr_code_image = qr_code_image
        payment_details.is_completed = payment_complete

        try:
            with transaction.atomic():
                profile.save()
                payment_details.save()
        except IntegrityError:
            messages.error(request, 'A doctor with this license number already exists.')
            return render(request, "doctor/doctor_profile.html", {"profile": profile, "payment_details": payment_details})

        messages.success(request, "Profile updated successfully!")
        return redirect("doctor_profile")

    return render(request, "doctor/doctor_profile.html", {"profile": profile, "payment_details": payment_details})


@login_required
def submit_doctor_review(request, pk):
    doctor = get_object_or_404(
        DoctorProfile,
        pk=pk,
        is_verified=True,
        is_profile_complete=True
    )

    if request.user.role != "user":
        # messages.error(request, "Only patients can leave reviews")
        return redirect("public_doctor_profile", pk=pk)

    if request.method == "POST":
        rating = request.POST.get("rating")
        comment = request.POST.get("comment", "").strip()

        DoctorReview.objects.update_or_create(
            doctor=doctor,
            patient=request.user,
            defaults={
                "rating": rating,
                "comment": comment
            }
        )

        messages.success(request, "Review submitted successfully")
        return redirect("public_doctor_profile", pk=pk)

    return redirect("public_doctor_profile", pk=pk)


def logout_view(request):
    logout(request)  
    return redirect("login")

# -----------------------------
# Dashboard views
# -----------------------------
from django.contrib.auth.decorators import login_required


def _bootstrapize_password_form(form):
    for field in form.fields.values():
        existing = field.widget.attrs.get('class', '')
        field.widget.attrs['class'] = f"{existing} form-control".strip()


def _create_notification(
    user,
    title,
    message,
    notification_type='system',
    target_url='',
    target_section_id='',
):
    if not user:
        return

    Notification.objects.create(
        user=user,
        title=title,
        message=message,
        type=notification_type,
        target_url=(target_url or ''),
        target_section_id=(target_section_id or ''),
    )


def _default_navigation_target(user, notification_type, title, message):
    role = getattr(user, 'role', 'user')
    haystack = f"{notification_type} {title} {message}".lower()

    if role == 'doctor':
        if any(token in haystack for token in ['emergency', 'urgent', 'alert']):
            return reverse('doctor_appointment'), 'emergency-section'
        if any(token in haystack for token in ['appointment', 'consultation', 'session', 'request']):
            return reverse('doctor_appointment'), 'appointments-section'
        if any(token in haystack for token in ['message', 'chat']):
            return reverse('doctor_appointment'), 'appointments-section'
        if any(token in haystack for token in ['profile']):
            return reverse('doctor_profile'), 'profile-section'
        if any(token in haystack for token in ['settings', 'password', 'email', 'security', 'account']):
            return reverse('doctor_settings'), 'settings-section'
        return reverse('doctor_dashboard'), ''

    if any(token in haystack for token in ['appointment', 'doctor']):
        return reverse('appointment'), 'appointments-section'
    if any(token in haystack for token in ['symptom', 'pain', 'mood', 'cycle']):
        return reverse('dashboard_home'), 'symptoms-section'
    if any(token in haystack for token in ['report', 'analysis', 'trend']):
        return reverse('dashboard_reports'), 'reports-section'
    if any(token in haystack for token in ['message', 'chat', 'consultation']):
        return reverse('dashboard_chat'), 'chat-section'
    if any(token in haystack for token in ['document', 'file', 'record']):
        return reverse('dashboard_profile'), 'documents-section'
    if any(token in haystack for token in ['profile']):
        return reverse('dashboard_profile'), 'profile-section'
    if any(token in haystack for token in ['settings', 'password', 'email', 'security', 'account']):
        return reverse('dashboard_settings'), 'settings-section'
    if any(token in haystack for token in ['emergency', 'urgent', 'alert']):
        return reverse('dashboard_home'), 'emergency-section'
    return reverse('dashboard_home'), ''


def _resolve_notification_target(notification):
    target_url = (notification.target_url or '').strip()
    target_section_id = (notification.target_section_id or '').strip()

    if target_url or target_section_id:
        return target_url, target_section_id

    return _default_navigation_target(
        notification.user,
        notification.type,
        notification.title,
        notification.message,
    )


def _has_recent_notification(user, title, hours=24, notification_type=None):
    if not user:
        return False

    safe_hours = max(int(hours or 1), 1)
    cutoff = timezone.now() - timedelta(hours=safe_hours)

    query = Notification.objects.filter(
        user=user,
        title=title,
        created_at__gte=cutoff,
    )
    if notification_type:
        query = query.filter(type=notification_type)
    return query.exists()


def _ensure_password_security_notice(user):
    if not user or user.role != 'user' or user.is_password_strong:
        return

    title = 'Security Update Required'
    message = (
        'For improved security, please update your password to a stronger one. '
        'This helps protect your personal health data.'
    )

    if not _has_recent_notification(user, title, hours=168, notification_type='system'):
        _create_notification(user, title, message, 'system')

    if user.email and not _has_recent_notification(user, title, hours=168, notification_type='email'):
        send_notification_template_email(
            user,
            message,
            {
                'notification_title': title,
                'subject': 'Important: Update Your Password',
                'action_url': reverse('dashboard_settings'),
                'action_label': 'Update Password',
            },
        )
        _create_notification(
            user,
            title,
            'An email reminder was sent to you about the password security update.',
            'email',
        )


def check_consecutive_symptoms(user, symptom):
    today = timezone.localdate()
    target_dates = {today - timedelta(days=offset) for offset in range(3)}
    logged_dates = set(
        SymptomLog.objects.filter(
            user=user,
            symptom=symptom,
            date__in=target_dates,
        ).values_list('date', flat=True)
    )
    return len(logged_dates) == len(target_dates) and logged_dates == target_dates


def send_email_alert(user, symptom):
    if not user or not user.email:
        return

    send_emergency_template_email(
        user,
        {
            'type': 'symptom_risk',
            'subject': 'Symptom Risk Alert - FemiCare',
            'symptom': symptom,
            'action_url': reverse('explore_doctors'),
            'action_label': 'Book Doctor',
        },
    )


def trigger_health_alert(user, symptom):
    if symptom not in RISK_SYMPTOMS:
        return False

    already_notified_today = Notification.objects.filter(
        user=user,
        title='Health Attention Needed',
        message__icontains=symptom,
        created_at__date=timezone.localdate(),
    ).exists()
    if already_notified_today:
        return False

    resources_path = reverse('resources')
    doctor_path = reverse('explore_doctors')

    _create_notification(
        user,
        'Health Attention Needed',
        (
            f'You have been experiencing {symptom} for multiple days. '
            'This may require attention. Please take care and consider consulting a doctor if needed. '
            f'Do not panic. Resources: {resources_path} | Doctor consultation: {doctor_path}'
        ),
        'cycle',
    )

    send_email_alert(user, symptom)
    return True


def calculate_risk_score(user, target_date=None):
    if not user:
        return {
            'score': 0,
            'level': 'none',
            'symptoms': [],
            'repeated_symptoms': [],
            'multiple_symptoms': False,
        }

    target_date = target_date or timezone.localdate()
    symptoms_today = list(
        SymptomLog.objects.filter(user=user, date=target_date)
        .values_list('symptom', flat=True)
    )
    unique_symptoms = sorted(set(symptoms_today))

    score = 0
    repeated_symptoms = []

    for symptom in unique_symptoms:
        if symptom in HIGH_RISK_SYMPTOMS:
            score += 3
        elif symptom in MEDIUM_RISK_SYMPTOMS:
            score += 2

        if symptom in RISK_SYMPTOMS and check_consecutive_symptoms(user, symptom):
            score += 5
            repeated_symptoms.append(symptom)

    multiple_symptoms = len(unique_symptoms) >= 2
    if multiple_symptoms:
        score += 2

    if score >= 9:
        level = 'high'
    elif score >= 5:
        level = 'medium'
    elif score >= 1:
        level = 'low'
    else:
        level = 'none'

    return {
        'score': score,
        'level': level,
        'symptoms': unique_symptoms,
        'repeated_symptoms': repeated_symptoms,
        'multiple_symptoms': multiple_symptoms,
    }


def send_emergency_email(user, score=None, symptoms=None, subject='Health Alert from FemiCare', body_message=None):
    if not user or not user.email:
        return False
    email_type = 'emergency_alert'
    if 'Delayed Period' in subject:
        email_type = 'delayed_period'

    return send_emergency_template_email(
        user,
        {
            'type': email_type,
            'subject': subject,
            'risk_score': score,
            'symptoms': symptoms or [],
            'alert_message': body_message or EMERGENCY_ALERT_MESSAGE,
            'action_url': reverse('dashboard_home') if email_type == 'emergency_alert' else reverse('explore_doctors'),
            'action_label': 'Open Dashboard' if email_type == 'emergency_alert' else 'Book Doctor',
        },
    )


def trigger_emergency_alert(user):
    assessment = calculate_risk_score(user)
    level = assessment['level']

    if level in {'none', 'low'}:
        assessment['triggered'] = False
        return assessment

    alert_cooldown_hours = getattr(settings, 'ALERT_NOTIFICATION_COOLDOWN_HOURS', 24)

    if level == 'medium':
        title = 'Health Warning'
        message = (
            'Your recent symptom pattern suggests moderate risk. '
            'Please continue monitoring and consult a doctor if symptoms persist.'
        )
        repeated_symptoms = assessment.get('repeated_symptoms') or []
        exists_recently = _has_recent_notification(
            user,
            title,
            hours=alert_cooldown_hours,
            notification_type='cycle',
        )
        if not exists_recently:
            _create_notification(user, title, message, 'cycle')
            if repeated_symptoms:
                send_email_alert(user, repeated_symptoms[0])

        assessment['triggered'] = not exists_recently
        assessment['notification_title'] = title
        return assessment

    exists_recently = _has_recent_notification(
        user,
        EMERGENCY_ALERT_TITLE,
        hours=alert_cooldown_hours,
        notification_type='cycle',
    )

    if not exists_recently:
        _create_notification(user, EMERGENCY_ALERT_TITLE, EMERGENCY_ALERT_MESSAGE, 'cycle')
        send_emergency_email(
            user,
            score=assessment['score'],
            symptoms=assessment['symptoms'],
            subject='Emergency Health Alert from FemiCare',
            body_message=EMERGENCY_ALERT_MESSAGE,
        )

    assessment['triggered'] = not exists_recently
    assessment['notification_title'] = EMERGENCY_ALERT_TITLE
    return assessment


def check_period_delay(user):
    if not user:
        return False

    delay_threshold_days = max(int(getattr(settings, 'PERIOD_DELAY_ALERT_DAYS', 6)), 5)
    threshold_date = timezone.localdate() - timedelta(days=delay_threshold_days)

    delayed_cycle = (
        CycleLog.objects.filter(user=user)
        .filter(actual_start_date__isnull=True, start_date__isnull=True)
        .filter(
            Q(predicted_start_date__lte=threshold_date)
            | Q(predicted_start_date__isnull=True, predicted_next_period__lte=threshold_date)
        )
        .order_by('-predicted_start_date', '-predicted_next_period', '-created_at')
        .first()
    )

    if not delayed_cycle:
        return False

    today = timezone.localdate()
    already_notified = Notification.objects.filter(
        user=user,
        title='Delayed Period Reminder',
        created_at__date=today,
    ).exists()
    if already_notified:
        return False

    _create_notification(
        user,
        'Delayed Period Reminder',
        DELAYED_PERIOD_MESSAGE,
        'cycle',
    )
    send_emergency_email(
        user,
        subject='Delayed Period Alert from FemiCare',
        body_message=DELAYED_PERIOD_MESSAGE,
    )
    return True


def _get_available_doctors_for_emergency():
    now = timezone.localtime(timezone.now())
    today = now.date()
    current_time = now.time()

    available_doctor_ids = (
        DoctorAvailability.objects.filter(is_active=True)
        .filter(
            Q(date__gt=today)
            | Q(date=today, start_time__gte=current_time)
        )
        .filter(appointment__isnull=True)
        .values_list('doctor_id', flat=True)
        .distinct()
    )
    return User.objects.filter(id__in=available_doctor_ids, role='doctor', is_verified=True)


def create_emergency_request(user, reason=''):
    if not user or user.role != 'user':
        return None

    existing = EmergencyRequest.objects.filter(
        user=user,
        status__in=['pending', 'assigned'],
    ).first()
    if existing:
        return existing

    request_obj = EmergencyRequest.objects.create(
        user=user,
        reason=(reason or '').strip(),
        status='pending',
    )
    _create_notification(
        user,
        'Emergency request submitted',
        'Your emergency consultation request has been submitted. We are finding the earliest available doctor.',
        'emergency_alert',
        target_url=reverse('dashboard_home'),
        target_section_id='emergency-section',
    )
    return request_obj


def notify_available_doctors(request_obj):
    if not request_obj:
        return 0

    doctors = _get_available_doctors_for_emergency()
    notified = 0

    for doctor in doctors:
        already_sent = Notification.objects.filter(
            user=doctor,
            title='Emergency consultation request',
            message__icontains=f'#{request_obj.id}',
            created_at__date=timezone.localdate(),
        ).exists()
        if already_sent:
            continue

        _create_notification(
            doctor,
            'Emergency consultation request',
            f'A patient requires urgent consultation. Request #{request_obj.id}.',
            'emergency_alert',
            target_url=reverse('doctor_appointment'),
            target_section_id='emergency-section',
        )

        if doctor.email:
            send_notification_template_email(
                doctor,
                (
                    'A patient requires urgent consultation. '
                    f'Request ID: #{request_obj.id}. Please review your dashboard and accept if available.'
                ),
                {
                    'notification_title': 'Emergency Consultation Request',
                    'subject': 'Urgent Consultation Request - FemiCare',
                    'action_url': reverse('doctor_appointment'),
                    'action_label': 'Review Emergency Requests',
                },
            )

        notified += 1

    return notified


def send_patient_email(user, slot):
    if not user or not user.email or not slot:
        return False
    return send_emergency_template_email(
        user,
        {
            'type': 'doctor_assigned',
            'subject': 'Emergency Consultation Assigned - FemiCare',
            'appointment_date': slot.date.strftime('%Y-%m-%d'),
            'appointment_time': f"{slot.start_time.strftime('%H:%M')} - {slot.end_time.strftime('%H:%M')}",
            'action_url': reverse('appointment'),
            'action_label': 'Open Dashboard',
        },
    )


def schedule_emergency_appointment(request_obj, doctor):
    if not request_obj or not doctor:
        return None

    now = timezone.localtime(timezone.now())
    today = now.date()
    current_time = now.time()

    slot = (
        DoctorAvailability.objects.select_for_update()
        .filter(doctor=doctor, is_active=True)
        .filter(
            Q(date__gt=today)
            | Q(date=today, start_time__gte=current_time)
        )
        .filter(appointment__isnull=True)
        .order_by('date', 'start_time')
        .first()
    )

    if not slot:
        return None

    appointment = Appointment.objects.create(
        user=request_obj.user,
        doctor=doctor,
        availability=slot,
        status='upcoming',
        patient_message=(request_obj.reason or 'Emergency consultation request')[:400],
    )

    slot.is_active = False
    slot.save(update_fields=['is_active'])

    _create_notification(
        request_obj.user,
        'Emergency appointment assigned',
        f'Your emergency consultation was assigned for {slot.date:%b %d, %Y} at {slot.start_time.strftime("%H:%M")}.',
        'appointment',
    )
    _create_notification(
        doctor,
        'Emergency appointment assigned',
        f'You accepted emergency request #{request_obj.id}. The appointment has been scheduled automatically.',
        'appointment',
    )
    send_patient_email(request_obj.user, slot)

    return appointment


def assign_doctor_to_request(request_obj, doctor):
    if not request_obj or not doctor:
        return None

    with transaction.atomic():
        locked = EmergencyRequest.objects.select_for_update().filter(id=request_obj.id).first()
        if not locked or locked.status != 'pending':
            return None

        appointment = schedule_emergency_appointment(locked, doctor)
        if not appointment:
            return None

        locked.status = 'assigned'
        locked.assigned_doctor = doctor
        locked.assigned_slot = appointment.availability
        locked.save(update_fields=['status', 'assigned_doctor', 'assigned_slot', 'updated_at'])
        return locked


def trigger_period_day_reminder(user, predicted_next_period):
    if not user or not predicted_next_period:
        return False

    today = timezone.localdate()
    if predicted_next_period != today:
        return False

    exists_today = Notification.objects.filter(
        user=user,
        title='Period Day Reminder',
        created_at__date=today,
    ).exists()
    if exists_today:
        return False

    _create_notification(
        user,
        'Period Day Reminder',
        'Today is your predicted period day. Make sure to log your symptoms so we can support your health better.',
        'cycle',
    )
    return True


def _get_latest_confirmed_cycle(user):
    return (
        CycleLog.objects.filter(user=user, is_confirmed=True)
        .filter(Q(start_date__isnull=False) | Q(actual_start_date__isnull=False) | Q(last_period_start__isnull=False))
        .order_by('-start_date', '-actual_start_date', '-last_period_start', '-created_at')
        .first()
    )


def _get_active_period(user):
    return (
        CycleLog.objects.filter(user=user)
        .filter(start_date__isnull=False)
        .filter(end_date__isnull=True)
        .order_by('-start_date', '-actual_start_date', '-last_period_start', '-created_at')
        .first()
    )


def is_period_active(user):
    return _get_active_period(user) is not None


def _resolve_prediction_date(cycle_log):
    if not cycle_log:
        return None
    return cycle_log.predicted_start_date or cycle_log.predicted_next_period


def _get_active_cycle_for_symptoms(user, target_date=None):
    target_date = target_date or timezone.localdate()

    active_period = _get_active_period(user)
    if active_period:
        period_start = active_period.start_date or active_period.actual_start_date or active_period.last_period_start
        if period_start and period_start <= target_date:
            return active_period

    actual_cycle = (
        CycleLog.objects.filter(user=user, is_confirmed=True)
        .filter(
            Q(start_date__lte=target_date)
            | Q(actual_start_date__lte=target_date)
            | Q(start_date__isnull=True, actual_start_date__isnull=True, last_period_start__lte=target_date)
        )
        .order_by('-start_date', '-actual_start_date', '-last_period_start', '-created_at')
        .first()
    )
    if actual_cycle:
        return actual_cycle

    return (
        CycleLog.objects.filter(user=user)
        .exclude(last_period_start__isnull=True)
        .filter(last_period_start__lte=target_date)
        .order_by('-last_period_start')
        .first()
    )


def update_cycle_prediction(user):
    reference_cycle = _get_latest_confirmed_cycle(user)
    if not reference_cycle:
        return None

    start_date = reference_cycle.start_date or reference_cycle.actual_start_date or reference_cycle.last_period_start
    if not start_date:
        return None

    historical_cycle_lengths = list(
        CycleLog.objects.filter(user=user)
        .exclude(length_of_cycle__isnull=True)
        .values_list('length_of_cycle', flat=True)
    )
    predicted_days = int(round(sum(historical_cycle_lengths) / len(historical_cycle_lengths))) if historical_cycle_lengths else 28
    predicted_days = max(predicted_days, 1)

    predicted_start = start_date + timedelta(days=predicted_days)
    ovulation_day = predicted_start - timedelta(days=14)

    reference_cycle.predicted_start_date = predicted_start
    reference_cycle.predicted_next_period = predicted_start
    reference_cycle.estimated_ovulation_day = ovulation_day
    reference_cycle.fertile_window_start = ovulation_day - timedelta(days=5)
    reference_cycle.fertile_window_end = ovulation_day
    reference_cycle.save(
        update_fields=[
            'predicted_start_date',
            'predicted_next_period',
            'estimated_ovulation_day',
            'fertile_window_start',
            'fertile_window_end',
        ]
    )
    return reference_cycle


def create_period(user, start_date, end_date=None):
    if not user or not start_date:
        return None

    today = timezone.localdate()
    if start_date > today:
        raise ValueError('Future dates are not allowed.')

    if end_date:
        if end_date < start_date:
            raise ValueError('End date cannot be before start date.')
        if end_date > today:
            raise ValueError('End date cannot be in the future.')

    active_period = _get_active_period(user)
    if active_period:
        active_start = active_period.start_date or active_period.actual_start_date or active_period.last_period_start
        if active_start != start_date:
            raise ValueError('Cannot create a new period while one is active.')

    existing_cycle = (
        CycleLog.objects.filter(user=user)
        .filter(Q(start_date=start_date) | Q(actual_start_date=start_date) | Q(last_period_start=start_date))
        .order_by('-created_at')
        .first()
    )

    expected_end_date = start_date + timedelta(days=5)

    if existing_cycle:
        existing_cycle.start_date = start_date
        existing_cycle.actual_start_date = start_date
        existing_cycle.last_period_start = start_date
        existing_cycle.expected_end_date = expected_end_date
        existing_cycle.end_date = end_date
        existing_cycle.is_confirmed = True
        existing_cycle.save(
            update_fields=[
                'start_date',
                'actual_start_date',
                'last_period_start',
                'expected_end_date',
                'end_date',
                'is_confirmed',
            ]
        )
        SymptomLog.objects.filter(user=user, date=start_date, cycle_log__isnull=True).update(cycle_log=existing_cycle)
        update_cycle_prediction(user)
        return existing_cycle

    latest_log = CycleLog.objects.filter(user=user).order_by('-created_at').first()
    latest_confirmed = _get_latest_confirmed_cycle(user)
    previous_start = None
    if latest_confirmed:
        previous_start = latest_confirmed.start_date or latest_confirmed.actual_start_date or latest_confirmed.last_period_start

    derived_cycle_length = None
    if previous_start and start_date > previous_start:
        derived_cycle_length = (start_date - previous_start).days

    user_profile, _ = UserProfile.objects.get_or_create(user=user)

    base_cycle = latest_confirmed or latest_log
    default_cycle_length = derived_cycle_length or (base_cycle.length_of_cycle if base_cycle and base_cycle.length_of_cycle else 28)
    default_menses_length = base_cycle.length_of_menses if base_cycle and base_cycle.length_of_menses else 5
    default_menses_score = base_cycle.total_menses_score if base_cycle and base_cycle.total_menses_score is not None else 3
    default_intensity = base_cycle.mean_bleeding_intensity if base_cycle and base_cycle.mean_bleeding_intensity else 2

    height_cm = float(user_profile.height_cm) if user_profile.height_cm is not None else (float(base_cycle.height_cm) if base_cycle and base_cycle.height_cm is not None else 0.0)
    weight_kg = float(user_profile.weight_kg) if user_profile.weight_kg is not None else (float(base_cycle.weight_kg) if base_cycle and base_cycle.weight_kg is not None else 0.0)

    bmi = None
    if height_cm and weight_kg:
        height_m = height_cm / 100
        if height_m > 0:
            bmi = round(weight_kg / (height_m ** 2), 2)

    cycle = CycleLog.objects.create(
        user=user,
        start_date=start_date,
        last_period_start=start_date,
        actual_start_date=start_date,
        end_date=end_date,
        expected_end_date=expected_end_date,
        is_confirmed=True,
        length_of_cycle=default_cycle_length,
        length_of_menses=default_menses_length,
        mean_menses_length=default_menses_length,
        mean_bleeding_intensity=default_intensity,
        total_menses_score=default_menses_score,
        unusual_bleeding=base_cycle.unusual_bleeding if base_cycle else False,
        height_cm=height_cm,
        weight_kg=weight_kg,
        bmi=bmi,
    )

    SymptomLog.objects.filter(user=user, date=start_date, cycle_log__isnull=True).update(cycle_log=cycle)
    update_cycle_prediction(user)
    return cycle


def end_period(user, end_date):
    if not user:
        return None

    active_period = _get_active_period(user)
    if not active_period:
        raise ValueError('No active period found.')

    start_date = active_period.start_date or active_period.actual_start_date or active_period.last_period_start
    if not start_date:
        raise ValueError('Active period is missing a valid start date.')

    today = timezone.localdate()
    if end_date > today:
        raise ValueError('End date cannot be in the future.')
    if end_date < start_date:
        raise ValueError('End date cannot be before start date.')

    active_period.end_date = end_date
    active_period.length_of_menses = max((end_date - start_date).days + 1, 1)
    active_period.mean_menses_length = active_period.length_of_menses
    active_period.save(update_fields=['end_date', 'length_of_menses', 'mean_menses_length'])

    update_cycle_prediction(user)
    return active_period


def log_period_start(user, date):
    return create_period(user=user, start_date=date)


def handle_delayed_period(user):
    return check_period_delay(user)


def _relative_time(value):
    now = timezone.now()
    diff = now - value
    seconds = int(diff.total_seconds())

    if seconds < 60:
        return 'just now'

    minutes = seconds // 60
    if minutes < 60:
        return f'{minutes} min ago'

    hours = minutes // 60
    if hours < 24:
        return f'{hours} hr ago'

    days = hours // 24
    return f'{days} day ago' if days == 1 else f'{days} days ago'


def generate_report(user):
    today = timezone.localdate()

    cycle_logs = list(
        CycleLog.objects.filter(user=user)
        .exclude(last_period_start__isnull=True)
        .order_by('-last_period_start')
    )
    cycle_lengths = [item.length_of_cycle for item in cycle_logs if item.length_of_cycle]
    average_cycle_length = round(sum(cycle_lengths) / len(cycle_lengths), 1) if cycle_lengths else None

    recent_period_dates = [item.last_period_start for item in cycle_logs[:6]]
    predicted_next_period = None
    if cycle_logs:
        predicted_next_period = cycle_logs[0].predicted_start_date or cycle_logs[0].predicted_next_period

    symptom_frequency = list(
        SymptomLog.objects.filter(user=user)
        .values('symptom')
        .annotate(count=Count('id'))
        .order_by('-count', 'symptom')[:10]
    )

    last_30_days = today - timedelta(days=29)
    mood_entries = MoodEntry.objects.filter(user=user, date__gte=last_30_days)
    mood_trends = list(
        mood_entries.values('mood')
        .annotate(count=Count('id'))
        .order_by('-count', 'mood')
    )

    repeated_alert_notifications = list(
        Notification.objects.filter(
            user=user,
            title='Health Attention Needed',
        )
        .order_by('-created_at')[:15]
    )

    repeated_symptom_alerts = []
    symptom_dates = {}
    for row in SymptomLog.objects.filter(user=user).values('symptom', 'date').order_by('symptom', 'date'):
        symptom_dates.setdefault(row['symptom'], []).append(row['date'])

    for symptom_name, dates in symptom_dates.items():
        unique_dates = sorted(set(dates))
        streak = 1
        detected_on = None

        for index in range(1, len(unique_dates)):
            if (unique_dates[index] - unique_dates[index - 1]).days == 1:
                streak += 1
            else:
                streak = 1

            if streak >= 3:
                detected_on = unique_dates[index]

        if detected_on:
            repeated_symptom_alerts.append(
                {
                    'symptom': symptom_name,
                    'detected_on': detected_on,
                }
            )

    repeated_symptom_alerts.sort(key=lambda item: item['detected_on'], reverse=True)

    documents = list(
        UserDocument.objects.filter(user=user)
        .order_by('-uploaded_at')
    )

    appointments = list(
        Appointment.objects.filter(user=user)
        .select_related('doctor', 'doctor__doctor_profile', 'availability')
        .order_by('-created_at')
    )

    consultation_history = []
    for appt in appointments:
        doctor_name = appt.doctor.get_full_name().strip() or appt.doctor.username
        consultation_history.append(
            {
                'appointment_date': appt.availability.date if appt.availability_id else None,
                'doctor_name': doctor_name,
                'status': appt.status,
                'created_at': appt.created_at,
            }
        )

    return {
        'generated_at': timezone.localtime(),
        'cycle_summary': {
            'average_cycle_length': average_cycle_length,
            'last_period_dates': recent_period_dates,
            'predicted_next_period': predicted_next_period,
        },
        'symptom_report': {
            'most_frequent_symptoms': symptom_frequency,
            'mood_trends': mood_trends,
            'repeated_symptom_alerts': repeated_symptom_alerts,
        },
        'health_alerts': {
            'symptoms_repeated_3_days': repeated_symptom_alerts,
            'triggered_alerts': repeated_alert_notifications,
        },
        'medical_documents': documents,
        'consultation_history': consultation_history,
    }


def _format_pdf_date(value):
    if not value:
        return 'N/A'
    if hasattr(value, 'strftime'):
        return value.strftime('%d %b %Y')
    return str(value)


def _format_pdf_datetime(value):
    if not value:
        return 'N/A'
    if hasattr(value, 'strftime'):
        return timezone.localtime(value).strftime('%d %b %Y, %I:%M %p')
    return str(value)


def _safe_pdf_text(value, default='N/A'):
    if value in (None, ''):
        return default
    return escape(str(value))


def _build_image_flowable(path, max_width, max_height):
    if not path:
        return Spacer(max_width, max_height)

    image_path = Path(path)
    if not image_path.exists():
        return Spacer(max_width, max_height)

    try:
        image = Image(str(image_path))
        width, height = ImageReader(str(image_path)).getSize()
        scale = min(max_width / width, max_height / height)
        image.drawWidth = width * scale
        image.drawHeight = height * scale
        return image
    except Exception:
        return Spacer(max_width, max_height)


def _build_pdf_report_data(user):
    report_data = generate_report(user)
    profile = getattr(user, 'user_profile', None)
    today = timezone.localdate()

    cycle_logs = list(
        CycleLog.objects.filter(user=user)
        .exclude(last_period_start__isnull=True)
        .order_by('-last_period_start', '-created_at')
    )
    cycle_log_ids = [item.id for item in cycle_logs]

    checkins = {
        item.cycle_log_id: item
        for item in PeriodCheckIn.objects.filter(user=user, cycle_log_id__in=cycle_log_ids)
    }

    mood_entries = list(MoodEntry.objects.filter(user=user).values('mood', 'date'))
    symptom_entries = list(SymptomLog.objects.filter(user=user).values('symptom', 'date'))
    feedback_entries = list(PredictionFeedback.objects.filter(user=user).values('is_correct'))

    cycle_rows = []
    for log in cycle_logs:
        checkin = checkins.get(log.id)
        reference_date = log.last_period_start or log.predicted_start_date or today
        window_start = reference_date - timedelta(days=1)
        window_end = reference_date + timedelta(days=2)

        cycle_moods = Counter(
            item['mood']
            for item in mood_entries
            if window_start <= item['date'] <= window_end
        )

        cycle_symptoms = Counter(
            item['symptom']
            for item in symptom_entries
            if item['date'] == reference_date or (
                log.id and item['date'] >= reference_date and item['date'] <= reference_date + timedelta(days=6)
            )
        )

        cycle_rows.append(
            {
                'date': _format_pdf_date(log.last_period_start),
                'cycle_length': log.length_of_cycle or 'N/A',
                'flow': _safe_pdf_text(checkin.get_blood_flow_display() if checkin else None),
                'pain': _safe_pdf_text(checkin.get_pain_level_display() if checkin else None),
                'moods': ', '.join(
                    f"{mood.title()} ({count})" for mood, count in cycle_moods.most_common(2)
                ) or 'No mood entries',
                'symptoms': ', '.join(
                    f"{symptom} ({count})" for symptom, count in cycle_symptoms.most_common(3)
                ) or 'No symptom entries',
            }
        )

    cycle_lengths = [item.length_of_cycle for item in cycle_logs if item.length_of_cycle]
    if cycle_lengths:
        min_cycle = min(cycle_lengths)
        max_cycle = max(cycle_lengths)
        spread = max_cycle - min_cycle
        if spread == 0:
            cycle_regularity = f"Stable at {min_cycle} days"
        elif spread <= 2:
            cycle_regularity = f"Consistent range: {min_cycle}-{max_cycle} days"
        else:
            cycle_regularity = f"Variable range: {min_cycle}-{max_cycle} days"
    else:
        cycle_regularity = 'Not enough logged cycles yet'

    avg_cycle_length = report_data['cycle_summary']['average_cycle_length']
    recent_period_dates = [item.last_period_start for item in cycle_logs[:6]]
    predicted_next_period = report_data['cycle_summary']['predicted_next_period']
    latest_cycle = cycle_logs[0] if cycle_logs else None

    top_symptoms = report_data['symptom_report']['most_frequent_symptoms']
    mood_trends = report_data['symptom_report']['mood_trends']

    if feedback_entries:
        correct_predictions = sum(1 for item in feedback_entries if item['is_correct'])
        prediction_accuracy = f"{correct_predictions} of {len(feedback_entries)} logged predictions matched the tracked date"
    else:
        prediction_accuracy = 'No prediction feedback has been logged yet'

    if latest_cycle and latest_cycle.estimated_ovulation_day:
        fertile_window = ''
        if latest_cycle.fertile_window_start and latest_cycle.fertile_window_end:
            fertile_window = (
                f" with a fertile window from {_format_pdf_date(latest_cycle.fertile_window_start)} "
                f"to {_format_pdf_date(latest_cycle.fertile_window_end)}"
            )
        ovulation_summary = f"Latest estimated ovulation: {_format_pdf_date(latest_cycle.estimated_ovulation_day)}{fertile_window}"
    else:
        ovulation_summary = 'No ovulation estimate available yet'

    recent_cutoff = today - timedelta(days=14)
    prior_cutoff = today - timedelta(days=28)
    recent_symptoms = Counter(
        item['symptom']
        for item in symptom_entries
        if item['date'] >= recent_cutoff
    )
    prior_symptoms = Counter(
        item['symptom']
        for item in symptom_entries
        if prior_cutoff <= item['date'] < recent_cutoff
    )

    notable_changes = []
    for symptom, count in recent_symptoms.most_common(5):
        previous_count = prior_symptoms.get(symptom, 0)
        if count > previous_count:
            notable_changes.append(
                f"{symptom} increased from {previous_count} to {count} logged entries in the last 14 days"
            )
    if not notable_changes:
        notable_changes.append('No strong change in symptom frequency was detected from the available logs')

    high_frequency_patterns = []
    for alert in report_data['symptom_report']['repeated_symptom_alerts']:
        high_frequency_patterns.append(
            f"{alert['symptom']} appeared on at least three consecutive days, most recently detected on {_format_pdf_date(alert['detected_on'])}"
        )
    if not high_frequency_patterns:
        high_frequency_patterns.append('No three-day symptom streaks were detected in the available log history')

    high_risk_symptoms = sorted(
        {item['symptom'] for item in report_data['symptom_report']['most_frequent_symptoms'] if item['symptom'] in HIGH_RISK_SYMPTOMS}
    )
    if high_risk_symptoms:
        high_risk_summary = [
            f"{symptom} was logged and falls within the high-risk symptom set"
            for symptom in high_risk_symptoms[:5]
        ]
    else:
        high_risk_summary = ['No high-risk symptoms were logged in the current report window']

    if profile and getattr(profile, 'date_of_birth', None):
        today = timezone.localdate()
        age = today.year - profile.date_of_birth.year - ((today.month, today.day) < (profile.date_of_birth.month, profile.date_of_birth.day))
        age_text = f'{age} years'
    else:
        age_text = 'Not provided'

    if profile and getattr(profile, 'photo', None):
        avatar_path = profile.photo.path if profile.photo else None
    else:
        avatar_path = None

    static_root = Path(settings.BASE_DIR) / 'FemiCare' / 'static' / 'images'
    logo_path = static_root / 'femicare_logo.png'

    return {
        'generated_at': report_data['generated_at'],
        'profile': profile,
        'age_text': age_text,
        'cycle_regularity': cycle_regularity,
        'recent_period_dates': recent_period_dates,
        'predicted_next_period': predicted_next_period,
        'avg_cycle_length': avg_cycle_length,
        'top_symptoms': top_symptoms,
        'mood_trends': mood_trends,
        'prediction_accuracy': prediction_accuracy,
        'ovulation_summary': ovulation_summary,
        'cycle_rows': cycle_rows,
        'notable_changes': notable_changes,
        'high_frequency_patterns': high_frequency_patterns,
        'high_risk_summary': high_risk_summary,
        'avatar_path': avatar_path,
        'logo_path': str(logo_path),
    }


def _build_report_styles():
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name='ReportTitle',
            parent=styles['Title'],
            fontName='Helvetica-Bold',
            fontSize=22,
            leading=26,
            textColor=colors.HexColor('#243447'),
            alignment=TA_LEFT,
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name='ReportSubtitle',
            parent=styles['BodyText'],
            fontName='Helvetica',
            fontSize=9.5,
            leading=12,
            textColor=colors.HexColor('#6b7280'),
            alignment=TA_LEFT,
            spaceAfter=0,
        )
    )
    styles.add(
        ParagraphStyle(
            name='SectionHeading',
            parent=styles['Heading2'],
            fontName='Helvetica-Bold',
            fontSize=13,
            leading=16,
            textColor=colors.HexColor('#1f2937'),
            spaceBefore=8,
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name='SubHeading',
            parent=styles['BodyText'],
            fontName='Helvetica-Bold',
            fontSize=10,
            leading=12,
            textColor=colors.HexColor('#374151'),
            spaceBefore=4,
            spaceAfter=3,
        )
    )
    styles.add(
        ParagraphStyle(
            name='ReportBody',
            parent=styles['BodyText'],
            fontName='Helvetica',
            fontSize=9,
            leading=12,
            textColor=colors.HexColor('#374151'),
        )
    )
    styles.add(
        ParagraphStyle(
            name='ReportBullet',
            parent=styles['BodyText'],
            fontName='Helvetica',
            fontSize=9,
            leading=12,
            leftIndent=12,
            firstLineIndent=0,
            textColor=colors.HexColor('#374151'),
            spaceAfter=2,
        )
    )
    styles.add(
        ParagraphStyle(
            name='TableCell',
            parent=styles['BodyText'],
            fontName='Helvetica',
            fontSize=8.5,
            leading=10.5,
            textColor=colors.HexColor('#374151'),
        )
    )
    styles.add(
        ParagraphStyle(
            name='TableHeader',
            parent=styles['BodyText'],
            fontName='Helvetica-Bold',
            fontSize=8.5,
            leading=10.5,
            alignment=TA_CENTER,
            textColor=colors.white,
        )
    )
    styles.add(
        ParagraphStyle(
            name='MiniLabel',
            parent=styles['BodyText'],
            fontName='Helvetica-Bold',
            fontSize=8,
            leading=10,
            textColor=colors.HexColor('#6b7280'),
            alignment=TA_CENTER,
        )
    )
    return styles


def build_header_section(user, data=None):
    report_data = data or _build_pdf_report_data(user)
    styles = _build_report_styles()

    display_name = (user.get_full_name() or user.username).strip()
    email_address = user.email or 'Not provided'
    summary = [
        [Paragraph('<b>Full name</b>', styles['MiniLabel']), Paragraph(_safe_pdf_text(display_name), styles['TableCell']), Paragraph('<b>Email</b>', styles['MiniLabel']), Paragraph(_safe_pdf_text(email_address), styles['TableCell'])],
        [Paragraph('<b>Age</b>', styles['MiniLabel']), Paragraph(_safe_pdf_text(report_data['age_text']), styles['TableCell']), Paragraph('<b>Cycle regularity</b>', styles['MiniLabel']), Paragraph(_safe_pdf_text(report_data['cycle_regularity']), styles['TableCell'])],
        [Paragraph('<b>Last period</b>', styles['MiniLabel']), Paragraph(_safe_pdf_text(', '.join(_format_pdf_date(item) for item in report_data['recent_period_dates'][:3]) or 'N/A'), styles['TableCell']), Paragraph('<b>Next predicted period</b>', styles['MiniLabel']), Paragraph(_safe_pdf_text(_format_pdf_date(report_data['predicted_next_period'])), styles['TableCell'])],
    ]

    avatar = _build_image_flowable(report_data['avatar_path'], 0.72 * inch, 0.72 * inch)
    logo = _build_image_flowable(report_data['logo_path'], 0.78 * inch, 0.78 * inch)

    header_block = Table(
        [[avatar, [
            Paragraph('FemiCare Health Report', styles['ReportTitle']),
            Paragraph(
                f"Generated {_safe_pdf_text(_format_pdf_datetime(report_data['generated_at']))}",
                styles['ReportSubtitle'],
            ),
        ], logo]],
        colWidths=[0.9 * inch, 5.6 * inch, 0.9 * inch],
    )
    header_block.setStyle(
        TableStyle(
            [
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('ALIGN', (0, 0), (0, 0), 'LEFT'),
                ('ALIGN', (2, 0), (2, 0), 'RIGHT'),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ]
        )
    )

    details_table = Table(summary, colWidths=[1.05 * inch, 2.15 * inch, 1.25 * inch, 2.15 * inch])
    details_table.setStyle(
        TableStyle(
            [
                ('BACKGROUND', (0, 0), (-1, -1), colors.whitesmoke),
                ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#374151')),
                ('BOX', (0, 0), (-1, -1), 0.6, colors.HexColor('#d1d5db')),
                ('INNERGRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#e5e7eb')),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 5),
                ('RIGHTPADDING', (0, 0), (-1, -1), 5),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]
        )
    )

    return [header_block, Spacer(1, 0.14 * inch), details_table, Spacer(1, 0.18 * inch)]


def build_insight_section(data):
    styles = _build_report_styles()
    insight_rows = [
        ('Average cycle length', _safe_pdf_text(f"{data['avg_cycle_length']} days" if data['avg_cycle_length'] else 'No cycle lengths logged yet')),
        ('Cycle variation range', _safe_pdf_text(data['cycle_regularity'])),
        ('Most frequent symptoms', _safe_pdf_text(', '.join(
            f"{item['symptom']} ({item['count']})" for item in data['top_symptoms'][:3]
        ) or 'No symptom data logged yet')),
        ('Mood trends', _safe_pdf_text(', '.join(
            f"{item['mood'].title()} ({item['count']})" for item in data['mood_trends'][:3]
        ) or 'No mood data logged yet')),
        ('Prediction accuracy overview', _safe_pdf_text(data['prediction_accuracy'])),
        ('Ovulation prediction summary', _safe_pdf_text(data['ovulation_summary'])),
    ]

    table_rows = [[Paragraph('<b>Insight</b>', styles['TableHeader']), Paragraph('<b>Summary</b>', styles['TableHeader'])]]
    for label, value in insight_rows:
        table_rows.append([Paragraph(_safe_pdf_text(label), styles['TableCell']), Paragraph(value, styles['TableCell'])])

    insight_table = Table(table_rows, colWidths=[1.95 * inch, 5.15 * inch], repeatRows=1)
    insight_table.setStyle(
        TableStyle(
            [
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3f4b59')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')]),
                ('BOX', (0, 0), (-1, -1), 0.6, colors.HexColor('#cbd5e1')),
                ('INNERGRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#e5e7eb')),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 6),
                ('RIGHTPADDING', (0, 0), (-1, -1), 6),
                ('TOPPADDING', (0, 0), (-1, -1), 5),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ]
        )
    )

    return [
        Paragraph('Key Insights', styles['SectionHeading']),
        insight_table,
        Spacer(1, 0.16 * inch),
    ]


def build_cycle_table(logs):
    styles = _build_report_styles()
    rows = [[
        Paragraph('<b>Date</b>', styles['TableHeader']),
        Paragraph('<b>Cycle length</b>', styles['TableHeader']),
        Paragraph('<b>Flow</b>', styles['TableHeader']),
        Paragraph('<b>Pain</b>', styles['TableHeader']),
        Paragraph('<b>Mood and symptoms</b>', styles['TableHeader']),
    ]]

    for item in logs:
        mood_and_symptoms = f"<b>Moods:</b> {item['moods']}<br/><b>Symptoms:</b> {item['symptoms']}"
        rows.append([
            Paragraph(_safe_pdf_text(item['date']), styles['TableCell']),
            Paragraph(_safe_pdf_text(item['cycle_length']), styles['TableCell']),
            Paragraph(_safe_pdf_text(item['flow']), styles['TableCell']),
            Paragraph(_safe_pdf_text(item['pain']), styles['TableCell']),
            Paragraph(mood_and_symptoms, styles['TableCell']),
        ])

    cycle_table = Table(rows, colWidths=[1.0 * inch, 0.9 * inch, 0.85 * inch, 0.8 * inch, 3.85 * inch], repeatRows=1)
    cycle_table.setStyle(
        TableStyle(
            [
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3f4b59')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')]),
                ('BOX', (0, 0), (-1, -1), 0.6, colors.HexColor('#cbd5e1')),
                ('INNERGRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#e5e7eb')),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 5),
                ('RIGHTPADDING', (0, 0), (-1, -1), 5),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]
        )
    )

    return [
        Paragraph('Cycle Log Table', styles['SectionHeading']),
        cycle_table,
        Spacer(1, 0.16 * inch),
    ]


def build_symptom_summary(data):
    styles = _build_report_styles()
    summary_flowables = [Paragraph('Symptom Summary', styles['SectionHeading'])]

    sections = [
        ('Frequently occurring symptoms', [
            f"{item['symptom']} was logged {item['count']} time(s)" for item in data['top_symptoms'][:5]
        ]),
        ('Notable changes', data['notable_changes']),
        ('High frequency patterns', data['high_frequency_patterns']),
        ('High-risk symptoms', data['high_risk_summary']),
    ]

    for heading, items in sections:
        summary_flowables.append(Paragraph(_safe_pdf_text(heading), styles['SubHeading']))
        for item in items:
            summary_flowables.append(Paragraph(_safe_pdf_text(item), styles['ReportBullet'], bulletText='-'))

    summary_flowables.append(Spacer(1, 0.12 * inch))
    return summary_flowables


def build_recommendations():
    styles = _build_report_styles()
    recommendations = [
        'Keep logging periods, symptoms, and mood entries consistently so the cycle summary stays accurate.',
        'Review the report after each new cycle to notice changing patterns early.',
        'Update prediction feedback when available because it improves the accuracy of future estimates.',
        'Share any concerning or recurring high-risk symptoms with a clinician for review.',
    ]

    flowables = [Paragraph('Recommendations', styles['SectionHeading'])]
    for recommendation in recommendations:
        flowables.append(Paragraph(_safe_pdf_text(recommendation), styles['ReportBullet'], bulletText='-'))
    flowables.append(
        Paragraph(
            'This report summarizes tracked information and is for reference only. It is not a medical diagnosis.',
            styles['ReportBody'],
        )
    )
    return flowables


def _draw_report_page(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor('#d1d5db'))
    canvas.setLineWidth(0.6)
    canvas.line(doc.leftMargin, doc.height + doc.topMargin - 10, doc.width + doc.leftMargin, doc.height + doc.topMargin - 10)
    canvas.setFont('Helvetica', 8)
    canvas.setFillColor(colors.HexColor('#6b7280'))
    canvas.drawString(doc.leftMargin, 18, 'FemiCare Health Report')
    canvas.drawRightString(doc.width + doc.leftMargin, 18, f'Page {canvas.getPageNumber()}')
    canvas.restoreState()


@login_required
def dashboard_reports(request):
    role_redirect = _ensure_user_access(request)
    if role_redirect:
        return role_redirect

    context = {
        'active_page': 'reports',
    }
    return render(request, 'dashboard/reports.html', context)


@login_required
def export_reports_pdf(request):
    role_redirect = _ensure_user_access(request)
    if role_redirect:
        return role_redirect

    report_data = _build_pdf_report_data(request.user)
    buffer = BytesIO()

    document = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=0.55 * inch,
        rightMargin=0.55 * inch,
        topMargin=0.7 * inch,
        bottomMargin=0.7 * inch,
        title='FemiCare Health Report',
        author='FemiCare',
        subject='User health report export',
    )

    story = []
    story.extend(build_header_section(request.user, report_data))
    story.extend(build_insight_section(report_data))
    story.extend(build_cycle_table(report_data['cycle_rows']))
    story.extend(build_symptom_summary(report_data))
    story.extend(build_recommendations())

    try:
        document.build(story, onFirstPage=_draw_report_page, onLaterPages=_draw_report_page)
    except Exception:
        logger.exception('Unable to generate ReportLab PDF report for user %s', request.user.pk)
        messages.error(request, 'Unable to generate PDF report at the moment.')
        return redirect('dashboard_reports')

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="femicare_health_report.pdf"'
    response.write(buffer.getvalue())

    _create_notification(
        request.user,
        'Report export completed',
        'Your report was exported successfully.',
        'system',
        target_url=reverse('dashboard_reports'),
        target_section_id='reports-section',
    )

    return response


def _clear_email_verification_session(
    request,
    pending_key='pending_email',
    code_key='email_otp_code',
    created_key='email_otp_created_at',
):
    request.session.pop(pending_key, None)
    request.session.pop(code_key, None)
    request.session.pop(created_key, None)


def _send_email_verification_code(
    request,
    new_email,
    pending_key='pending_email',
    code_key='email_otp_code',
    created_key='email_otp_created_at',
    action_url_name='dashboard_settings',
):
    otp = str(random.SystemRandom().randint(100000, 999999))

    request.session[pending_key] = new_email
    request.session[code_key] = otp
    request.session[created_key] = int(time.time())

    send_verification_email(
        request.user,
        'email_verification',
        {
            'recipient_email': new_email,
            'code': otp,
            'expires_minutes': 10,
            'subject': 'FemiCare Email Verification Code',
            'action_url': reverse(action_url_name),
            'action_label': 'Review Settings',
        },
    )


def _delete_user_account_data(user):
    from .models import Conversation, ChatMessage

    doctor_rooms = list(Conversation.objects.filter(doctor=user).values_list('room_name', flat=True))
    patient_rooms = list(Conversation.objects.filter(patient=user).values_list('room_name', flat=True))
    room_names = list(set(doctor_rooms + patient_rooms))

    for message in ChatMessage.objects.filter(room_name__in=room_names).exclude(file=''):
        if message.file:
            message.file.delete(save=False)

    for document in UserDocument.objects.filter(user=user):
        if document.file:
            document.file.delete(save=False)

    try:
        profile = user.user_profile
        if profile.profile_picture:
            profile.profile_picture.delete(save=False)
    except UserProfile.DoesNotExist:
        pass

    try:
        doctor_profile = user.doctor_profile
        if doctor_profile.photo:
            doctor_profile.photo.delete(save=False)
        if doctor_profile.certificate:
            doctor_profile.certificate.delete(save=False)
    except DoctorProfile.DoesNotExist:
        pass


def _ensure_doctor_access(request):
    if request.user.is_staff or request.user.is_superuser:
        messages.error(request, 'Admin accounts can only access the admin area.')
        return False
    if request.user.role != 'doctor':
        messages.error(request, 'Only doctor accounts can access this page.')
        return False
    return True


@login_required
def profile_view(request):
    role_redirect = _ensure_user_access(request)
    if role_redirect:
        return role_redirect

    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    last_log = HealthLog.objects.filter(user=request.user).order_by('-created_at').first()
    documents = UserDocument.objects.filter(user=request.user)

    if request.method == 'POST':
        form = UserProfileForm(
            request.POST,
            request.FILES,
            instance=profile,
            user=request.user,
            last_log=last_log,
        )
        if form.is_valid():
            previous_height = last_log.height_cm if last_log else None
            previous_weight = last_log.weight_kg if last_log else None

            updated_profile = form.save()

            current_height = updated_profile.height_cm
            current_weight = updated_profile.weight_kg
            if current_height != previous_height or current_weight != previous_weight:
                HealthLog.objects.create(
                    user=request.user,
                    height_cm=current_height,
                    weight_kg=current_weight,
                )

            _create_notification(
                request.user,
                'Profile updated',
                'Your profile information has been updated.',
                'profile',
            )
            send_profile_settings_change_email(
                request.user,
                {'change_summary': 'Your profile information was updated successfully.'},
            )
            messages.success(request, 'Profile updated successfully.')
            return redirect('dashboard_profile')
    else:
        form = UserProfileForm(instance=profile, user=request.user, last_log=last_log)

    return render(
        request,
        'dashboard/profile.html',
        {
            'form': form,
            'upload_form': UserDocumentUploadForm(),
            'documents': documents,
        },
    )


@login_required
def upload_user_documents(request):
    role_redirect = _ensure_user_access(request)
    if role_redirect:
        return role_redirect

    if request.method != 'POST':
        return redirect('dashboard_profile')

    form = UserDocumentUploadForm(request.POST, request.FILES)
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    last_log = HealthLog.objects.filter(user=request.user).order_by('-created_at').first()
    profile_form = UserProfileForm(instance=profile, user=request.user, last_log=last_log)
    documents = UserDocument.objects.filter(user=request.user)

    if form.is_valid():
        uploaded_files = form.cleaned_data.get('documents', [])

        if not uploaded_files:
            messages.error(request, 'Please select at least one file to upload.')
            return redirect('dashboard_profile')

        for file_obj in uploaded_files:
            UserDocument.objects.create(
                user=request.user,
                file=file_obj,
                original_name=file_obj.name,
            )

        messages.success(request, 'Document(s) uploaded successfully.')
        return redirect('dashboard_profile')

    messages.error(request, 'Please upload valid files (PDF, JPG, JPEG, PNG).')
    return render(
        request,
        'dashboard/profile.html',
        {
            'form': profile_form,
            'upload_form': form,
            'documents': documents,
        },
    )


@login_required
def settings_view(request):
    role_redirect = _ensure_user_access(request)
    if role_redirect:
        return role_redirect

    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    two_factor_enabled = request.user.is_two_factor_enabled

    if request.method == 'POST':
        account_form = AccountSettingsForm(request.POST, instance=profile, user=request.user)
        password_form = StrongPasswordChangeForm(request.user)
        verification_form = EmailVerificationForm()
        _bootstrapize_password_form(password_form)

        if account_form.is_valid():
            new_email = account_form.cleaned_data['email'].strip().lower()
            email_changed = new_email != request.user.email

            if email_changed:
                account_form.save(update_email=False)
                try:
                    _send_email_verification_code(request, new_email)
                    _create_notification(
                        request.user,
                        'Email verification required',
                        f'A verification code was sent to {new_email}.',
                        'email',
                    )
                    messages.info(request, 'Verification code sent to your new email. Enter the code to confirm change.')
                except Exception:
                    _clear_email_verification_session(request)
                    messages.error(request, 'Unable to send verification code. Please try again.')
            else:
                account_form.save(update_email=True)
                _clear_email_verification_session(request)
                _create_notification(
                    request.user,
                    'Settings updated',
                    'Your account settings were updated.',
                    'system',
                )
                send_profile_settings_change_email(
                    request.user,
                    {'change_summary': 'Your account settings were updated successfully.'},
                )
                messages.success(request, 'Account settings updated successfully.')

            return redirect('dashboard_settings')
    else:
        account_form = AccountSettingsForm(instance=profile, user=request.user)
        password_form = StrongPasswordChangeForm(request.user)
        verification_form = EmailVerificationForm()
        _bootstrapize_password_form(password_form)

    return render(
        request,
        'dashboard/settings.html',
        {
            'account_form': account_form,
            'password_form': password_form,
            'verification_form': verification_form,
            'pending_email': request.session.get('pending_email'),
            'two_factor_enabled': two_factor_enabled,
            'requires_password_update': not request.user.is_password_strong,
        },
    )


@login_required
def verify_email_code(request):
    role_redirect = _ensure_user_access(request)
    if role_redirect:
        return role_redirect

    if request.method != 'POST':
        return redirect('dashboard_settings')

    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    account_form = AccountSettingsForm(instance=profile, user=request.user)
    password_form = StrongPasswordChangeForm(request.user)
    _bootstrapize_password_form(password_form)

    verification_form = EmailVerificationForm(request.POST)
    pending_email = request.session.get('pending_email')
    session_code = request.session.get('email_otp_code')
    created_at = request.session.get('email_otp_created_at')

    if not pending_email or not session_code or not created_at:
        messages.error(request, 'No pending email verification found. Please try updating email again.')
        return redirect('dashboard_settings')

    if verification_form.is_valid():
        if (int(time.time()) - int(created_at)) > 600:
            _clear_email_verification_session(request)
            messages.error(request, 'Verification code expired. Please request a new one.')
            return redirect('dashboard_settings')

        input_code = verification_form.cleaned_data['code']
        if input_code == session_code:
            request.user.email = pending_email
            request.user.save(update_fields=['email'])
            _clear_email_verification_session(request)
            _create_notification(
                request.user,
                'Email updated',
                'Your email address has been verified and updated.',
                'email',
            )
            send_profile_settings_change_email(
                request.user,
                {
                    'change_summary': 'Your email address was verified and updated.',
                    'changed_email': pending_email,
                },
            )
            messages.success(request, 'Email verified and updated successfully.')
            return redirect('dashboard_settings')

        messages.error(request, 'Invalid verification code. Please try again.')

    return render(
        request,
        'dashboard/settings.html',
        {
            'account_form': account_form,
            'password_form': password_form,
            'verification_form': verification_form,
            'pending_email': pending_email,
            'two_factor_enabled': request.user.is_two_factor_enabled,
            'requires_password_update': not request.user.is_password_strong,
        },
    )


@login_required
def get_notifications(request):
    notifications = Notification.objects.filter(user=request.user).order_by('-created_at')[:20]
    unread_count = Notification.objects.filter(user=request.user, is_read=False).count()

    payload = []
    for item in notifications:
        resolved_url, resolved_section = _resolve_notification_target(item)
        payload.append(
            {
                'id': item.id,
                'title': item.title,
                'message': item.message,
                'type': item.type,
                'is_read': item.is_read,
                'target_url': resolved_url,
                'target_section_id': resolved_section,
                'created_at': item.created_at.isoformat(),
                'relative_time': _relative_time(item.created_at),
            }
        )

    return JsonResponse({'notifications': payload, 'unread_count': unread_count})


@login_required
def mark_as_read(request, notification_id):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)

    notification = get_object_or_404(Notification, id=notification_id, user=request.user)
    if not notification.is_read:
        notification.is_read = True
        notification.save(update_fields=['is_read'])

    unread_count = Notification.objects.filter(user=request.user, is_read=False).count()
    return JsonResponse({'success': True, 'unread_count': unread_count})


@login_required
def mark_all_as_read(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)

    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return JsonResponse({'success': True, 'unread_count': 0})


@login_required
def delete_account(request):
    role_redirect = _ensure_user_access(request)
    if role_redirect:
        return role_redirect

    if request.method != 'POST':
        return redirect('dashboard_settings')

    user = request.user

    _delete_user_account_data(user)

    user.delete()
    auth_logout(request)
    messages.success(request, 'Your account has been deleted successfully.')
    return redirect('login')


@login_required
def doctor_settings_view(request):
    if not _ensure_doctor_access(request):
        return redirect('home')

    password_form = StrongPasswordChangeForm(request.user)
    email_form = DoctorEmailChangeRequestForm(user=request.user)
    verification_form = EmailVerificationForm()
    delete_form = DeleteAccountForm(user=request.user)
    _bootstrapize_password_form(password_form)

    return render(
        request,
        'doctor/settings.html',
        {
            'password_form': password_form,
            'email_form': email_form,
            'verification_form': verification_form,
            'delete_form': delete_form,
            'pending_email': request.session.get('doctor_pending_email'),
            'requires_password_update': not request.user.is_password_strong,
        },
    )


@login_required
def doctor_change_password(request):
    if not _ensure_doctor_access(request):
        return redirect('home')

    if request.method != 'POST':
        return redirect('doctor_settings')

    form = StrongPasswordChangeForm(request.user, request.POST)
    _bootstrapize_password_form(form)

    if form.is_valid():
        user = form.save()
        user.is_password_strong = True
        user.save(update_fields=['is_password_strong'])
        update_session_auth_hash(request, user)

        _create_notification(
            request.user,
            'Password changed',
            'Your doctor account password has been changed successfully.',
            'system',
        )
        send_profile_settings_change_email(
            request.user,
            {
                'subject': 'Doctor Account Password Changed - FemiCare',
                'change_summary': 'Your doctor account password was changed successfully.',
            },
        )
        messages.success(request, 'Password changed successfully.')
        return redirect('doctor_settings')

    messages.error(request, 'Please fix the password form errors and try again.')
    return render(
        request,
        'doctor/settings.html',
        {
            'password_form': form,
            'email_form': DoctorEmailChangeRequestForm(user=request.user),
            'verification_form': EmailVerificationForm(),
            'delete_form': DeleteAccountForm(user=request.user),
            'pending_email': request.session.get('doctor_pending_email'),
            'requires_password_update': not request.user.is_password_strong,
        },
    )


@login_required
def doctor_change_email(request):
    if not _ensure_doctor_access(request):
        return redirect('home')

    if request.method != 'POST':
        return redirect('doctor_settings')

    form = DoctorEmailChangeRequestForm(request.POST, user=request.user)
    _bootstrapize_password_form(StrongPasswordChangeForm(request.user))

    if form.is_valid():
        new_email = form.cleaned_data['email']
        try:
            _send_email_verification_code(
                request,
                new_email,
                pending_key='doctor_pending_email',
                code_key='doctor_email_otp_code',
                created_key='doctor_email_otp_created_at',
                action_url_name='doctor_settings',
            )
            _create_notification(
                request.user,
                'Email verification required',
                f'A verification code was sent to {new_email}.',
                'email',
            )
            messages.info(request, 'Verification code sent to your new email. Enter the code to confirm change.')
            return redirect('doctor_settings')
        except Exception:
            _clear_email_verification_session(
                request,
                pending_key='doctor_pending_email',
                code_key='doctor_email_otp_code',
                created_key='doctor_email_otp_created_at',
            )
            messages.error(request, 'Unable to send verification code. Please try again.')
            return redirect('doctor_settings')

    messages.error(request, 'Please fix the email form errors and try again.')
    password_form = StrongPasswordChangeForm(request.user)
    _bootstrapize_password_form(password_form)
    return render(
        request,
        'doctor/settings.html',
        {
            'password_form': password_form,
            'email_form': form,
            'verification_form': EmailVerificationForm(),
            'delete_form': DeleteAccountForm(user=request.user),
            'pending_email': request.session.get('doctor_pending_email'),
            'requires_password_update': not request.user.is_password_strong,
        },
    )


@login_required
def doctor_verify_email_code(request):
    if not _ensure_doctor_access(request):
        return redirect('home')

    if request.method != 'POST':
        return redirect('doctor_settings')

    verification_form = EmailVerificationForm(request.POST)
    pending_email = request.session.get('doctor_pending_email')
    session_code = request.session.get('doctor_email_otp_code')
    created_at = request.session.get('doctor_email_otp_created_at')

    if not pending_email or not session_code or not created_at:
        messages.error(request, 'No pending email verification found. Please try updating email again.')
        return redirect('doctor_settings')

    if verification_form.is_valid():
        if (int(time.time()) - int(created_at)) > 600:
            _clear_email_verification_session(
                request,
                pending_key='doctor_pending_email',
                code_key='doctor_email_otp_code',
                created_key='doctor_email_otp_created_at',
            )
            messages.error(request, 'Verification code expired. Please request a new one.')
            return redirect('doctor_settings')

        input_code = verification_form.cleaned_data['code']
        if input_code == session_code:
            request.user.email = pending_email
            request.user.save(update_fields=['email'])
            _clear_email_verification_session(
                request,
                pending_key='doctor_pending_email',
                code_key='doctor_email_otp_code',
                created_key='doctor_email_otp_created_at',
            )
            _create_notification(
                request.user,
                'Email updated',
                'Your doctor account email address has been verified and updated.',
                'email',
            )
            send_profile_settings_change_email(
                request.user,
                {
                    'subject': 'Doctor Account Email Updated - FemiCare',
                    'change_summary': 'Your doctor account email was verified and updated.',
                    'changed_email': pending_email,
                },
            )
            messages.success(request, 'Email verified and updated successfully.')
            return redirect('doctor_settings')

        messages.error(request, 'Invalid verification code. Please try again.')

    password_form = StrongPasswordChangeForm(request.user)
    _bootstrapize_password_form(password_form)

    return render(
        request,
        'doctor/settings.html',
        {
            'password_form': password_form,
            'email_form': DoctorEmailChangeRequestForm(user=request.user),
            'verification_form': verification_form,
            'delete_form': DeleteAccountForm(user=request.user),
            'pending_email': pending_email,
            'requires_password_update': not request.user.is_password_strong,
        },
    )


@login_required
def doctor_delete_account(request):
    if not _ensure_doctor_access(request):
        return redirect('home')

    if request.method != 'POST':
        return redirect('doctor_settings')

    form = DeleteAccountForm(request.POST, user=request.user)
    if not form.is_valid():
        messages.error(request, 'Please complete deletion confirmation correctly.')
        password_form = StrongPasswordChangeForm(request.user)
        _bootstrapize_password_form(password_form)
        return render(
            request,
            'doctor/settings.html',
            {
                'password_form': password_form,
                'email_form': DoctorEmailChangeRequestForm(user=request.user),
                'verification_form': EmailVerificationForm(),
                'delete_form': form,
                'pending_email': request.session.get('doctor_pending_email'),
                'requires_password_update': not request.user.is_password_strong,
            },
        )

    account_email = request.user.email
    _create_notification(
        request.user,
        'Account deletion requested',
        'Your doctor account is being deleted as requested.',
        'system',
    )

    if account_email:
        send_notification_template_email(
            request.user,
            'Your doctor account deletion request has been processed. This action cannot be undone.',
            {
                'notification_title': 'Doctor Account Deleted',
                'subject': 'Doctor Account Deletion Confirmation - FemiCare',
            },
        )

    user = request.user
    _delete_user_account_data(user)
    user.delete()
    auth_logout(request)
    messages.success(request, 'Your doctor account has been deleted permanently.')
    return redirect('login')


@login_required
def change_password(request):
    role_redirect = _ensure_user_access(request)
    if role_redirect:
        return role_redirect

    if request.method != 'POST':
        return redirect('dashboard_settings')

    form = StrongPasswordChangeForm(request.user, request.POST)
    _bootstrapize_password_form(form)
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    account_form = AccountSettingsForm(instance=profile, user=request.user)

    if form.is_valid():
        user = form.save()
        user.is_password_strong = True
        user.save(update_fields=['is_password_strong'])

        Notification.objects.filter(
            user=request.user,
            title='Security Update Required',
            is_read=False,
        ).update(is_read=True)

        update_session_auth_hash(request, user)
        _create_notification(
            request.user,
            'Password changed',
            'Your password has been changed successfully.',
            'system',
        )
        messages.success(request, 'Password changed successfully.')
        return redirect('dashboard_settings')

    messages.error(request, 'Please fix the password form errors and try again.')
    return render(
        request,
        'dashboard/settings.html',
        {
            'account_form': account_form,
            'password_form': form,
            'verification_form': EmailVerificationForm(),
            'pending_email': request.session.get('pending_email'),
            'two_factor_enabled': request.user.is_two_factor_enabled,
            'requires_password_update': not request.user.is_password_strong,
        },
    )

@login_required
def dashboard_home(request):
    role_redirect = _ensure_user_access(request)
    if role_redirect:
        return role_redirect

    _ensure_password_security_notice(request.user)

    logs = CycleLog.objects.filter(user=request.user)
    latest_cycle = logs.first()
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    today = timezone.localdate()
    current_hour = timezone.localtime().hour

    if current_hour < 12:
        greeting_prefix = "Good Morning"
    elif current_hour < 18:
        greeting_prefix = "Good Afternoon"
    else:
        greeting_prefix = "Good Evening"

    today_mood_entry = MoodEntry.objects.filter(user=request.user, date=today).first()
    today_mood_label = today_mood_entry.get_mood_display() if today_mood_entry else None
    show_mood_prompt = today_mood_entry is None

    greeting_text = (
        f"{greeting_prefix}, you are feeling {today_mood_label} today"
        if today_mood_label else
        f"{greeting_prefix}, tell us how you are feeling today"
    )

    mood_counts = dict(
        MoodEntry.objects.filter(user=request.user)
        .values('mood')
        .annotate(total=Count('id'))
        .values_list('mood', 'total')
    )
    mood_chart_labels = [label for _, label in MoodEntry.MOOD_CHOICES]
    mood_chart_values = [mood_counts.get(code, 0) for code, _ in MoodEntry.MOOD_CHOICES]

    cycle_log_qs = CycleLog.objects.filter(user=request.user)

    symptom_frequency = list(
        SymptomLog.objects.filter(user=request.user, source__in=['manual', 'first_login'])
        .values('symptom')
        .annotate(count=Count('id'))
        .order_by('-count', 'symptom')[:10]
    )
    max_symptom_frequency = symptom_frequency[0]['count'] if symptom_frequency else 1

    recent_cycle_symptoms = list(
        SymptomLog.objects.filter(user=request.user, source__in=['manual', 'first_login'])
        .values('symptom', 'date')
        .order_by('-date', '-created_at')[:8]
    )

    most_common_symptom = symptom_frequency[0]['symptom'] if symptom_frequency else 'No Data Yet'

    today_symptoms_qs = SymptomLog.objects.filter(user=request.user, date=today).order_by('created_at')
    selected_today_symptoms = list(today_symptoms_qs.values_list('symptom', flat=True))

    recent_symptoms = list(
        SymptomLog.objects.filter(user=request.user, source__in=['manual', 'first_login'])
        .order_by('-created_at')
        .values_list('symptom', flat=True)[:5]
    )

    appointments_count = Appointment.objects.filter(user=request.user).count()

    height_cm = profile.height_cm
    weight_kg = profile.weight_kg

    if height_cm is None and latest_cycle:
        height_cm = latest_cycle.height_cm
    if weight_kg is None and latest_cycle:
        weight_kg = latest_cycle.weight_kg

    bmi = None
    if height_cm and weight_kg:
        try:
            height_m = float(height_cm) / 100
            if height_m > 0:
                bmi = round(float(weight_kg) / (height_m ** 2), 1)
        except (TypeError, ValueError, ZeroDivisionError):
            bmi = None

    cycle_logs = list(logs.exclude(last_period_start__isnull=True).order_by('last_period_start'))
    cycle_lengths = [log.length_of_cycle for log in cycle_logs if log.length_of_cycle]
    menses_lengths = [log.length_of_menses for log in cycle_logs if log.length_of_menses]

    avg_cycle_length = None
    if cycle_lengths:
        avg_cycle_length = round(sum(cycle_lengths) / len(cycle_lengths), 1)

    avg_menses_length = None
    if menses_lengths:
        avg_menses_length = round(sum(menses_lengths) / len(menses_lengths), 1)

    phase_labels = ['Menstrual', 'Follicular', 'Ovulation', 'Luteal']
    phase_values = [25, 35, 10, 30]
    cycle_days = int(round(avg_cycle_length)) if avg_cycle_length else None
    menstrual_days = int(round(avg_menses_length)) if avg_menses_length else 5

    if cycle_days and cycle_days > 0:
        menstrual_days = max(2, min(menstrual_days, max(cycle_days - 3, 2)))
        ovulation_days = 1
        luteal_days = 14 if cycle_days >= 24 else max(8, cycle_days // 3)
        remaining_days = cycle_days - menstrual_days - ovulation_days

        if remaining_days > 1:
            luteal_days = min(luteal_days, remaining_days - 1)
            follicular_days = remaining_days - luteal_days
            if follicular_days < 1:
                follicular_days = 1
                luteal_days = max(1, remaining_days - 1)

            raw_percentages = [
                (menstrual_days / cycle_days) * 100,
                (follicular_days / cycle_days) * 100,
                (ovulation_days / cycle_days) * 100,
                (luteal_days / cycle_days) * 100,
            ]
            phase_values = [int(round(value)) for value in raw_percentages]
            rounding_diff = 100 - sum(phase_values)
            phase_values[1] += rounding_diff

    last_30_start = today - timedelta(days=29)
    recent_mood_entries = list(
        MoodEntry.objects.filter(user=request.user, date__gte=last_30_start)
        .order_by('date')
        .values_list('mood', flat=True)
    )

    mood_trend_buckets = {
        'happy': {'label': 'Happy', 'emoji': '😊', 'codes': {'happy', 'calm', 'energetic'}},
        'neutral': {'label': 'Neutral', 'emoji': '😐', 'codes': {'stressed'}},
        'sad': {'label': 'Sad', 'emoji': '😔', 'codes': {'sad', 'irritated'}},
    }

    mood_trend_points = {'happy': 0, 'neutral': 0, 'sad': 0}
    for mood_code in recent_mood_entries:
        for key, bucket in mood_trend_buckets.items():
            if mood_code in bucket['codes']:
                mood_trend_points[key] += 1
                break

    mood_score_map = {
        'energetic': 3,
        'happy': 3,
        'calm': 2,
        'stressed': 1,
        'irritated': 0,
        'sad': 0,
    }
    mood_scores = [mood_score_map.get(code, 1) for code in recent_mood_entries]
    mood_split = len(mood_scores) // 2
    first_half_avg = sum(mood_scores[:mood_split]) / mood_split if mood_split else None
    second_half_len = len(mood_scores) - mood_split
    second_half_avg = sum(mood_scores[mood_split:]) / second_half_len if second_half_len else None

    if not recent_mood_entries:
        mood_trend_summary = 'No mood check-ins in the last 30 days.'
    else:
        most_common_mood_code = max(
            mood_counts,
            key=mood_counts.get,
            default='irritated'
        )
        mood_label_map = dict(MoodEntry.MOOD_CHOICES)
        most_common_mood_label = mood_label_map.get(most_common_mood_code, 'Unknown')

        if first_half_avg is not None and second_half_avg is not None and second_half_avg > first_half_avg:
            mood_trend_summary = f'Most common mood: {most_common_mood_label}. Mood improved in the second half of the cycle.'
        elif first_half_avg is not None and second_half_avg is not None and second_half_avg < first_half_avg:
            mood_trend_summary = f'Most common mood: {most_common_mood_label}. Mood dipped in the second half of the cycle.'
        else:
            mood_trend_summary = f'Most common mood: {most_common_mood_label}.'

    mood_trend_tip = 'Mood swings are normal during luteal phase.'
    mood_trend_max = max(mood_trend_points.values()) if any(mood_trend_points.values()) else 1

    last_period_date = cycle_logs[-1].last_period_start if cycle_logs else None

    cycle_length_days = _to_positive_int(avg_cycle_length)
    if not cycle_length_days and latest_cycle:
        cycle_length_days = _to_positive_int(latest_cycle.length_of_cycle)
    if not cycle_length_days:
        cycle_length_days = 28

    menses_length_days = _to_positive_int(avg_menses_length)
    if not menses_length_days and latest_cycle:
        menses_length_days = _to_positive_int(latest_cycle.length_of_menses)
    if not menses_length_days:
        menses_length_days = 5

    predicted_cycle_starts = _generate_rolling_prediction_starts(
        last_period_date,
        cycle_length_days,
        today,
        count=3,
    )

    predicted_period_ranges = [
        _serialize_period_range(start_date, menses_length_days, 'predicted', 'Predicted period')
        for start_date in predicted_cycle_starts
    ]
    predicted_period_ranges = [item for item in predicted_period_ranges if item]

    actual_period_ranges = _build_logged_period_ranges(cycle_logs[-24:], menses_length_days)

    predicted_next_period = predicted_cycle_starts[0] if predicted_cycle_starts else None
    if not predicted_next_period and latest_cycle and latest_cycle.predicted_next_period:
        predicted_next_period = latest_cycle.predicted_next_period
    if not predicted_next_period and last_period_date and cycle_length_days:
        predicted_next_period = last_period_date + timedelta(days=cycle_length_days)

    trigger_period_day_reminder(request.user, predicted_next_period)

    active_period = _get_active_period(request.user)
    active_cycle = cycle_log_qs.exclude(last_period_start__isnull=True).filter(last_period_start__lte=today).order_by('-last_period_start').first()
    is_on_period = False
    show_period_checkin_prompt = False
    current_period_range = None

    if active_period:
        period_start = active_period.start_date or active_period.actual_start_date or active_period.last_period_start
        period_end = active_period.end_date or active_period.expected_end_date
        if period_start:
            is_on_period = period_start <= today and (period_end is None or today <= period_end)
            current_period_range = _serialize_period_range(
                period_start,
                (active_period.length_of_menses or 5),
                'current',
                'Current period',
            )
        if active_cycle and is_on_period:
            show_period_checkin_prompt = not PeriodCheckIn.objects.filter(user=request.user, cycle_log=active_cycle).exists()
    elif active_cycle and active_cycle.length_of_menses:
        period_end = active_cycle.last_period_start + timedelta(days=max(active_cycle.length_of_menses, 1) - 1)
        is_on_period = active_cycle.last_period_start <= today <= period_end
        if is_on_period:
            show_period_checkin_prompt = not PeriodCheckIn.objects.filter(user=request.user, cycle_log=active_cycle).exists()
            current_period_range = _serialize_period_range(
                active_cycle.last_period_start,
                active_cycle.length_of_menses,
                'current',
                'Current period',
            )

    if show_period_checkin_prompt:
        show_mood_prompt = False

    period_status_text = "No active cycle today"
    period_status_variant = "neutral"
    if is_on_period and (active_period or active_cycle):
        period_status_text = "You are on your period today"
        period_status_variant = "active"
    elif last_period_date and latest_cycle and latest_cycle.length_of_menses:
        bleeding_end = last_period_date + timedelta(days=max(latest_cycle.length_of_menses, 1) - 1)
        if last_period_date <= today <= bleeding_end:
            period_status_text = "You are on your period today"
            period_status_variant = "active"
        elif predicted_next_period:
            days_until_period = (predicted_next_period - today).days
            if 0 <= days_until_period <= 7:
                period_status_text = f"Your period is expected in {days_until_period} day(s)"
                period_status_variant = "upcoming"
            elif days_until_period < 0:
                period_status_text = f"Your period was expected {abs(days_until_period)} day(s) ago"
                period_status_variant = "upcoming"
    elif predicted_next_period:
        days_until_period = (predicted_next_period - today).days
        if 0 <= days_until_period <= 7:
            period_status_text = f"Your period is expected in {days_until_period} day(s)"
            period_status_variant = "upcoming"

    cycle_is_irregular = None
    cycle_spread = None
    if len(cycle_lengths) >= 3:
        cycle_spread = max(cycle_lengths) - min(cycle_lengths)
        cycle_is_irregular = cycle_spread > 7
    elif len(cycle_lengths) >= 1:
        cycle_is_irregular = False

    cycle_pattern_short = "No Data"
    cycle_pattern_value = "No Data Yet"
    cycle_pattern_helper = "Start logging your cycle to understand your monthly pattern."
    if cycle_lengths:
        if cycle_spread is None or cycle_spread <= 3:
            cycle_pattern_short = "Regular"
            cycle_pattern_value = "Regular"
            cycle_pattern_helper = "Your cycle is mostly consistent from month to month."
        elif cycle_spread <= 7:
            cycle_pattern_short = "Slightly Irregular"
            cycle_pattern_value = "Slightly Irregular"
            cycle_pattern_helper = "Your cycle is mostly consistent with minor variations."
        else:
            cycle_pattern_short = "Irregular"
            cycle_pattern_value = "Irregular"
            cycle_pattern_helper = "Your cycle varies more than usual. Keep tracking and monitor changes."

    menstrual_insights = []
    if not cycle_lengths:
        menstrual_insights.append(
            "Start tracking your cycle to receive personalized menstrual insights."
        )
    elif cycle_is_irregular:
        menstrual_insights.append(
            "Your cycle appears irregular. Consider consulting a doctor for guidance."
        )
    else:
        menstrual_insights.append("Your cycle appears regular and stable.")

    symptom_insights = []
    if not cycle_logs:
        symptom_insights.append("Track your symptoms to get deeper health insights.")
    else:
        high_cramp_logs = sum(1 for log in cycle_logs if (log.total_menses_score or 0) >= 6)
        heavy_bleeding_logs = sum(1 for log in cycle_logs if log.mean_bleeding_intensity == 3)
        unusual_bleeding_logs = sum(1 for log in cycle_logs if log.unusual_bleeding)
        score_variation = len({log.total_menses_score for log in cycle_logs if log.total_menses_score is not None}) > 1

        if high_cramp_logs >= 2:
            symptom_insights.append(
                "You have reported frequent cramps. Monitoring intensity or consulting a doctor is recommended."
            )
        if heavy_bleeding_logs >= 2 or unusual_bleeding_logs >= 1:
            symptom_insights.append(
                "Bleeding pattern changes detected. Keep tracking and discuss persistent changes with a clinician."
            )
        if score_variation:
            symptom_insights.append("Mood variations detected during cycle phases.")

        if not symptom_insights:
            symptom_insights.append("Symptoms appear stable based on your recent cycle logs.")

    bmi_insight = "Add height and weight details for BMI-based menstrual guidance."
    if bmi is not None:
        if bmi < 18.5:
            bmi_insight = "Low body weight may affect menstrual consistency."
        elif bmi > 24.9:
            bmi_insight = "Body weight can impact hormonal balance and cycle regularity."
        else:
            bmi_insight = "Your BMI is within a healthy range, supporting stable cycles."

    personalized_insights = [
        {
            "title": "Cycle Regularity",
            "message": menstrual_insights[0],
        },
        {
            "title": "Symptom Pattern",
            "message": symptom_insights[0],
        },
        {
            "title": "Health Recommendation",
            "message": "Continue consistent cycle and symptom tracking to improve menstrual health predictions.",
        },
    ]

    trend_logs = cycle_logs[-8:]
    cycle_trend_labels = [log.last_period_start.strftime("%b %d") for log in trend_logs]
    cycle_trend_values = [log.length_of_cycle for log in trend_logs]

    cycle_label = "insufficient data"
    if cycle_lengths:
        cycle_label = "irregular" if cycle_is_irregular else "regular"

    bmi_summary = "BMI data is currently incomplete"
    body_health_value = "No Data Yet"
    body_health_helper = "Update your profile height and weight to get personalized body health status."
    if bmi is not None:
        if bmi < 18.5:
            bmi_summary = "your BMI is on the lower side"
            body_health_value = "Underweight"
            body_health_helper = "Your BMI suggests lower weight than recommended for your height."
        elif bmi > 24.9:
            bmi_summary = "your BMI is above the healthy range"
            body_health_value = "Overweight"
            body_health_helper = "Your BMI suggests a slightly higher weight than recommended."
        else:
            bmi_summary = "your BMI is within a healthy range"
            body_health_value = "Healthy"
            body_health_helper = "Your BMI is in a healthy range for your height."

    symptom_summary = (
        "symptom patterns are limited"
        if symptom_insights and "Track your symptoms" in symptom_insights[0]
        else "symptom tracking indicates useful menstrual trends"
    )

    health_summary_text = (
        f"Based on your menstrual and health data, your cycle appears {cycle_label}, "
        f"{bmi_summary}, and {symptom_summary}. Maintaining consistent tracking and consulting "
        "healthcare professionals can help improve reproductive health."
    )

    feedback_target = None
    feedback_map = {
        item['cycle_log_id']: item['actual_date']
        for item in PredictionFeedback.objects.filter(user=request.user, cycle_log__isnull=False)
        .values('cycle_log_id', 'actual_date')
    }
    for log in logs.exclude(predicted_next_period__isnull=True).order_by('-predicted_next_period'):
        predicted_date = _resolve_prediction_date(log)
        if not predicted_date or predicted_date > today:
            continue

        if log.start_date or log.actual_start_date:
            continue

        feedback_actual_date = feedback_map.get(log.id)
        if feedback_actual_date is None:
            feedback_target = log
            break

    emergency_assessment = trigger_emergency_alert(request.user)
    check_period_delay(request.user)
    active_emergency_request = EmergencyRequest.objects.filter(
        user=request.user,
        status__in=['pending', 'assigned'],
    ).first()

    feedback_stats = PredictionFeedback.objects.filter(user=request.user)
    total_feedback = feedback_stats.count()
    correct_feedback = feedback_stats.filter(is_correct=True).count()
    prediction_accuracy = round((correct_feedback / total_feedback) * 100, 1) if total_feedback else 0

    # 👇 ONE-TIME session trigger (KEEP THIS)
    show_prediction = request.session.pop("show_prediction", False)
    last_cycle_id = request.session.pop("last_cycle_id", None)

    cycle = latest_cycle
    if last_cycle_id:
        cycle = CycleLog.objects.filter(
            id=last_cycle_id,
            user=request.user
        ).first()

    return render(request, "dashboard/first.html", {
        # ✅ ONLY CHANGE IS HERE
        "form": CycleLogForm(user=request.user),
        "period_log_form": PeriodLogForm(),
        "end_period_form": EndPeriodForm(start_date=(active_period.start_date if active_period else None)),

        "logs": logs,
        "cycle": cycle,
        "show_prediction": show_prediction,
        "height_cm": height_cm,
        "weight_kg": weight_kg,
        "bmi": bmi,
        "appointments_count": appointments_count,
        "avg_cycle_length": avg_cycle_length,
        "last_period_date": last_period_date,
        "predicted_next_period": predicted_next_period,
        "menstrual_insights": menstrual_insights,
        "symptom_insights": symptom_insights,
        "bmi_insight": bmi_insight,
        "personalized_insights": personalized_insights,
        "cycle_trend_labels": cycle_trend_labels,
        "cycle_trend_values": cycle_trend_values,
        "health_summary_text": health_summary_text,
        "greeting_text": greeting_text,
        "today_mood_label": today_mood_label,
        "show_mood_prompt": show_mood_prompt,
        "show_period_checkin_prompt": show_period_checkin_prompt,
        "active_cycle_id": active_cycle.id if active_cycle else None,
        "mood_chart_labels": mood_chart_labels,
        "mood_chart_values": mood_chart_values,
        "phase_labels": phase_labels,
        "phase_values": phase_values,
        "symptom_frequency": symptom_frequency,
        "max_symptom_frequency": max_symptom_frequency,
        "recent_cycle_symptoms": recent_cycle_symptoms,
        "most_common_symptom": most_common_symptom,
        "mood_trend_points": mood_trend_points,
        "mood_trend_max": mood_trend_max,
        "mood_trend_summary": mood_trend_summary,
        "mood_trend_tip": mood_trend_tip,
        "period_status_text": period_status_text,
        "period_status_variant": period_status_variant,
        "feedback_target": feedback_target,
        "active_period": active_period,
        "is_active_period": is_period_active(request.user),
        "prediction_accuracy": prediction_accuracy,
        "total_feedback": total_feedback,
        "cycle_pattern_short": cycle_pattern_short,
        "cycle_pattern_value": cycle_pattern_value,
        "cycle_pattern_helper": cycle_pattern_helper,
        "body_health_value": body_health_value,
        "body_health_helper": body_health_helper,
        "symptom_options": SYMPTOM_OPTIONS,
        "selected_today_symptoms": selected_today_symptoms,
        "recent_symptoms": recent_symptoms,
        "calendar_actual_ranges": actual_period_ranges,
        "calendar_predicted_ranges": predicted_period_ranges,
        "calendar_current_period_range": current_period_range,
        "predicted_cycle_starts": [start.isoformat() for start in predicted_cycle_starts],
        "show_emergency_panel": emergency_assessment.get('level') == 'high',
        "emergency_alert_level": emergency_assessment.get('level'),
        "emergency_risk_score": emergency_assessment.get('score', 0),
        "emergency_alert_message": EMERGENCY_ALERT_MESSAGE,
        "emergency_repeated_symptoms": emergency_assessment.get('repeated_symptoms', []),
        "active_emergency_request": active_emergency_request,
    })


@login_required
def submit_mood_checkin(request):
    role_redirect = _ensure_user_access(request)
    if role_redirect:
        return role_redirect

    if request.method != 'POST':
        return redirect('dashboard_home')

    mood_value = request.POST.get('mood', '').strip().lower()
    allowed_moods = {choice[0] for choice in MoodEntry.MOOD_CHOICES}

    if mood_value not in allowed_moods:
        messages.error(request, 'Please choose a valid mood option.')
        return redirect('dashboard_home')

    MoodEntry.objects.update_or_create(
        user=request.user,
        date=timezone.localdate(),
        defaults={'mood': mood_value}
    )

    messages.success(request, 'Mood check-in saved for today.')
    return redirect('dashboard_home')


@login_required
def submit_prediction_feedback(request):
    role_redirect = _ensure_user_access(request)
    if role_redirect:
        return role_redirect

    if request.method != 'POST':
        return redirect('dashboard_home')

    cycle_log_id = request.POST.get('cycle_log_id')
    response = (request.POST.get('feedback_status') or '').strip().lower()
    legacy_response = (request.POST.get('is_correct') or '').strip().lower()
    actual_date_raw = request.POST.get('actual_date')

    if not response and legacy_response in {'yes', 'no'}:
        response = 'yes' if legacy_response == 'yes' else 'started_earlier'

    valid_responses = {'yes', 'started_earlier', 'still_not_started', 'started_today'}
    if not cycle_log_id or response not in valid_responses:
        messages.error(request, 'Invalid feedback submission.')
        return redirect('dashboard_home')

    cycle_log = get_object_or_404(CycleLog, id=cycle_log_id, user=request.user)
    predicted_date = _resolve_prediction_date(cycle_log)
    if not predicted_date:
        messages.error(request, 'This prediction does not have a valid predicted date.')
        return redirect('dashboard_home')

    today = timezone.localdate()
    parsed_actual_date = parse_date(actual_date_raw or '')

    if response == 'yes':
        actual_date = predicted_date
    elif response == 'started_today':
        actual_date = today
    elif response == 'started_earlier':
        actual_date = parsed_actual_date
        if not actual_date:
            messages.error(request, 'Please select when your period started.')
            return redirect('dashboard_home')
        if actual_date >= predicted_date:
            messages.error(request, 'For "Started earlier", choose a date before the predicted day.')
            return redirect('dashboard_home')
    else:
        actual_date = None

    if actual_date and actual_date > today:
        messages.error(request, 'You cannot select a future period start date.')
        return redirect('dashboard_home')

    is_correct = actual_date == predicted_date if actual_date else False

    PredictionFeedback.objects.update_or_create(
        user=request.user,
        cycle_log=cycle_log,
        defaults={
            'predicted_date': predicted_date,
            'actual_date': actual_date,
            'is_correct': is_correct,
        }
    )

    if actual_date:
        try:
            create_period(request.user, actual_date)
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect('dashboard_home')
        cycle_log.start_date = actual_date
        cycle_log.actual_start_date = actual_date
        cycle_log.expected_end_date = actual_date + timedelta(days=5)
        cycle_log.end_date = None
        cycle_log.is_confirmed = True
        cycle_log.save(update_fields=['start_date', 'actual_start_date', 'expected_end_date', 'end_date', 'is_confirmed'])
        update_cycle_prediction(request.user)
        messages.success(request, 'Period start confirmed and cycle prediction updated.')
        return redirect('dashboard_home')

    cycle_log.actual_start_date = None
    cycle_log.start_date = None
    cycle_log.end_date = None
    cycle_log.is_confirmed = False
    cycle_log.save(update_fields=['actual_start_date', 'start_date', 'end_date', 'is_confirmed'])
    handle_delayed_period(request.user)
    messages.info(request, 'We will keep tracking and remind you daily until your period starts.')
    return redirect('dashboard_home')


@login_required
def log_period_start_view(request):
    role_redirect = _ensure_user_access(request)
    if role_redirect:
        return role_redirect

    if request.method != 'POST':
        return redirect('dashboard_home')

    form = PeriodLogForm(request.POST)
    if not form.is_valid():
        for field_errors in form.errors.values():
            for err in field_errors:
                messages.error(request, err)
        return redirect('dashboard_home')

    start_date = form.cleaned_data['start_date']
    end_date = form.cleaned_data.get('end_date')

    try:
        cycle = create_period(request.user, start_date, end_date=end_date)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect('dashboard_home')

    if cycle:
        _create_notification(
            request.user,
            'Period start logged',
            f'Period start date {start_date:%b %d, %Y} has been saved and predictions updated.',
            'cycle',
        )

    if end_date:
        messages.success(request, 'Past period logged successfully.')
    else:
        messages.success(request, 'Period start logged. Your period is currently ongoing.')
    return redirect('dashboard_home')


@login_required
def end_period_view(request):
    role_redirect = _ensure_user_access(request)
    if role_redirect:
        return role_redirect

    if request.method != 'POST':
        return redirect('dashboard_home')

    active_period = _get_active_period(request.user)
    if not active_period:
        messages.error(request, 'No active period found.')
        return redirect('dashboard_home')

    start_date = active_period.start_date or active_period.actual_start_date or active_period.last_period_start
    form = EndPeriodForm(request.POST, start_date=start_date)
    if not form.is_valid():
        for field_errors in form.errors.values():
            for err in field_errors:
                messages.error(request, err)
        return redirect('dashboard_home')

    try:
        ended = end_period(request.user, form.cleaned_data['end_date'])
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect('dashboard_home')

    _create_notification(
        request.user,
        'Period completed',
        f'Your period ending on {ended.end_date:%b %d, %Y} was recorded successfully.',
        'cycle',
    )
    messages.success(request, 'Period ended successfully.')
    return redirect('dashboard_home')


@login_required
def submit_period_checkin(request):
    role_redirect = _ensure_user_access(request)
    if role_redirect:
        return role_redirect

    if request.method != 'POST':
        return redirect('dashboard_home')

    cycle_log_id = request.POST.get('cycle_log_id')
    pain_level = request.POST.get('pain_level', '').strip().lower()
    blood_flow = request.POST.get('blood_flow', '').strip().lower()
    selected_symptoms = [value.strip() for value in request.POST.getlist('symptoms') if value.strip()]

    cycle_log = get_object_or_404(CycleLog, id=cycle_log_id, user=request.user)

    valid_pain_levels = {choice[0] for choice in PeriodCheckIn.PAIN_LEVEL_CHOICES}
    valid_blood_flows = {choice[0] for choice in PeriodCheckIn.BLOOD_FLOW_CHOICES}
    valid_symptoms = set(SYMPTOM_OPTIONS)

    if pain_level not in valid_pain_levels or blood_flow not in valid_blood_flows:
        messages.error(request, 'Please complete pain level and blood flow.')
        return redirect('dashboard_home')

    selected_symptoms = [symptom for symptom in selected_symptoms if symptom in valid_symptoms]

    checkin, created = PeriodCheckIn.objects.get_or_create(
        user=request.user,
        cycle_log=cycle_log,
        defaults={
            'pain_level': pain_level,
            'blood_flow': blood_flow,
        },
    )

    if not created:
        messages.info(request, 'You already submitted this cycle check-in.')
        return redirect('dashboard_home')

    SymptomLog.objects.bulk_create(
        [
            SymptomLog(
                user=request.user,
                cycle_log=cycle_log,
                symptom=symptom,
                source='first_login',
                date=timezone.localdate(),
            )
            for symptom in selected_symptoms
        ]
    )

    emergency_assessment = trigger_emergency_alert(request.user)
    check_period_delay(request.user)

    if emergency_assessment.get('level') == 'high' and emergency_assessment.get('triggered'):
        messages.warning(request, 'Emergency health alert has been triggered. Please review resources and consult a doctor if needed.')
    elif emergency_assessment.get('level') == 'medium' and emergency_assessment.get('triggered'):
        messages.info(request, 'A health warning was added based on your latest symptom pattern.')

    messages.success(request, 'Period check-in saved successfully.')
    return redirect('dashboard_home')


@login_required
def save_symptoms(request):
    role_redirect = _ensure_user_access(request)
    if role_redirect:
        return role_redirect

    if request.method != 'POST':
        return redirect('dashboard_home')

    selected_symptoms = [value.strip() for value in request.POST.getlist('symptoms') if value.strip()]
    valid_values = set(SYMPTOM_OPTIONS)
    selected_symptoms = [value for value in selected_symptoms if value in valid_values]

    today = timezone.localdate()
    active_cycle = _get_active_cycle_for_symptoms(request.user, today)

    # Add-only behavior keeps historical frequency stable even if UI selections are toggled off later.
    for symptom in dict.fromkeys(selected_symptoms):
        symptom_log, created = SymptomLog.objects.get_or_create(
            user=request.user,
            symptom=symptom,
            date=today,
            defaults={
                'cycle_log': active_cycle,
                'source': 'manual',
            },
        )

        if not created and symptom_log.cycle_log_id is None and active_cycle:
            symptom_log.cycle_log = active_cycle
            symptom_log.save(update_fields=['cycle_log'])

    emergency_assessment = trigger_emergency_alert(request.user)
    check_period_delay(request.user)

    if emergency_assessment.get('level') == 'high' and emergency_assessment.get('triggered'):
        messages.warning(request, 'Emergency health alert has been triggered. Please review resources and consult a doctor if needed.')
    elif emergency_assessment.get('level') == 'medium' and emergency_assessment.get('triggered'):
        messages.info(request, 'A health warning was added based on your latest symptom pattern.')

    messages.success(request, 'Symptoms saved successfully.')
    return redirect('dashboard_home')

@login_required
def appointment(request):
    role_redirect = _ensure_user_access(request)
    if role_redirect:
        return role_redirect

    today = timezone.now().date()
    
    # Sort by date and time so the earliest is always first
    all_appts = Appointment.objects.filter(user=request.user).select_related(
        'doctor__doctor_profile', 'availability'
    ).order_by('availability__date', 'availability__start_time')

    upcoming = []
    past = []

    for appt in all_appts:
        if appt.availability.date < today:
            appt.display_status = "Completed" if appt.status in ['upcoming', 'completed'] else "Missed"
            appt.status_color = "secondary"
            past.append(appt)
        else:
            status_labels = {
                'pending': 'Pending Approval',
                'awaiting_payment': 'Awaiting Payment',
                'payment_verification': 'Payment Verification',
                'upcoming': 'Upcoming Consultation',
                'completed': 'Completed',
                'rejected': 'Rejected',
            }
            appt.display_status = status_labels.get(appt.status, appt.status.capitalize())
            appt.status_color = "success" if appt.status in ['upcoming', 'completed'] else "warning"
            upcoming.append(appt)

    # The absolute next thing the user needs to do
    next_session = upcoming[0] if upcoming else None
    
    # For the 'Upcoming' list, we want to group by doctor, 
    # but we need to exclude the next_session so it's not duplicated
    other_upcoming = upcoming[1:] if upcoming else []

    return render(request, "dashboard/appointment.html", {
        "next_session": next_session,
        "other_upcoming": other_upcoming,
        "past": past,
        "today": today
    })

@login_required
def doctor_dashboard(request):
    if not _ensure_doctor_access(request):
        return redirect('home')

    profile = get_object_or_404(DoctorProfile, user=request.user)
    now = timezone.localtime(timezone.now())
    today = now.date()
    end_date = today + timedelta(days=14)

    if now.hour < 12:
        greeting_prefix = 'Good morning'
    elif now.hour < 18:
        greeting_prefix = 'Good afternoon'
    else:
        greeting_prefix = 'Good evening'

    greeting_text = f"{greeting_prefix}, Doctor!"

    doctor_appointments = Appointment.objects.filter(doctor=request.user)
    total_appointments = doctor_appointments.count()
    pending_appointments = doctor_appointments.filter(status='pending').count()
    total_patients = doctor_appointments.values('user_id').distinct().count()
    completed_appointments = doctor_appointments.filter(
        Q(status='completed') |
        Q(status='upcoming', availability__date__lt=today) |
        Q(status='upcoming', availability__date=today, availability__end_time__lt=now.time())
    ).count()

    availabilities = DoctorAvailability.objects.filter(
        doctor=request.user,
        date__range=[today, end_date]
    ).select_related('appointment').order_by('date', 'start_time') 

    pending_payment_verifications = Payment.objects.filter(
        appointment__doctor=request.user,
        status='pending'
    ).select_related('user', 'appointment').order_by('-created_at')

    return render(request, 'doctor/doctor_dashboard.html', {
        'availabilities': availabilities,
        'profile': profile,
        'days_of_week': DoctorAvailability.DAYS_OF_WEEK,
        'greeting_text': greeting_text,
        'total_appointments': total_appointments,
        'pending_appointments': pending_appointments,
        'total_patients': total_patients,
        'completed_appointments': completed_appointments,
        'show_profile_warning': profile.is_verified and not profile.is_profile_complete,
        'pending_payment_verifications': pending_payment_verifications,
    })


@login_required
def add_availability(request):
    if request.method == "POST":
        start_time_str = request.POST.get("start_time")
        end_time_str = request.POST.get("end_time")
        duration = int(request.POST.get("duration"))
        selected_days = [int(day) for day in request.POST.getlist("days")]

        if not selected_days:
            messages.error(request, "Please select at least one day.")
            return redirect("doctor_dashboard")

        today = timezone.now().date()
        # LIMIT TO 14 DAYS HERE
        end_date = today + timedelta(days=14)
        
        start_time = datetime.strptime(start_time_str, "%H:%M").time()
        end_time = datetime.strptime(end_time_str, "%H:%M").time()

        # Validate time difference
        start_dt = datetime.combine(today, start_time)
        end_dt = datetime.combine(today, end_time)
        
        if end_dt <= start_dt:
            messages.error(request, "End time must be after start time.")
            return redirect("doctor_dashboard")
        
        time_diff_minutes = (end_dt - start_dt).total_seconds() / 60
        
        if time_diff_minutes < duration:
            messages.error(
                request, 
                f"Time difference must be at least {duration} minutes. You have {int(time_diff_minutes)} minutes between start and end time."
            )
            return redirect("doctor_dashboard")

        slots_created = 0
        current_date = today

        while current_date <= end_date:
            if current_date.weekday() in selected_days:
                temp_dt = datetime.combine(current_date, start_time)
                limit_dt = datetime.combine(current_date, end_time)

                while temp_dt + timedelta(minutes=duration) <= limit_dt:
                    slot_start = temp_dt.time()
                    slot_end = (temp_dt + timedelta(minutes=duration)).time()

                    # Only create if it doesn't exist
                    if not DoctorAvailability.objects.filter(doctor=request.user, date=current_date, start_time=slot_start).exists():
                        DoctorAvailability.objects.create(
                            doctor=request.user,
                            date=current_date,
                            start_time=slot_start,
                            end_time=slot_end,
                            is_active=True
                        )
                        slots_created += 1
                    temp_dt += timedelta(minutes=duration)
            current_date += timedelta(days=1)
        print("Selected days:", selected_days)
        messages.success(request, f"Generated slots for the next 14 days.")
        return redirect("doctor_dashboard")

@login_required
def toggle_availability(request, pk):
    slot = get_object_or_404(
        DoctorAvailability,
        pk=pk,
        doctor=request.user
    )

    slot.is_active = not slot.is_active
    slot.save()

    messages.success(request, "Availability status updated.")
    return redirect("doctor_dashboard")

@login_required
def delete_availability(request, pk):
    slot = get_object_or_404(
        DoctorAvailability,
        pk=pk,
        doctor=request.user
    )

    slot.delete()
    messages.success(request, "Availability deleted.")
    return redirect("doctor_dashboard")

@login_required
def add_cycle_log(request):
    if request.method == "POST":
        form = CycleLogForm(request.POST, user=request.user)

        if form.is_valid():
            cycle = form.save(commit=False)
            cycle.user = request.user

            user_profile, _ = UserProfile.objects.get_or_create(user=request.user)

            # Always source anthropometrics from profile, not form input.
            cycle.height_cm = float(user_profile.height_cm) if user_profile.height_cm is not None else None
            cycle.weight_kg = float(user_profile.weight_kg) if user_profile.weight_kg is not None else None

            previous_logs = CycleLog.objects.filter(user=request.user).exclude(last_period_start__isnull=True)
            last_log = previous_logs.order_by('-last_period_start').first()

            # Respect user-provided cycle length from the form (validated in CycleLogForm).
            if cycle.length_of_cycle is None and last_log and last_log.length_of_cycle:
                cycle.length_of_cycle = last_log.length_of_cycle

            # Mean menses length is derived from current input, with historical fallback.
            if cycle.length_of_menses:
                cycle.mean_menses_length = cycle.length_of_menses
            else:
                historical_mean = previous_logs.aggregate(avg_menses=Avg('mean_menses_length')).get('avg_menses')
                cycle.mean_menses_length = int(round(historical_mean)) if historical_mean else 5

            # ---- BMI calculation ----
            if cycle.height_cm and cycle.weight_kg:
                height_m = cycle.height_cm / 100
                cycle.bmi = round(cycle.weight_kg / (height_m ** 2), 2)
            elif last_log and last_log.bmi is not None:
                cycle.bmi = last_log.bmi
            else:
                cycle.bmi = 22.0

            # ---- ML FEATURES (UNCHANGED) ----
            features = [
                cycle.length_of_cycle,
                cycle.length_of_menses,
                cycle.mean_menses_length,
                cycle.total_menses_score,
                cycle.mean_bleeding_intensity,
                int(cycle.unusual_bleeding),
                cycle.bmi,
            ]

            historical_cycle_lengths = list(
                previous_logs
                .exclude(length_of_cycle__isnull=True)
                .values_list('length_of_cycle', flat=True)
            )
            if cycle.length_of_cycle:
                historical_cycle_lengths.append(cycle.length_of_cycle)

            if historical_cycle_lengths:
                predicted_days = int(round(sum(historical_cycle_lengths) / len(historical_cycle_lengths)))
            else:
                predicted_days = round(predict_cycle(features))

            # ---- DATE CALCULATIONS ----
            if cycle.last_period_start:
                active_period = _get_active_period(request.user)
                if active_period:
                    active_start = active_period.start_date or active_period.actual_start_date or active_period.last_period_start
                    if active_start != cycle.last_period_start:
                        messages.error(request, 'You already have an active period. Please end it before logging a new one.')
                        return redirect("dashboard_home")

                cycle.start_date = cycle.last_period_start
                cycle.actual_start_date = cycle.last_period_start
                cycle.is_confirmed = True
                cycle.predicted_next_period = (
                    cycle.last_period_start + timedelta(days=predicted_days)
                )
                cycle.predicted_start_date = cycle.predicted_next_period
                cycle.expected_end_date = cycle.last_period_start + timedelta(days=5)

                derived_end_date = cycle.last_period_start + timedelta(days=max(cycle.length_of_menses, 1) - 1)
                if derived_end_date <= timezone.localdate():
                    cycle.end_date = derived_end_date
                else:
                    cycle.end_date = None

                # Ovulation ≈ 14 days before next period
                cycle.estimated_ovulation_day = (
                    cycle.predicted_next_period - timedelta(days=14)
                )

                # Fertile window: 5 days before ovulation + ovulation day
                cycle.fertile_window_start = (
                    cycle.estimated_ovulation_day - timedelta(days=5)
                )
                cycle.fertile_window_end = cycle.estimated_ovulation_day

            # 🚫 1. Prevent future cycle logging
            if cycle.last_period_start > timezone.now().date():
                messages.error(request, "You cannot log a future cycle date.")
                return redirect("dashboard_home")


            # 🚫 2. Prevent multiple logs same day
            existing_same_day = CycleLog.objects.filter(
                user=request.user,
                last_period_start=cycle.last_period_start
            ).exists()

            if existing_same_day:
                messages.error(request, "You have already logged a cycle for this date.")
                return redirect("dashboard_home")


            # 🚫 3. Prevent unrealistic short interval
            last_log = CycleLog.objects.filter(user=request.user).order_by('-last_period_start').first()

            if last_log:
                days_difference = (cycle.last_period_start - last_log.last_period_start).days

                if days_difference < 0:
                    messages.error(request, "Invalid cycle date.")
                    return redirect("dashboard_home")

                if days_difference < 15:
                    messages.error(
                        request,
                        f"This is only {days_difference} days after your last cycle. "
                        "Cycles shorter than 15 days are uncommon. Cannot add!"
                    )
                    return redirect("dashboard_home")

                if 15 <= days_difference < 21:
                    messages.warning(
                        request,
                        f"This is {days_difference} days after your last cycle. "
                        "Are you sure? Short cycles may affect prediction accuracy."
                    )
            cycle.save()
            update_cycle_prediction(request.user)

            _create_notification(
                request.user,
                'Cycle prediction updated',
                'Your new cycle log has been saved and prediction generated.',
                'cycle',
            )

            # Save trigger in session
            request.session["show_prediction"] = True
            request.session["last_cycle_id"] = cycle.id

            return redirect("dashboard_home")
        for field_errors in form.errors.values():
            for err in field_errors:
                messages.error(request, err)
        return redirect("dashboard_home")
    return redirect("dashboard_home")
        


from .models import Appointment, ChatMessage
# Chat Consultation
def _get_consultation_chat_state(appointment):
    now = timezone.now()
    start_dt = timezone.make_aware(
        timezone.datetime.combine(appointment.availability.date, appointment.availability.start_time)
    )
    end_dt = timezone.make_aware(
        timezone.datetime.combine(appointment.availability.date, appointment.availability.end_time)
    )

    is_status_open = appointment.status == 'upcoming'
    is_active = is_status_open and (start_dt <= now <= end_dt)
    is_future = now < start_dt
    is_locked = now > end_dt or not is_status_open

    return {
        'is_active': is_active,
        'is_locked': is_locked,
        'is_future': is_future,
        'can_chat': is_active,
        'start_dt': start_dt,
        'end_dt': end_dt,
    }


@login_required
def chat_room(request, appointment_id):
    """Compatibility endpoint: keep old links working via split-screen chat page."""
    return redirect('dashboard_chat_redirect', appointment_id=appointment_id)


@login_required
def consultation_patient_document(request, appointment_id, document_id):
    """Serve patient document only to the assigned doctor or the patient in this consultation."""
    appointment = get_object_or_404(Appointment, id=appointment_id, status='upcoming')

    if request.user.id not in (appointment.user_id, appointment.doctor_id):
        return HttpResponse(status=403)

    document = get_object_or_404(UserDocument, id=document_id, user=appointment.user)
    as_attachment = request.GET.get('download') == '1'
    filename = document.original_name or document.file.name.split('/')[-1]
    return FileResponse(document.file.open('rb'), as_attachment=as_attachment, filename=filename)


@login_required
def consultation_chat_file(request, appointment_id, message_id):
    """Serve chat attachment files only to participants of the approved consultation."""
    appointment = get_object_or_404(Appointment, id=appointment_id, status='upcoming')

    if request.user.id not in (appointment.user_id, appointment.doctor_id):
        return HttpResponse(status=403)

    expected_room_name = f"chat_{appointment.user_id}_{appointment.doctor_id}"
    chat_message = get_object_or_404(
        ChatMessage,
        id=message_id,
        room_name=expected_room_name,
    )

    if not chat_message.file:
        return HttpResponse(status=404)

    as_attachment = request.GET.get('download') == '1'
    filename = chat_message.file.name.split('/')[-1]
    return FileResponse(chat_message.file.open('rb'), as_attachment=as_attachment, filename=filename)


@login_required
def dashboard_chat(request):
    role_redirect = _ensure_chat_access(request)
    if role_redirect:
        return role_redirect

    """Chat interface page containing only the conversations sidebar/list."""
    return render(request, 'dashboard/chat.html', {
        'role': request.user.role,
        'initial_appointment_id': None,
    })


@login_required
def dashboard_chat_redirect(request, appointment_id):
    role_redirect = _ensure_chat_access(request)
    if role_redirect:
        return role_redirect

    appointment = get_object_or_404(Appointment, id=appointment_id)
    if request.user.id not in (appointment.user_id, appointment.doctor_id):
        messages.error(request, 'You do not have access to this consultation room.')
        return redirect('dashboard_chat' if request.user.role == 'user' else 'doctor_chat_hub')

    if appointment.status != 'upcoming':
        messages.error(request, 'Payment not verified yet')
        return redirect('appointment' if request.user.role == 'user' else 'doctor_appointment')

    return render(
        request,
        'dashboard/chat.html',
        {
            'role': request.user.role,
            'initial_appointment_id': appointment.id,
        },
    )


@login_required
def doctor_chat_hub(request):
    """Open a doctor's most relevant consultation chat from sidebar Chat entry."""
    if not _ensure_doctor_access(request):
        return redirect('home')

    now = timezone.now()
    approved_appts = list(
        Appointment.objects.filter(doctor=request.user, status='upcoming')
        .select_related('availability')
        .order_by('availability__date', 'availability__start_time')
    )

    if not approved_appts:
        messages.info(request, 'No upcoming consultations available for chat yet.')
        return redirect('doctor_appointment')

    active = []
    upcoming = []
    past = []

    for appt in approved_appts:
        start_dt = timezone.make_aware(datetime.combine(appt.availability.date, appt.availability.start_time))
        end_dt = timezone.make_aware(datetime.combine(appt.availability.date, appt.availability.end_time))

        if start_dt <= now <= end_dt:
            active.append(appt)
        elif start_dt > now:
            upcoming.append(appt)
        else:
            past.append(appt)

    if active:
        return redirect('dashboard_chat_redirect', appointment_id=active[0].id)
    if upcoming:
        return redirect('dashboard_chat_redirect', appointment_id=upcoming[0].id)
    return redirect('dashboard_chat_redirect', appointment_id=past[-1].id)


from django.views.decorators.csrf import csrf_exempt
import os

@login_required
def upload_chat_file(request):
    """Handle file uploads for chat messages"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'})
    
    file = request.FILES.get('file')
    room_name = request.POST.get('room_name')
    appointment_id = request.POST.get('appointment_id')
    message_text = request.POST.get('message', '')
    
    if not file or not room_name:
        return JsonResponse({'success': False, 'error': 'Missing file or room name'})

    appointment = None
    try:
        appointment = Appointment.objects.get(id=appointment_id, status='upcoming')
    except (Appointment.DoesNotExist, ValueError, TypeError):
        return JsonResponse({'success': False, 'error': 'Invalid appointment'})

    if request.user.id not in (appointment.user_id, appointment.doctor_id):
        return JsonResponse({'success': False, 'error': 'Unauthorized access'})

    expected_room_name = f"chat_{appointment.user_id}_{appointment.doctor_id}"
    if room_name != expected_room_name:
        return JsonResponse({'success': False, 'error': 'Invalid chat room'})
    
    # Validate file type
    allowed_extensions = ['.jpg', '.jpeg', '.png', '.pdf', '.doc', '.docx']
    file_ext = os.path.splitext(file.name)[1].lower()
    
    if file_ext not in allowed_extensions:
        return JsonResponse({'success': False, 'error': 'Invalid file type'})
    
    # Validate file size (10MB max)
    if file.size > 10 * 1024 * 1024:
        return JsonResponse({'success': False, 'error': 'File too large (max 10MB)'})
    
    try:
        # Save the message with file
        chat_message = ChatMessage.objects.create(
            room_name=room_name,
            sender=request.user,
            message=message_text,
            file=file,
            is_note=False
        )
        
        # Update conversation with last message
        from .models import Conversation
        try:
            # Extract doctor and patient IDs from room_name format: chat_patientID_doctorID
            parts = room_name.split('_')
            if len(parts) >= 3:
                patient_id = int(parts[1])
                doctor_id = int(parts[2])
                
                conversation = Conversation.objects.filter(
                    doctor_id=doctor_id,
                    patient_id=patient_id
                ).first()
                
                if conversation:
                    conversation.last_message = f"📎 {file.name}"
                    conversation.last_message_time = timezone.now()
                    
                    # Increment unread count for the receiver
                    if request.user.role == 'doctor':
                        conversation.unread_count_patient += 1
                    else:
                        conversation.unread_count_doctor += 1
                    
                    conversation.save()
                    
                    # Broadcast to channel layer for real-time updates
                    from asgiref.sync import async_to_sync
                    from channels.layers import get_channel_layer
                    channel_layer = get_channel_layer()
                    async_to_sync(channel_layer.group_send)(
                        'broadcast',
                        {
                            'type': 'broadcast_message',
                            'message_type': 'file_message',
                            'room_name': room_name
                        }
                    )
        except Exception as e:
            print(f"Error updating conversation: {e}")
        
        # Determine file type
        file_type = 'image' if file_ext in ['.jpg', '.jpeg', '.png'] else 'document'
        
        return JsonResponse({
            'success': True,
            'file_url': chat_message.file.url,
            'file_name': file.name,
            'file_type': file_type,
            'message_id': chat_message.id
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})



from .models import Conversation

@login_required
def get_conversations(request):
    if request.user.is_staff or request.user.is_superuser or request.user.role not in {'user', 'doctor'}:
        return JsonResponse({'error': 'Forbidden'}, status=403)

    """API endpoint to fetch all conversations for the logged-in user"""
    user = request.user
    
    if user.role == 'doctor':
        conversations = Conversation.objects.filter(doctor=user).select_related('patient')
    else:
        conversations = Conversation.objects.filter(patient=user).select_related('doctor')
    
    conversations_data = []
    for conv in conversations:
        other_user = conv.get_other_user(user)
        
        # Get the latest consultation between participants.
        if user.role == 'doctor':
            appointment = Appointment.objects.filter(
                doctor=user,
                user=conv.patient,
            ).select_related('availability').order_by('-availability__date', '-availability__start_time').first()
        else:
            appointment = Appointment.objects.filter(
                user=user,
                doctor=conv.doctor,
            ).select_related('availability').order_by('-availability__date', '-availability__start_time').first()
        
        # Format the other user's name correctly
        if user.role == 'user':
            # For patients, show doctor's full name with "Dr." prefix
            doctor_name = other_user.doctor_profile.full_name or other_user.username
            display_name = f"Dr. {doctor_name}"
        else:
            # For doctors, show patient's username without prefix
            display_name = other_user.username
        
        conversations_data.append({
            'id': conv.id,
            'other_user': {
                'id': other_user.id,
                'name': display_name,
                'role': other_user.role
            },
            'last_message': conv.last_message or 'No messages yet',
            'last_message_time': conv.last_message_time.isoformat(),
            'unread_count': conv.get_unread_count(user),
            'appointment_id': appointment.id if appointment else None,
            'room_name': conv.room_name
        })
    
    return JsonResponse({'conversations': conversations_data})


@login_required
def get_message_history(request, appointment_id):
    if request.user.is_staff or request.user.is_superuser or request.user.role not in {'user', 'doctor'}:
        return JsonResponse({'error': 'Forbidden'}, status=403)

    """API endpoint to fetch message history for a conversation"""
    appointment = get_object_or_404(Appointment, id=appointment_id)
    user = request.user
    
    # Verify user is part of this appointment
    if appointment.user != user and appointment.doctor != user:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    # Get the room name for this appointment
    if user.role == 'doctor':
        room_name = f"chat_{appointment.user_id}_{appointment.doctor_id}"
        other_user = appointment.user
    else:
        room_name = f"chat_{appointment.user_id}_{appointment.doctor_id}"
        other_user = appointment.doctor
    
    chat_state = _get_consultation_chat_state(appointment)

    # Get all messages for this room
    messages_qs = ChatMessage.objects.filter(room_name=room_name, is_note=False).select_related('sender')
    
    messages_data = []
    for msg in messages_qs:
        # Determine message type
        message_type = 'text'
        file_url = None
        file_name = None
        
        if msg.file:
            # Determine if it's an image or document
            file_ext = msg.file.name.split('.')[-1].lower()
            if file_ext in ['jpg', 'jpeg', 'png']:
                message_type = 'image'
            else:
                message_type = 'document'
            
            file_url = msg.file.url
            file_name = msg.file.name.split('/')[-1]
        
        messages_data.append({
            'id': msg.id,
            'sender_id': msg.sender_id,
            'content': msg.message,
            'message_type': message_type,
            'file_url': file_url,
            'file_name': file_name,
            'timestamp': msg.timestamp.isoformat(),
            'is_read': msg.is_read
        })
    
    return JsonResponse(
        {
            'messages': messages_data,
            'consultation': {
                'is_active': chat_state['is_active'],
                'is_locked': chat_state['is_locked'],
                'is_future': chat_state['is_future'],
                'can_chat': chat_state['can_chat'],
                'status': appointment.status,
                'start_time_label': timezone.localtime(chat_state['start_dt']).strftime('%d %b %Y, %H:%M'),
                'end_time_label': timezone.localtime(chat_state['end_dt']).strftime('%d %b %Y, %H:%M'),
                'other_user_name': (
                    (other_user.doctor_profile.full_name if user.role == 'user' and hasattr(other_user, 'doctor_profile') else other_user.username)
                    or other_user.username
                ),
            },
        }
    )


@login_required
def send_message(request):
    if request.user.is_staff or request.user.is_superuser or request.user.role not in {'user', 'doctor'}:
        return JsonResponse({'error': 'Forbidden'}, status=403)

    """API endpoint to send a chat message"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'})
    
    import json
    try:
        data = json.loads(request.body)
    except:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'})
    
    appointment_id = data.get('appointment_id')
    room_name = data.get('room_name')
    content = data.get('content', '')
    
    if not appointment_id or not room_name:
        return JsonResponse({'success': False, 'error': 'Missing appointment or room'})
    
    appointment = get_object_or_404(Appointment, id=appointment_id)
    user = request.user
    
    # Verify user is part of this appointment
    if appointment.user != user and appointment.doctor != user:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    expected_room_name = f"chat_{appointment.user_id}_{appointment.doctor_id}"
    if room_name != expected_room_name:
        return JsonResponse({'success': False, 'error': 'Invalid room selected'})

    chat_state = _get_consultation_chat_state(appointment)
    if not chat_state['can_chat']:
        return JsonResponse({'success': False, 'error': 'Consultation chat is locked right now'})
    
    # Create the message
    msg = ChatMessage.objects.create(
        room_name=room_name,
        sender=user,
        message=content
    )
    
    # Update Conversation
    if user.role == 'doctor':
        conversation = Conversation.objects.get(doctor=user, patient=appointment.user)
        conversation.unread_count_patient += 1
    else:
        conversation = Conversation.objects.get(doctor=appointment.doctor, patient=user)
        conversation.unread_count_doctor += 1
    
    conversation.last_message = content
    conversation.last_message_time = msg.timestamp
    conversation.save()

    recipient = appointment.user if user.role == 'doctor' else appointment.doctor
    _create_notification(
        recipient,
        'New message received',
        f"{user.username} sent you a new message.",
        'message_received',
        target_url=reverse('dashboard_chat') if recipient.role == 'user' else reverse('doctor_appointment'),
        target_section_id='chat-section' if recipient.role == 'user' else 'appointments-section',
    )
    
    # Broadcast message via WebSocket
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer
    
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"chat_{room_name}",
        {
            "type": "message",
            "message": content,
            "sender_id": user.id,
            "sender_name": user.username,
            "timestamp": msg.timestamp.isoformat(),
            "message_type": "text",
            "message_id": msg.id
        }
    )
    
    # Also broadcast to conversation list updates
    async_to_sync(channel_layer.group_send)(
        "broadcast",
        {
            "type": "message",
            "message": content,
            "sender_id": user.id,
            "timestamp": msg.timestamp.isoformat(),
            "message_type": "text"
        }
    )
    
    return JsonResponse({
        'success': True,
        'message': {
            'id': msg.id,
            'sender_id': msg.sender_id,
            'content': msg.message,
            'message_type': 'text',
            'timestamp': msg.timestamp.isoformat()
        }
    })


@login_required
def upload_message_file(request):
    if request.user.is_staff or request.user.is_superuser or request.user.role not in {'user', 'doctor'}:
        return JsonResponse({'error': 'Forbidden'}, status=403)

    """API endpoint to upload file for chat message"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'})
    
    file = request.FILES.get('file')
    appointment_id = request.POST.get('appointment_id')
    room_name = request.POST.get('room_name')
    
    if not file or not appointment_id or not room_name:
        return JsonResponse({'success': False, 'error': 'Missing file or metadata'})
    
    appointment = get_object_or_404(Appointment, id=appointment_id)
    user = request.user
    
    # Verify user is part of this appointment
    if appointment.user != user and appointment.doctor != user:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    expected_room_name = f"chat_{appointment.user_id}_{appointment.doctor_id}"
    if room_name != expected_room_name:
        return JsonResponse({'success': False, 'error': 'Invalid room selected'})

    chat_state = _get_consultation_chat_state(appointment)
    if not chat_state['can_chat']:
        return JsonResponse({'success': False, 'error': 'Consultation chat is locked right now'})

    # Validate file
    import os
    allowed_extensions = ['.jpg', '.jpeg', '.png', '.pdf', '.doc', '.docx']
    file_ext = os.path.splitext(file.name)[1].lower()
    
    if file_ext not in allowed_extensions:
        return JsonResponse({'success': False, 'error': 'Invalid file type'})
    
    if file.size > 10 * 1024 * 1024:  # 10MB
        return JsonResponse({'success': False, 'error': 'File too large'})
    
    # Create the message with file
    msg = ChatMessage.objects.create(
        room_name=room_name,
        sender=user,
        file=file,
        message=file.name
    )
    
    # Update Conversation
    if user.role == 'doctor':
        conversation = Conversation.objects.get(doctor=user, patient=appointment.user)
        conversation.unread_count_patient += 1
    else:
        conversation = Conversation.objects.get(doctor=appointment.doctor, patient=user)
        conversation.unread_count_doctor += 1
    
    conversation.last_message = f"📎 {file.name}"
    conversation.last_message_time = msg.timestamp
    conversation.save()
    
    # Determine message type
    message_type = 'image' if file_ext in ['.jpg', '.jpeg', '.png'] else 'document'
    
    # Broadcast file message via WebSocket
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer
    
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"chat_{room_name}",
        {
            "type": "file_message",
            "message_type": message_type,
            "file_url": msg.file.url,
            "file_name": file.name,
            "sender_id": user.id,
            "sender_name": user.username,
            "timestamp": msg.timestamp.isoformat(),
            "message_id": msg.id
        }
    )
    
    # Also broadcast to conversation list updates
    async_to_sync(channel_layer.group_send)(
        "broadcast",
        {
            "type": "file_message",
            "message_type": message_type,
            "timestamp": msg.timestamp.isoformat(),
            "sender_id": user.id
        }
    )
    
    return JsonResponse({
        'success': True,
        'message': {
            'id': msg.id,
            'sender_id': msg.sender_id,
            'content': file.name,
            'message_type': message_type,
            'file_url': msg.file.url,
            'file_name': file.name,
            'timestamp': msg.timestamp.isoformat()
        }
    })


@login_required
def mark_conversation_as_read(request, appointment_id):
    if request.user.is_staff or request.user.is_superuser or request.user.role not in {'user', 'doctor'}:
        return JsonResponse({'error': 'Forbidden'}, status=403)

    """Mark conversation as read for the current user"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'})
    
    appointment = get_object_or_404(Appointment, id=appointment_id)
    user = request.user
    
    # Verify user is part of this appointment
    if appointment.user != user and appointment.doctor != user:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    # Get conversation
    if user.role == 'doctor':
        conversation = Conversation.objects.get(doctor=user, patient=appointment.user)
        conversation.unread_count_doctor = 0
    else:
        conversation = Conversation.objects.get(doctor=appointment.doctor, patient=user)
        conversation.unread_count_patient = 0
    
    conversation.save()
    
    return JsonResponse({'success': True})