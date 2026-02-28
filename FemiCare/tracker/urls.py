from django.urls import path
from . import views
from django.contrib import admin
from django.contrib.auth import views as auth_views
from .views import (add_availability,toggle_availability,delete_availability,)

urlpatterns = [
    # Public pages
    path('', views.main, name='main'),
    path('home/', views.home, name='home'),
    path('service/', views.service, name='service'),
    path('contact/', views.contact, name='contact'),
    path('terms_and_conditions/', views.terms_and_conditions, name='terms_and_conditions'),
    path('doctor/', views.explore_doctors, name='explore_doctors'),

    # Authentication
    path('signup/', views.signup_view, name='signup'),  
    path('login/', views.login_view, name='login'),    
    path('logout/', views.logout_view, name='logout'),
    path('profile/', views.user_profile, name='user_profile'),

    # Dashboard pages (login required)
    path('dashboard/', views.dashboard_home, name='dashboard_home'),
    path('dashboard/appointments/', views.appointment, name='appointment'),

    # Public doctor profile (USER)
    path('doctors/<int:pk>/', views.public_doctor_profile, name='public_doctor_profile'),
    path("doctor/<int:pk>/review/", views.submit_doctor_review, name="submit_doctor_review"),

    # doctor dashboard
    path('doctor/dashboard/', views.doctor_dashboard, name='doctor_dashboard'),
    path('doctor/appointment/', views.doctor_appointment, name='doctor_appointment'),
    path('doctor/details/', views.doctor_details, name='doctor_details'),
    path('doctor/profile/', views.doctor_profile, name='doctor_profile'),
    path("doctor/availability/add/", add_availability, name="add_availability"),
    path("doctor/availability/toggle/<int:pk>/", toggle_availability, name="toggle_availability"),
    path("doctor/availability/delete/<int:pk>/", delete_availability, name="delete_availability"),
    path("book/<int:slot_id>/", views.book_appointment, name="book_appointment"),
    # We point it to 'doctor_dashboard' since that's where the list lives
    path('doctor/appointment/', views.doctor_appointment, name='doctor_appointment'),
    
    # This allows the "Accept/Reject" buttons to work
    path('appointment/respond/<int:appointment_id>/', views.respond_appointment, name='respond_appointment'),

    path('dashboard/add-cycle-log/', views.add_cycle_log, name='add_cycle_log'),

    # Chat 
    path('chat/<int:appointment_id>/', views.chat_room, name='chat_room'),

    
     path(
        'password-reset/',
        auth_views.PasswordResetView.as_view(
            template_name='registration/password_reset_form.html'
        ),
        name='password_reset'
    ),
    path(
        'password-reset/done/',
        auth_views.PasswordResetDoneView.as_view(
            template_name='registration/password_reset_done.html'
        ),
        name='password_reset_done'
    ),
    path(
        'reset/<uidb64>/<token>/',
        auth_views.PasswordResetConfirmView.as_view(
            template_name='registration/password_reset_confirm.html'
        ),
        name='password_reset_confirm'
    ),
    path(
        'reset/done/',
        auth_views.PasswordResetCompleteView.as_view(
            template_name='registration/password_reset_complete.html'
        ),
        name='password_reset_complete'
    ),
]