from django.contrib import admin
from .models import User, DoctorProfile, UserProfile
from django.core.mail import send_mail
from django.contrib.sites.shortcuts import get_current_site
from django.urls import reverse
from django.utils.html import format_html

@admin.register(DoctorProfile)
class DoctorAdmin(admin.ModelAdmin):
    list_display = (
        'full_name', 
        'specialization',
        'is_verified',      
        'is_profile_complete', 
        'view_certificate', # Added helper for easy verification
        'created_at',
    )
    list_filter = ('is_verified', 'is_profile_complete', 'specialization')
    search_fields = ('full_name', 'user__username', 'license_number')
    actions = ['approve_doctors', 'reject_doctors']

    def view_certificate(self, obj):
        if obj.certificate:
            return format_html('<a href="{}" target="_blank">View Docs</a>', obj.certificate.url)
        return "No File"
    view_certificate.short_description = "Certificate"

    def approve_doctors(self, request, queryset):
        count = queryset.count()
        for profile in queryset:
            profile.is_verified = True
            profile.save()
            
            # Sync with the User model
            user = profile.user
            user.is_verified = True
            user.save()
            
        self.message_user(request, f"{count} doctors approved and verified.")

    def reject_doctors(self, request, queryset):
        count = queryset.count()
        for profile in queryset:
            profile.is_verified = False
            profile.save()
            
            user = profile.user
            user.is_verified = False
            user.save()
            
        self.message_user(request, f"{count} doctors rejected.")


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'date_of_birth', 'cycle_length', 'last_period_date')


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('username', 'email', 'role', 'is_active', 'is_verified')