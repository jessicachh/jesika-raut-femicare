from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout, logout
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib import messages
import random
import time
from django.http import JsonResponse
from .models import User
from django.contrib.auth.decorators import login_required
from .models import (
    UserProfile,
    DoctorProfile,
    DoctorAvailability,
    Appointment,
    DoctorReview,
    UserDocument,
    HealthLog,
    Notification,
    MoodEntry,
    PredictionFeedback,
    SymptomLog,
    PeriodCheckIn,
    TwoFactorCode,
)
from .forms import (
    CycleLogForm,
    UserProfileForm,
    AccountSettingsForm,
    EmailVerificationForm,
    UserDocumentUploadForm,
)
from .models import CycleLog
from tracker.ml.predict import predict_cycle
from datetime import timedelta, datetime
from django.utils import timezone
from django.core.paginator import Paginator
from django.core.mail import send_mail
from django.conf import settings
from django.db.models import Avg, Count, Q
from django.utils.dateparse import parse_date


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
    send_mail(
        subject='FemiCare Verification Code',
        message=(
            f'Your verification code is: {code_obj.code}\n\n'
            'This code expires in 10 minutes. If this was not you, please ignore this email.'
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
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


def _redirect_user_after_login(request, user):
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

    return redirect('dashboard_home')


def _is_google_oauth_ready():
    has_env_config = bool(getattr(settings, 'GOOGLE_CLIENT_ID', '')) and bool(getattr(settings, 'GOOGLE_CLIENT_SECRET', ''))
    if has_env_config:
        return True

    try:
        from allauth.socialaccount.models import SocialApp
    except Exception:
        return False

    return SocialApp.objects.filter(provider='google', sites__id=getattr(settings, 'SITE_ID', 1)).exists()
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
        is_profile_complete=True
    )

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

def signup_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        email = (request.POST.get('email') or '').strip().lower()
        password = request.POST.get('password')
        confirm = request.POST.get('confirm_password')
        role = request.POST.get('role') or 'user'

        if password != confirm:
            messages.error(request, "Passwords do not match")
            return redirect('signup')

        if User.objects.filter(email=email).exists():
            messages.error(request, "Email already exists")
            return redirect('signup')

        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already exists")
            return redirect('signup')

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            role=role
        )
        
        auth_login(request, user)

        request.session['prompt_2fa_after_signup'] = True
        request.session['post_signup_next'] = 'doctor_details' if role == 'doctor' else 'user_profile'
        return redirect('two_factor_setup_prompt')

    google_oauth_ready = _is_google_oauth_ready()
    return render(request, 'signup.html', {'google_oauth_ready': google_oauth_ready})



def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        remember_me = request.POST.get('remember_me') == 'on'

        user = authenticate(request, username=username, password=password)

        if user is None:
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
        return _redirect_user_after_login(request, user)

    google_oauth_ready = _is_google_oauth_ready()
    return render(request, 'login.html', {'google_oauth_ready': google_oauth_ready})


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
    profile, _ = UserProfile.objects.get_or_create(user=request.user)

    # If profile already filled, redirect to dashboard
    profile_complete = (
        profile.date_of_birth and
        profile.height_cm not in (None, 0) and
        profile.weight_kg not in (None, 0)
    )
    if profile_complete and request.method != 'POST':
        return _redirect_user_after_login(request, request.user)

    if request.method == 'POST':
        profile.date_of_birth = request.POST.get('dob')

        height_raw = request.POST.get('height_cm')
        weight_raw = request.POST.get('weight_kg')

        try:
            height_val = float(height_raw)
            weight_val = float(weight_raw)
            if height_val <= 0 or weight_val <= 0:
                raise ValueError
        except (TypeError, ValueError):
            messages.error(request, 'Please enter valid height and weight values greater than 0.')
            return render(request, 'user_profile.html', {'profile': profile})

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
        profile.full_name = request.POST.get("full_name")
        profile.specialization = request.POST.get('specialization')
        profile.license_number = request.POST.get('license')
        exp = request.POST.get('experience_years')
        profile.experience_years = int(exp) if exp else None
        profile.hospital_name = request.POST.get("hospital_name")
        profile.location = request.POST.get("location")
        
        if request.FILES.get('certificate'):
            profile.certificate = request.FILES['certificate']
        
        profile.save()
    

        # IMPORTANT: Redirect to pending page
        return redirect(request, 'doctor_pending.html')

    return render(request, 'doctor_details.html', {'profile': profile})

