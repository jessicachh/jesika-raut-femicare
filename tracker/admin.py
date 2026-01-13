from django.contrib import admin
from .models import User, DoctorProfile, UserProfile
from django.core.mail import send_mail
from django.contrib.sites.shortcuts import get_current_site
from django.urls import reverse


@admin.register(DoctorProfile)
class DoctorAdmin(admin.ModelAdmin):
    list_display = (
        'user',
        'specialization',
        'is_verified',      # ✅ direct field
        'experience_years',
        'created_at',
    )

    list_filter = ('is_verified', 'specialization')
    search_fields = ('user__username', 'license_number')

    actions = ['approve_doctors', 'reject_doctors']

    # ✅ ADMIN ACTIONS
    def approve_doctors(self, request, queryset):
        for doctor in queryset:
            doctor.is_verified = True
            doctor.is_rejected = False
            doctor.user.is_verified = True   # allow login
            doctor.user.save()
            doctor.save()                    # 🔥 triggers signal

    approve_doctors.short_description = "Approve selected doctors"

    def reject_doctors(self, request, queryset):
        for doctor in queryset:
            doctor.is_verified = False
            doctor.is_rejected = True
            doctor.user.is_verified = False
            doctor.user.save()
            doctor.save()

    reject_doctors.short_description = "Reject selected doctors"


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'date_of_birth', 'cycle_length', 'last_period_date')


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('username', 'email', 'role', 'is_active', 'is_verified')
