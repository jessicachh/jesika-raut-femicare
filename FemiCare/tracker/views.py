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

        # Step 1: Check if authentication failed
        if user is None:
            messages.error(request, "Invalid username or password")
            return redirect('login')

        # Step 2: Doctor verification check
        if user.role == 'doctor':
            try:
                doctor_profile = DoctorProfile.objects.get(user=user)
            except DoctorProfile.DoesNotExist:
                messages.info(request, "Please fill your doctor profile for verification.")
                return redirect('doctor_details')

            if not doctor_profile.is_verified:
                messages.error(request, "Your account is not verified yet.")
                return render(request, 'doctor_pending.html')

        # Step 3: Login the user
        auth_login(request, user)

        # Step 4: Redirect based on role
        if user.role == 'doctor':
            return redirect('doctor_dashboard')
        else:
            # Normal user
            profile, created = UserProfile.objects.get_or_create(user=user)
            if created or not profile.date_of_birth:
                return redirect('user_profile')
            else:
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
        return redirect('login')

    profile, created = DoctorProfile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        profile.full_name = request.POST.get("full_name")
        profile.specialization = request.POST.get('specialization')
        profile.license_number = request.POST.get('license')
        profile.experience_years = request.POST.get('experience_years')
        profile.hospital_name = request.POST.get("hospital_name")
        if request.FILES.get('certificate'):
            profile.certificate = request.FILES['certificate']
        profile.save()

        profile.is_profile_complete = profile.check_profile_complete()
        profile.save()

        # Instead of login redirect, show pending page
        return render(request, 'doctor_pending.html')

    return render(request, 'doctor_details.html', {'profile': profile})

@login_required
def public_doctor_profile(request, pk):
    doctor = get_object_or_404(DoctorProfile, pk=pk)
    today = timezone.now().date()
    reviews = doctor.reviews.all().select_related("patient")
    two_weeks = today + timedelta(days=14)
    
    # Get only active, unbooked slots for the next 14 days
    availabilities = DoctorAvailability.objects.filter(
        doctor=doctor.user,
        date__range=[today, two_weeks],
        is_active=True,
        appointment__isnull=True  # Ensure only unbooked slots show
    ).order_by('date', 'start_time')

    return render(request, "doctor_profile.html", {
        "doctor": doctor,
        "availabilities": availabilities,
        "reviews": reviews,
    })

@login_required
def book_appointment(request, slot_id):
    # 1. Get the slot and ensure it is still active/available
    slot = get_object_or_404(DoctorAvailability, id=slot_id, is_active=True)

    # 2. Safety Check: Prevent booking if the time has already passed
    if slot.date < timezone.now().date():
        messages.error(request, "This slot has already expired.")
        return redirect("public_doctor_profile", pk=slot.doctor.doctorprofile.id)

    # 3. Conflict Prevention: Ensure this user doesn't already have an appointment 
    # with THIS doctor on THIS specific day (Practical UX rule)
    existing_today = Appointment.objects.filter(
        user=request.user,
        doctor=slot.doctor,
        availability__date=slot.date,
        status__in=['approved', 'pending'] # Check for active bookings
    ).exists()

    if existing_today:
        messages.error(request, "You already have an appointment with this doctor on this day.")
        return redirect("public_doctor_profile", pk=slot.doctor.doctorprofile.id)

    # 4. Conflict Prevention: Check if the slot was JUST taken by someone else 
    # (Handling the One-to-One relationship)
    if Appointment.objects.filter(availability=slot).exists():
        messages.error(request, "This slot was just booked by another user.")
        slot.is_active = False # Clean up the database
        slot.save()
        return redirect("public_doctor_profile", pk=slot.doctor.doctorprofile.id)

    # 5. Create the Appointment (Automatically Approved)
    Appointment.objects.create(
        user=request.user,
        doctor=slot.doctor,
        availability=slot,
        status="approved" # Skip doctor acceptance
    )

    # 6. Deactivate the slot globally so it disappears from the profile
    slot.is_active = False
    slot.save()

    # 7. Redirect to Patient Dashboard
    messages.success(request, f"Appointment confirmed with Dr. {slot.doctor.doctorprofile.full_name}!")
    return redirect("appointment")


@login_required
def doctor_profile(request):
    profile = get_object_or_404(DoctorProfile, user=request.user)

    if request.method == "POST":
        if "certificate" in request.FILES:
            profile.certificate = request.FILES["certificate"]
            
        # Update photo only if uploaded
        if request.FILES.get("photo"):
            profile.photo = request.FILES["photo"]

        # Update bio safely
        profile.bio = request.POST.get("bio", "").strip()

        profile.qualifications = request.POST.get("qualifications", "").strip()
        profile.clinic_address = request.POST.get("clinic_address", "").strip()
        profile.languages_spoken = request.POST.get("languages_spoken", "").strip()
        profile.working_hours = request.POST.get("working_hours", "").strip()

        fee = request.POST.get("consultation_fee")
        if fee:
            profile.consultation_fee = fee

        profile.save()
        # 🔥 ADD THIS
        profile.is_profile_complete = profile.check_profile_complete()
        profile.save()

        messages.success(request, "Profile updated successfully")
        return redirect("doctor_profile")

    return render(request, "doctor/doctor_profile.html", {
        "profile": profile
    })


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
    # Patient Dashboard View: Show their own bookings
    user_appointments = Appointment.objects.filter(user=request.user).select_related(
        'doctor__doctorprofile', 'availability'
    ).order_by('-availability__date')
    
    return render(request, "dashboard/appointment.html", {
        "appointments": user_appointments
    })

@login_required
def doctor_dashboard(request):
    if request.user.role != 'doctor':
        return redirect('home')

    profile = request.user.doctorprofile
    
    # 1. Define the 14-day limit
    today = timezone.now().date()
    two_weeks_later = today + timedelta(days=14)

    # 2. Filter the query to only show slots within these 14 days
    availabilities = DoctorAvailability.objects.filter(
        doctor=request.user,
        date__gte=today,
        date__lte=two_weeks_later  # This stops it from showing 1 month
    ).order_by('date', 'start_time')

    show_profile_warning = (profile.is_verified and not profile.is_profile_complete)

    return render(request, 'doctor/doctor_dashboard.html', {
        'availabilities': availabilities,
        'show_profile_warning': show_profile_warning,
        'profile': profile,
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