@login_required
def public_doctor_profile(request, pk):
    doctor = get_object_or_404(DoctorProfile, pk=pk)
    
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
        appointment__status__in=['pending', 'approved'] 
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
            status__in=['pending', 'approved']
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
        )
        _create_notification(
            request.user,
            'Appointment requested',
            'Your appointment request has been submitted.',
            'appointment',
        )

        # Email logic remains same...
        messages.success(request, "Request sent!")
        return redirect("appointment")
    
    return redirect("public_doctor_profile", pk=slot.doctor.doctorprofile.id)

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

    for appt in appointments:
        # Combine date and time into a full datetime object for comparison
        appt_time_start = timezone.make_aware(datetime.combine(appt.availability.date, appt.availability.start_time))
        appt_time_end = timezone.make_aware(datetime.combine(appt.availability.date, appt.availability.end_time))

        if appt.status == 'pending':
            appt.display_status = "Pending" if appt.availability.date >= today else "Expired / Missed"
            appt.status_color = "info" if appt.availability.date >= today else "secondary"
            pending_appointments.append(appt)

        elif appt.status == 'approved':
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
        'pending_appointments': pending_appointments,
        'upcoming_appointments': upcoming_appointments,
        'ongoing_appointments': ongoing_appointments,
        'completed_appointments': completed_appointments,
        'rejected_appointments': rejected_appointments,
        'today': today,
    })

@login_required
def respond_appointment(request, appointment_id):
    appointment = get_object_or_404(Appointment, id=appointment_id, doctor=request.user)
    
    if request.method == 'POST':
        action = request.POST.get('action') 
        reject_reason = request.POST.get('reject_reason', '')

        if action == 'approve':
            appointment.status = 'approved'
            msg = f"Your appointment with Dr. {request.user.doctor_profile.full_name} has been approved!"
        
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
            
            msg = f"Your appointment was declined. Reason: {reject_reason}"

        appointment.save()

        if action == 'approve':
            _create_notification(
                appointment.user,
                'Appointment accepted',
                f'Your appointment with Dr. {request.user.doctor_profile.full_name} was accepted.',
                'appointment',
            )
        elif action == 'reject':
            _create_notification(
                appointment.user,
                'Appointment rejected',
                f'Your appointment was rejected. Reason: {reject_reason or "Not provided"}.',
                'appointment',
            )

        # Notification Logic...
        try:
            send_mail(
                subject=f"Appointment Update: {appointment.status.upper()}",
                message=msg,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[appointment.user.email],
            )
        except: pass

        messages.success(request, f"Appointment {appointment.status} successfully.")
    
    return redirect('doctor_appointment') # Redirect back to the requests list

@login_required
def doctor_profile(request):
    profile = get_object_or_404(DoctorProfile, user=request.user)

    if request.method == "POST":
        if request.FILES.get("photo"):
            profile.photo = request.FILES["photo"]

        profile.bio = request.POST.get("bio", "").strip()
        profile.qualifications = request.POST.get("qualifications", "").strip()
        profile.languages_spoken = request.POST.get("languages_spoken", "").strip()

        profile.save() 

        messages.success(request, "Profile updated successfully!")
        return redirect("doctor_profile")

    return render(request, "doctor/doctor_profile.html", {"profile": profile})


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


def _create_notification(user, title, message, notification_type='system'):
    if not user:
        return

    Notification.objects.create(
        user=user,
        title=title,
        message=message,
        type=notification_type,
    )


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


def _clear_email_verification_session(request):
    request.session.pop('pending_email', None)
    request.session.pop('email_otp_code', None)
    request.session.pop('email_otp_created_at', None)


