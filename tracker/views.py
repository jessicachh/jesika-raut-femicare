from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib import messages
from .models import User
from django.contrib.auth.decorators import login_required
from .models import UserProfile, DoctorProfile


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

        messages.success(request, "Account created successfully. Please login.")
        return redirect('login')   # redirect only

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
        profile.specialization = request.POST.get('specialization')
        profile.license_number = request.POST.get('license')
        profile.experience_years = request.POST.get('experience_years')
        if request.FILES.get('certificate'):
            profile.certificate = request.FILES['certificate']
        profile.save()

        # Instead of login redirect, show pending page
        return render(request, 'doctor_pending.html')

    return render(request, 'doctor_details.html', {'profile': profile})






def logout_view(request):
    auth_logout(request)
    return redirect('login')


# -----------------------------
# Dashboard views
# -----------------------------
from django.contrib.auth.decorators import login_required

@login_required
def dashboard_home(request):
    if request.user.role != 'user':
        return redirect('login')
    return render(request, 'dashboard/first.html')

@login_required
def appointment(request):
    return render(request, 'dashboard/appointment.html', {
        'active_page': 'appointments'
    })

@login_required
def doctor_dashboard(request):
    if request.user.role != 'doctor':
        return redirect('login')
    return render(request, 'dashboard/doctor_dashboard.html')