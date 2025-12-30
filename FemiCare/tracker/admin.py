from django.contrib import admin
from .models import User, DoctorProfile, UserProfile


@admin.register(DoctorProfile)
class DoctorAdmin(admin.ModelAdmin):
    list_display = (
        'user',
        'specialization',
        'get_is_verified',  # ✅ display verification status
        'experience_years',
        'created_at',
    )

    list_filter = ('user__is_verified', 'specialization')
    search_fields = ('user__username', 'license_number')

    actions = ['approve_doctors', 'reject_doctors']

    # Custom display for is_verified
    def get_is_verified(self, obj):
        return obj.user.is_verified
    get_is_verified.boolean = True
    get_is_verified.short_description = 'Verified'

    # Actions for admin
    def approve_doctors(self, request, queryset):
        for doctor in queryset:
            doctor.user.is_verified = True
            doctor.user.save()
    approve_doctors.short_description = "Approve selected doctors"

    def reject_doctors(self, request, queryset):
        for doctor in queryset:
            doctor.user.is_verified = False
            doctor.user.save()
    reject_doctors.short_description = "Reject selected doctors"


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'date_of_birth', 'cycle_length', 'last_period_date')


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('username', 'email', 'role', 'is_active')