def _send_email_verification_code(request, new_email):
    otp = str(random.SystemRandom().randint(100000, 999999))

    request.session['pending_email'] = new_email
    request.session['email_otp_code'] = otp
    request.session['email_otp_created_at'] = int(time.time())

    send_mail(
        subject='FemiCare Email Verification Code',
        message=(
            f'Use this verification code to confirm your new email address: {otp}\n\n'
            'This code expires in 10 minutes.'
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[new_email],
        fail_silently=False,
    )


@login_required
def profile_view(request):
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
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    two_factor_enabled = request.user.is_two_factor_enabled

    if request.method == 'POST':
        account_form = AccountSettingsForm(request.POST, instance=profile, user=request.user)
        password_form = PasswordChangeForm(request.user)
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
                messages.success(request, 'Account settings updated successfully.')

            return redirect('dashboard_settings')
    else:
        account_form = AccountSettingsForm(instance=profile, user=request.user)
        password_form = PasswordChangeForm(request.user)
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
        },
    )


@login_required
def verify_email_code(request):
    if request.method != 'POST':
        return redirect('dashboard_settings')

    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    account_form = AccountSettingsForm(instance=profile, user=request.user)
    password_form = PasswordChangeForm(request.user)
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
        },
    )


@login_required
def get_notifications(request):
    notifications = Notification.objects.filter(user=request.user).order_by('-created_at')[:20]
    unread_count = Notification.objects.filter(user=request.user, is_read=False).count()

    payload = [
        {
            'id': item.id,
            'title': item.title,
            'message': item.message,
            'type': item.type,
            'is_read': item.is_read,
            'created_at': item.created_at.isoformat(),
            'relative_time': _relative_time(item.created_at),
        }
        for item in notifications
    ]

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
    if request.method != 'POST':
        return redirect('dashboard_settings')

    user = request.user

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

    user.delete()
    auth_logout(request)
    messages.success(request, 'Your account has been deleted successfully.')
    return redirect('login')


@login_required
def change_password(request):
    if request.method != 'POST':
        return redirect('dashboard_settings')

    form = PasswordChangeForm(request.user, request.POST)
    _bootstrapize_password_form(form)
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    account_form = AccountSettingsForm(instance=profile, user=request.user)

    if form.is_valid():
        user = form.save()
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
        },
    )

@login_required
def dashboard_home(request):
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

    recent_symptoms = []
    for symptom in SymptomLog.objects.filter(user=request.user, source__in=['manual', 'first_login']).order_by('-date', '-created_at').values_list('symptom', flat=True):
        if symptom not in recent_symptoms:
            recent_symptoms.append(symptom)
        if len(recent_symptoms) >= 8:
            break

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
    predicted_next_period = latest_cycle.predicted_next_period if latest_cycle else None

    if not predicted_next_period and last_period_date and avg_cycle_length:
        predicted_next_period = last_period_date + timedelta(days=int(round(avg_cycle_length)))

    active_cycle = cycle_log_qs.exclude(last_period_start__isnull=True).filter(last_period_start__lte=today).order_by('-last_period_start').first()
    is_on_period = False
    show_period_checkin_prompt = False

    if active_cycle and active_cycle.length_of_menses:
        period_end = active_cycle.last_period_start + timedelta(days=max(active_cycle.length_of_menses, 1) - 1)
        is_on_period = active_cycle.last_period_start <= today <= period_end
        if is_on_period:
            show_period_checkin_prompt = not PeriodCheckIn.objects.filter(user=request.user, cycle_log=active_cycle).exists()

    if show_period_checkin_prompt:
        show_mood_prompt = False

    period_status_text = "No active cycle today"
    period_status_variant = "neutral"
    if is_on_period and active_cycle:
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
    feedback_log_ids = set(
        PredictionFeedback.objects.filter(user=request.user, cycle_log__isnull=False)
        .values_list('cycle_log_id', flat=True)
    )
    for log in logs.exclude(predicted_next_period__isnull=True).order_by('-predicted_next_period'):
        if log.predicted_next_period <= today and log.id not in feedback_log_ids:
            feedback_target = log
            break

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
    })


