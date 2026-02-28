from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout, logout
from django.contrib import messages
from .models import User
from django.contrib.auth.decorators import login_required
from .models import UserProfile, DoctorProfile, DoctorAvailability, Appointment, DoctorReview
from .forms import CycleLogForm
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
    
    # Get previous history
    history = ChatMessage.objects.filter(room_name=room_name)

    context = {
        'appointment': appointment,
        'room_name': room_name,
        'history': history,
        'is_active': is_active,
        'is_locked': is_locked,
        'role': request.user.role
    }
    return render(request, 'dashboard/room.html', context)