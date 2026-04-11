from django.urls import path
from . import views
from django.contrib import admin
from django.contrib.auth import views as auth_views
from .views import (add_availability, toggle_availability,delete_availability,)

urlpatterns = [
    # Public pages
    path('', views.main, name='main'),
    path('home/', views.home, name='home'),
    path('service/', views.service, name='service'),
    path('contact/', views.contact, name='contact'),
    path('resources/', views.resources, name='resources'),
    path('terms_and_conditions/', views.terms_and_conditions, name='terms_and_conditions'),
    path('doctor/', views.explore_doctors, name='explore_doctors'),

    # Authentication
    path('signup/', views.signup_view, name='signup'),  
    path('auth/verify-signup-email/', views.verify_signup_email, name='verify_signup_email'),
    path('auth/verify-signup-email/resend/', views.resend_signup_email_code, name='resend_signup_email_code'),
    path('login/', views.login_view, name='login'),    
    path('logout/', views.logout_view, name='logout'),
    path('auth/post-login/', views.post_auth_redirect, name='post_auth_redirect'),
    path('auth/2fa/setup/', views.two_factor_setup_prompt, name='two_factor_setup_prompt'),
    path('auth/2fa/setup/verify/', views.two_factor_setup_verify, name='two_factor_setup_verify'),
    path('auth/2fa/setup/resend/', views.two_factor_setup_resend, name='two_factor_setup_resend'),
    path('auth/2fa/login/verify/', views.two_factor_login_verify, name='two_factor_login_verify'),
    path('auth/2fa/login/resend/', views.two_factor_login_resend, name='two_factor_login_resend'),
    path('dashboard/settings/2fa/enable/', views.enable_two_factor, name='enable_two_factor'),
    path('dashboard/settings/2fa/disable/', views.disable_two_factor, name='disable_two_factor'),
    path('dashboard/settings/2fa/verify/', views.two_factor_settings_verify, name='two_factor_settings_verify'),
    path('profile/', views.user_profile, name='user_profile'),

    # Dashboard pages (login required)
    path('dashboard/', views.dashboard_home, name='dashboard_home'),
    path('dashboard/appointments/', views.appointment, name='appointment'),
    path('dashboard/profile/', views.profile_view, name='dashboard_profile'),
    path('dashboard/profile/documents/upload/', views.upload_user_documents, name='upload_user_documents'),
    path('dashboard/settings/', views.settings_view, name='dashboard_settings'),
    path('dashboard/change-password/', views.change_password, name='change_password'),
    path('dashboard/verify-email-code/', views.verify_email_code, name='verify_email_code'),
    path('dashboard/delete-account/', views.delete_account, name='delete_account'),
    path('dashboard/mood-checkin/', views.submit_mood_checkin, name='submit_mood_checkin'),
    path('dashboard/prediction-feedback/', views.submit_prediction_feedback, name='submit_prediction_feedback'),
    path('dashboard/log-period-start/', views.log_period_start_view, name='log_period_start'),
    path('dashboard/end-period/', views.end_period_view, name='end_period'),
    path('dashboard/reports/', views.dashboard_reports, name='dashboard_reports'),
    path('dashboard/reports/export-pdf/', views.export_reports_pdf, name='export_reports_pdf'),
    path('dashboard/period-checkin/', views.submit_period_checkin, name='submit_period_checkin'),
    path('dashboard/save-symptoms/', views.save_symptoms, name='save_symptoms'),
    path('dashboard/emergency/request/', views.submit_emergency_request, name='submit_emergency_request'),
    path('notifications/', views.get_notifications, name='get_notifications'),
    path('notifications/mark-read/<int:notification_id>/', views.mark_as_read, name='mark_as_read'),
    path('notifications/mark-all-read/', views.mark_all_as_read, name='mark_all_as_read'),

    # Public doctor profile (USER)
    path('doctors/<int:pk>/', views.public_doctor_profile, name='public_doctor_profile'),
    path("doctor/<int:pk>/review/", views.submit_doctor_review, name="submit_doctor_review"),

    # doctor dashboard
    path('doctor/dashboard/', views.doctor_dashboard, name='doctor_dashboard'),
    path('doctor/appointment/', views.doctor_appointment, name='doctor_appointment'),
    path('doctor/chat/', views.doctor_chat_hub, name='doctor_chat_hub'),
    path('doctor/details/', views.doctor_details, name='doctor_details'),
    path('doctor/profile/', views.doctor_profile, name='doctor_profile'),
    path('doctor/settings/', views.doctor_settings_view, name='doctor_settings'),
    path('doctor/settings/change-password/', views.doctor_change_password, name='doctor_change_password'),
    path('doctor/settings/change-email/', views.doctor_change_email, name='doctor_change_email'),
    path('doctor/settings/verify-email-code/', views.doctor_verify_email_code, name='doctor_verify_email_code'),
    path('doctor/settings/delete-account/', views.doctor_delete_account, name='doctor_delete_account'),
    path("doctor/availability/add/", add_availability, name="add_availability"),
    path("doctor/availability/toggle/<int:pk>/", toggle_availability, name="toggle_availability"),
    path("doctor/availability/delete/<int:pk>/", delete_availability, name="delete_availability"),
    path("book/<int:slot_id>/", views.book_appointment, name="book_appointment"),
    # We point it to 'doctor_dashboard' since that's where the list lives
    path('doctor/appointment/', views.doctor_appointment, name='doctor_appointment'),
    
    # This allows the "Accept/Reject" buttons to work
    path('appointment/respond/<int:appointment_id>/', views.respond_appointment, name='respond_appointment'),
    path('doctor/emergency/accept/<int:emergency_request_id>/', views.accept_emergency_request, name='accept_emergency_request'),

    path('dashboard/add-cycle-log/', views.add_cycle_log, name='add_cycle_log'),

    # Chat 
    path('chat/<int:appointment_id>/', views.chat_room, name='chat_room'),
    path(
        'chat/<int:appointment_id>/documents/<int:document_id>/',
        views.consultation_patient_document,
        name='consultation_patient_document'
    ),
    path(
        'chat/<int:appointment_id>/files/<int:message_id>/',
        views.consultation_chat_file,
        name='consultation_chat_file'
    ),
    path('upload-chat-file/', views.upload_chat_file, name='upload_chat_file'),
    path('api/conversations/', views.get_conversations, name='get_conversations'),
    
    # Chat interface page + compatibility redirect
    path('dashboard/chat/', views.dashboard_chat, name='dashboard_chat'),
    path('dashboard/chat/<int:appointment_id>/', views.dashboard_chat_redirect, name='dashboard_chat_redirect'),
    path('api/conversation/<int:appointment_id>/messages/', views.get_message_history, name='get_message_history'),
    path('api/message/send/', views.send_message, name='send_message'),
    path('api/message/upload/', views.upload_message_file, name='upload_message_file'),
    path('api/conversation/<int:appointment_id>/mark-read/', views.mark_conversation_as_read, name='mark_conversation_as_read'),

    
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
        views.StrongPasswordResetConfirmView.as_view(),
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