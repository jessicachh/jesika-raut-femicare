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


@login_required
def terms_and_conditions(request):
    if request.method == "POST":
        user = request.user
        user.has_accepted_terms = True
        user.save()
        
        if user.role == 'doctor':
            return redirect('doctor_dashboard')
        else:
            return redirect('dashboard_home')
            
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
        email = request.POST.get('email')
        password = request.POST.get('password')
        confirm = request.POST.get('confirm_password')
        role = request.POST.get('role')

        if password != confirm:
            messages.error(request, "Passwords do not match")
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
        
        # Automatically log the user in
        auth_login(request, user)

        # Direct first-time user to their profile page
        if role == 'doctor':
            return redirect('doctor_details')
        else:
            return redirect('user_profile')

    return render(request, 'signup.html')



def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)

        if user is None:
            messages.error(request, "Invalid username or password")
            return redirect('login')

        auth_login(request, user)

        if not getattr(user, 'has_accepted_terms', False):
            return redirect('terms_and_conditions')

        if user.role == 'doctor':
            try:
                profile = user.doctor_profile
            except DoctorProfile.DoesNotExist:
                return redirect('doctor_details')

            if not profile.is_verified:
                return render(request, 'doctor_pending.html', {'profile': profile})
            
            return redirect('doctor_dashboard')

        else:
            profile, created = UserProfile.objects.get_or_create(user=user)
            if created or not profile.date_of_birth:
                return redirect('user_profile')
            return redirect('dashboard_home')

    return render(request, 'login.html')


@login_required
def user_profile(request):
    profile, created = UserProfile.objects.get_or_create(user=request.user)

    # If profile already filled, redirect to dashboard
    if profile.date_of_birth and request.method != 'POST':
        return redirect('dashboard_home')

    if request.method == 'POST':
        profile.date_of_birth = request.POST.get('dob')
        profile.cycle_length = request.POST.get('cycle_length')
        profile.last_period_date = request.POST.get('last_period_date')
        profile.save()

        return redirect('dashboard_home')

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
        },
    )

@login_required
def dashboard_home(request):
    logs = CycleLog.objects.filter(user=request.user)
    latest_cycle = logs.first()

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
    })

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
        form = CycleLogForm(request.POST)

        if form.is_valid():
            cycle = form.save(commit=False)
            cycle.user = request.user

            # ---- BMI calculation ----
            if cycle.height_cm and cycle.weight_kg:
                height_m = cycle.height_cm / 100
                cycle.bmi = round(cycle.weight_kg / (height_m ** 2), 2)

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