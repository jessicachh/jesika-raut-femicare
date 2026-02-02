from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib import messages
from .models import User
from django.contrib.auth.decorators import login_required
from .models import UserProfile, DoctorProfile, DoctorAvailability, Appointment
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

        # Instead of login redirect, show pending page
        return render(request, 'doctor_pending.html')

    return render(request, 'doctor_details.html', {'profile': profile})

@login_required
def public_doctor_profile(request, pk):
    doctor = get_object_or_404(
        DoctorProfile,
        pk=pk,
        is_verified=True,
        is_profile_complete=True
    )

    availabilities = DoctorAvailability.objects.filter(
        doctor=doctor.user,
        date__gte=timezone.now().date(),
        is_active=True
    ).order_by('date', 'start_time')

    return render(request, 'doctor_profile.html', {
        'doctor': doctor,
        'availabilities': availabilities
    })

@login_required
def book_appointment(request, slot_id):
    slot = get_object_or_404(
        DoctorAvailability,
        pk=slot_id,
        is_active=True
    )

    Appointment.objects.create(
        user=request.user,
        doctor=slot.doctor,
        availability=slot
    )

    slot.is_active = False
    slot.save()

    messages.success(request, "Appointment booked successfully!")
    return redirect('dashboard_home')


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

        profile.save()

        messages.success(request, "Profile updated successfully")
        return redirect("doctor_profile")

    return render(request, "doctor/doctor_profile.html", {
        "profile": profile
    })





def logout_view(request):
    auth_logout(request)
    return redirect('login')


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
    return render(request, 'dashboard/appointment.html', {
        'active_page': 'appointments'
    })

@login_required
def doctor_dashboard(request):
    user = request.user

    if user.role != 'doctor':
        return redirect('home')

    profile = user.doctorprofile

    availabilities = DoctorAvailability.objects.filter(
        doctor=user
    ).order_by('-date', '-start_time')

    # 🔔 Profile completion warning logic
    show_profile_warning = (
        profile.is_verified and not profile.is_profile_complete
    )

    return render(request, 'doctor/doctor_dashboard.html', {
        'availabilities': availabilities,
        'show_profile_warning': show_profile_warning,
        'profile': profile,
    })

@login_required
def add_availability(request):
    if request.method == "POST":
        date = request.POST.get("date")
        start_time = request.POST.get("start_time")
        end_time = request.POST.get("end_time")

        date_obj = datetime.strptime(date, "%Y-%m-%d").date()
        start_time_obj = datetime.strptime(start_time, "%H:%M").time()
        end_time_obj = datetime.strptime(end_time, "%H:%M").time()

        start_dt = timezone.make_aware(
            datetime.combine(date_obj, start_time_obj)
        )
        end_dt = timezone.make_aware(
            datetime.combine(date_obj, end_time_obj)
        )

        # Past date/time not allowed
        if start_dt < timezone.now():
            messages.error(request, "Cannot add availability in the past.")
            return redirect("doctor_dashboard")

        # End before start
        if start_time_obj >= end_time_obj:
            messages.error(request, "End time must be after start time.")
            return redirect("doctor_dashboard")

        # Overlapping check
        overlap = DoctorAvailability.objects.filter(
            doctor=request.user,
            date=date_obj,
            start_time__lt=end_time_obj,
            end_time__gt=start_time_obj,
            is_active=True
        )

        if overlap.exists():
            messages.error(request, "This time slot overlaps an existing availability.")
            return redirect("doctor_dashboard")

        DoctorAvailability.objects.create(
            doctor=request.user,
            date=date_obj,
            start_time=start_time_obj,
            end_time=end_time_obj
        )

        messages.success(request, "Availability added successfully.")
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

            cycle.save()

            # Save trigger in session
            request.session["show_prediction"] = True
            request.session["last_cycle_id"] = cycle.id

            return redirect("dashboard_home")