@login_required
def submit_mood_checkin(request):
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
    if request.method != 'POST':
        return redirect('dashboard_home')

    cycle_log_id = request.POST.get('cycle_log_id')
    response = request.POST.get('is_correct')
    actual_date_raw = request.POST.get('actual_date')

    if not cycle_log_id or response not in {'yes', 'no'}:
        messages.error(request, 'Invalid feedback submission.')
        return redirect('dashboard_home')

    cycle_log = get_object_or_404(CycleLog, id=cycle_log_id, user=request.user)
    if not cycle_log.predicted_next_period:
        messages.error(request, 'This prediction does not have a valid predicted date.')
        return redirect('dashboard_home')

    is_correct = response == 'yes'
    actual_date = cycle_log.predicted_next_period if is_correct else parse_date(actual_date_raw or '')

    if not is_correct and not actual_date:
        messages.error(request, 'Please provide the actual period start date.')
        return redirect('dashboard_home')

    PredictionFeedback.objects.update_or_create(
        user=request.user,
        cycle_log=cycle_log,
        defaults={
            'predicted_date': cycle_log.predicted_next_period,
            'actual_date': actual_date,
            'is_correct': is_correct,
        }
    )

    messages.success(request, 'Prediction feedback saved. Thank you.')
    return redirect('dashboard_home')


@login_required
def submit_period_checkin(request):
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

    messages.success(request, 'Period check-in saved successfully.')
    return redirect('dashboard_home')


@login_required
def save_symptoms(request):
    if request.method != 'POST':
        return redirect('dashboard_home')

    selected_symptoms = [value.strip() for value in request.POST.getlist('symptoms') if value.strip()]
    valid_values = set(SYMPTOM_OPTIONS)
    selected_symptoms = [value for value in selected_symptoms if value in valid_values]

    today = timezone.localdate()
    active_cycle = (
        CycleLog.objects.filter(user=request.user)
        .exclude(last_period_start__isnull=True)
        .filter(last_period_start__lte=today)
        .order_by('-last_period_start')
        .first()
    )

    SymptomLog.objects.filter(user=request.user, date=today, source='manual').delete()

    SymptomLog.objects.bulk_create(
        [
            SymptomLog(
                user=request.user,
                cycle_log=active_cycle,
                symptom=symptom,
                source='manual',
                date=today,
            )
            for symptom in selected_symptoms
        ]
    )

    messages.success(request, 'Symptoms updated successfully.')
    return redirect('dashboard_home')

@login_required
def appointment(request):
    today = timezone.now().date()
    
    # Sort by date and time so the earliest is always first
    all_appts = Appointment.objects.filter(user=request.user).select_related(
        'doctor__doctor_profile', 'availability'
    ).order_by('availability__date', 'availability__start_time')

    upcoming = []
    past = []

    for appt in all_appts:
        # Add your existing status and color logic here...
        if appt.availability.date < today:
            appt.display_status = "Completed" if appt.status == 'approved' else "Missed"
            appt.status_color = "secondary"
            past.append(appt)
        else:
            appt.display_status = appt.status.capitalize()
            appt.status_color = "success" if appt.status == 'approved' else "warning"
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
    if request.user.role != 'doctor':
        return redirect('home')

    profile = get_object_or_404(DoctorProfile, user=request.user)
    now = timezone.localtime(timezone.now())
    today = now.date()
    end_date = today + timedelta(days=14)

    availabilities = DoctorAvailability.objects.filter(
        doctor=request.user,
        date__range=[today, end_date]
    ).select_related('appointment').order_by('date', 'start_time') 

    return render(request, 'doctor/doctor_dashboard.html', {
        'availabilities': availabilities,
        'profile': profile,
        'days_of_week': DoctorAvailability.DAYS_OF_WEEK,
    })


