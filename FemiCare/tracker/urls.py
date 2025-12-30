from django.urls import path
from . import views

urlpatterns = [
    # Public pages
    path('', views.main, name='main'),
    path('home/', views.home, name='home'),
    path('service/', views.service, name='service'),
    path('contact/', views.contact, name='contact'),

    # Authentication
    path('signup/', views.signup_view, name='signup'),  # Updated view
    path('login/', views.login_view, name='login'),     # Updated view
    path('logout/', views.logout_view, name='logout'),  # Added logout
    path('profile/', views.user_profile, name='user_profile'),

    # Dashboard pages (login required)
    path('dashboard/', views.dashboard_home, name='dashboard_home'),
    path('dashboard/appointments/', views.appointment, name='appointment'),

    # Optional: doctor dashboard
    path('doctor/dashboard/', views.doctor_dashboard, name='doctor_dashboard'),
    path('doctor/details/', views.doctor_details, name='doctor_details'),
]