@login_required
def add_availability(request):
    if request.method == "POST":
        start_time_str = request.POST.get("start_time")
        end_time_str = request.POST.get("end_time")
        duration = int(request.POST.get("duration"))
        selected_days = [int(day) for day in request.POST.getlist("days")]

                # 👇 ADD PRINTS RIGHT HERE
        print("Start:", start_time_str)
        print("End:", end_time_str)
        print("Duration:", duration)
        print("Selected days:", selected_days)
        
        if not selected_days:
            messages.error(request, "Please select at least one day.")
            return redirect("doctor_dashboard")

        today = timezone.now().date()
        # LIMIT TO 14 DAYS HERE
        end_date = today + timedelta(days=14)
        
        start_time = datetime.strptime(start_time_str, "%H:%M").time()
        end_time = datetime.strptime(end_time_str, "%H:%M").time()

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

            predicted_days = round(predict_cycle(features))

            # ---- DATE CALCULATIONS ----
            if cycle.last_period_start:
                cycle.predicted_next_period = (
                    cycle.last_period_start + timedelta(days=predicted_days)
                )

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
def chat_room(request, appointment_id):
    appointment = get_object_or_404(Appointment, id=appointment_id)
    
    # Logic: Only Approved appointments can chat
    if appointment.status != 'approved':
        return render(request, 'chat/locked.html', {"reason": "Appointment not approved."})

    # Time Logic
    now = timezone.now()
    start_dt = timezone.make_aware(timezone.datetime.combine(appointment.availability.date, appointment.availability.start_time))
    end_dt = timezone.make_aware(timezone.datetime.combine(appointment.availability.date, appointment.availability.end_time))

    is_active = start_dt <= now <= end_dt
    is_locked = now > end_dt

    # Room name is unique to the pair: "chat_patientID_doctorID"
    room_name = f"chat_{appointment.user.id}_{appointment.doctor.id}"
    
    # Get or create conversation
    from .models import Conversation
    conversation, created = Conversation.objects.get_or_create(
        doctor=appointment.doctor,
        patient=appointment.user,
        defaults={'room_name': room_name}
    )
    
    # Mark as read for current user
    conversation.mark_as_read(request.user)
    
    # Get previous history
    history = ChatMessage.objects.filter(room_name=room_name)

    context = {
        'appointment': appointment,
        'room_name': room_name,
        'history': history,
        'is_active': is_active,
        'is_locked': is_locked,
        'role': request.user.role,
        'conversation': conversation
    }
    return render(request, 'dashboard/room.html', context)


@login_required
def dashboard_chat(request):
    """Chat interface page containing only the conversations sidebar/list."""
    return render(request, 'dashboard/chat.html', {
        'role': request.user.role,
    })


@login_required
def dashboard_chat_redirect(request, appointment_id):
    """Compatibility route: redirect dashboard chat item to existing room view."""
    return redirect('chat_room', appointment_id=appointment_id)


from django.views.decorators.csrf import csrf_exempt
import os

@login_required
def upload_chat_file(request):
    """Handle file uploads for chat messages"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'})
    
    file = request.FILES.get('file')
    room_name = request.POST.get('room_name')
    message_text = request.POST.get('message', '')
    
    if not file or not room_name:
        return JsonResponse({'success': False, 'error': 'Missing file or room name'})
    
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
    """API endpoint to fetch all conversations for the logged-in user"""
    user = request.user
    
    if user.role == 'doctor':
        conversations = Conversation.objects.filter(doctor=user).select_related('patient')
    else:
        conversations = Conversation.objects.filter(patient=user).select_related('doctor')
    
    conversations_data = []
    for conv in conversations:
        other_user = conv.get_other_user(user)
        
        # Get appointment for this conversation
        if user.role == 'doctor':
            appointment = Appointment.objects.filter(
                doctor=user,
                user=conv.patient,
                status='approved'
            ).first()
        else:
            appointment = Appointment.objects.filter(
                user=user,
                doctor=conv.doctor,
                status='approved'
            ).first()
        
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
    
    return JsonResponse({'messages': messages_data})


@login_required
def send_message(request):
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
    
    # Check if appointment is locked (finished)
    if appointment.status == 'completed':
        return JsonResponse({'success': False, 'error': 'Appointment has ended'})
    
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