from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.html import format_html
from django.utils import timezone

from .models import (
    Appointment,
    ChatMessage,
    Conversation,
    CycleLog,
    DoctorAvailability,
    DoctorPaymentDetails,
    DoctorProfile,
    DoctorReview,
    EmergencyRequest,
    HealthLog,
    MoodEntry,
    Notification,
    Payment,
    PayoutBatch,
    PeriodCheckIn,
    PredictionFeedback,
    ResourceCategory,
    ResourceItem,
    SymptomLog,
    TwoFactorCode,
    User,
    UserDocument,
    UserProfile,
)


admin.site.site_header = 'FemiCare Admin Portal'
admin.site.site_title = 'FemiCare Admin'
admin.site.index_title = 'Administration Dashboard'
admin.site.empty_value_display = '-'
admin.site.enable_nav_sidebar = False


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = (
        'username',
        'email',
        'role',
        'is_verified',
        'is_two_factor_enabled',
        'is_active',
        'is_staff',
        'date_joined',
    )
    list_filter = ('role', 'is_verified', 'is_two_factor_enabled', 'is_active', 'is_staff', 'is_superuser')
    search_fields = ('username', 'email', 'first_name', 'last_name')
    ordering = ('-date_joined',)
    list_per_page = 25

    fieldsets = BaseUserAdmin.fieldsets + (
        (
            'FemiCare Account Settings',
            {
                'fields': (
                    'role',
                    'is_verified',
                    'has_accepted_terms',
                    'is_two_factor_enabled',
                    'two_factor_enabled_at',
                    'is_password_strong',
                )
            },
        ),
    )

    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        (
            'FemiCare Account Settings',
            {
                'classes': ('wide',),
                'fields': ('email', 'role', 'is_verified', 'is_two_factor_enabled', 'is_active', 'is_staff'),
            },
        ),
    )


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = (
        'user',
        'phone_number',
        'cycle_length',
        'last_period_date',
        'height_cm',
        'weight_kg',
        'has_accepted_terms',
        'created_at',
    )
    list_filter = ('has_accepted_terms', 'created_at')
    search_fields = ('user__username', 'user__email', 'phone_number', 'address')
    ordering = ('-created_at',)
    list_select_related = ('user',)


@admin.register(DoctorProfile)
class DoctorProfileAdmin(admin.ModelAdmin):
    list_display = (
        'full_name',
        'user',
        'specialization',
        'license_number',
        'is_verified',
        'is_profile_complete',
        'consultation_fee',
        'view_certificate',
        'created_at',
    )
    list_filter = ('is_verified', 'is_profile_complete', 'specialization', 'created_at')
    search_fields = ('full_name', 'user__username', 'user__email', 'license_number', 'hospital_name', 'location')
    list_select_related = ('user',)
    ordering = ('-created_at',)
    actions = ('approve_doctors', 'reject_doctors')

    def view_certificate(self, obj):
        if obj.certificate:
            return format_html('<a href="{}" target="_blank" rel="noopener">View Docs</a>', obj.certificate.url)
        return 'No File'

    view_certificate.short_description = 'Certificate'

    @admin.action(description='Approve selected doctors')
    def approve_doctors(self, request, queryset):
        count = queryset.count()
        for profile in queryset:
            profile.is_verified = True
            profile.save(update_fields=['is_verified'])

            profile.user.is_verified = True
            profile.user.save(update_fields=['is_verified'])

        self.message_user(request, f'{count} doctor(s) approved and verified.')

    @admin.action(description='Reject selected doctors')
    def reject_doctors(self, request, queryset):
        count = queryset.count()
        for profile in queryset:
            profile.is_verified = False
            profile.save(update_fields=['is_verified'])

            profile.user.is_verified = False
            profile.user.save(update_fields=['is_verified'])

        self.message_user(request, f'{count} doctor(s) rejected.')


@admin.register(CycleLog)
class CycleLogAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'user',
        'last_period_start',
        'length_of_cycle',
        'length_of_menses',
        'mean_bleeding_intensity',
        'unusual_bleeding',
        'predicted_next_period',
        'created_at',
    )
    list_filter = ('unusual_bleeding', 'is_confirmed', 'mean_bleeding_intensity', 'created_at')
    search_fields = ('user__username', 'user__email')
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)
    list_select_related = ('user',)


@admin.register(MoodEntry)
class MoodEntryAdmin(admin.ModelAdmin):
    list_display = ('user', 'mood', 'date', 'created_at')
    list_filter = ('mood', 'date')
    search_fields = ('user__username', 'user__email')
    date_hierarchy = 'date'
    ordering = ('-date', '-created_at')
    list_select_related = ('user',)


@admin.register(SymptomLog)
class SymptomLogAdmin(admin.ModelAdmin):
    list_display = ('user', 'symptom', 'source', 'date', 'cycle_log', 'created_at')
    list_filter = ('source', 'date', 'symptom')
    search_fields = ('user__username', 'user__email', 'symptom')
    date_hierarchy = 'date'
    ordering = ('-date', '-created_at')
    list_select_related = ('user', 'cycle_log')


@admin.register(PeriodCheckIn)
class PeriodCheckInAdmin(admin.ModelAdmin):
    list_display = ('user', 'cycle_log', 'pain_level', 'blood_flow', 'created_at')
    list_filter = ('pain_level', 'blood_flow', 'created_at')
    search_fields = ('user__username', 'user__email')
    ordering = ('-created_at',)
    list_select_related = ('user', 'cycle_log')


@admin.register(PredictionFeedback)
class PredictionFeedbackAdmin(admin.ModelAdmin):
    list_display = ('user', 'cycle_log', 'predicted_date', 'actual_date', 'is_correct', 'created_at')
    list_filter = ('is_correct', 'created_at')
    search_fields = ('user__username', 'user__email')
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)
    list_select_related = ('user', 'cycle_log')


@admin.register(HealthLog)
class HealthLogAdmin(admin.ModelAdmin):
    list_display = ('user', 'height_cm', 'weight_kg', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('user__username', 'user__email')
    ordering = ('-created_at',)
    list_select_related = ('user',)


@admin.register(UserDocument)
class UserDocumentAdmin(admin.ModelAdmin):
    list_display = ('user', 'original_name', 'uploaded_at')
    list_filter = ('uploaded_at',)
    search_fields = ('user__username', 'user__email', 'original_name')
    ordering = ('-uploaded_at',)
    list_select_related = ('user',)


@admin.register(DoctorAvailability)
class DoctorAvailabilityAdmin(admin.ModelAdmin):
    list_display = ('doctor', 'date', 'start_time', 'end_time', 'is_active', 'created_at')
    list_filter = ('is_active', 'date', 'created_at')
    search_fields = ('doctor__username', 'doctor__email')
    date_hierarchy = 'date'
    ordering = ('-date', '-start_time')
    list_select_related = ('doctor',)


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'doctor', 'status', 'availability', 'created_at', 'responded_at', 'completed_at')
    list_filter = ('status', 'created_at', 'responded_at', 'completed_at')
    search_fields = ('user__username', 'user__email', 'doctor__username', 'doctor__email')
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)
    list_select_related = ('user', 'doctor', 'availability')


@admin.register(DoctorReview)
class DoctorReviewAdmin(admin.ModelAdmin):
    list_display = ('doctor', 'patient', 'rating', 'created_at')
    list_filter = ('rating', 'created_at')
    search_fields = ('doctor__full_name', 'doctor__user__username', 'patient__username', 'patient__email')
    ordering = ('-created_at',)
    list_select_related = ('doctor', 'patient')


@admin.register(EmergencyRequest)
class EmergencyRequestAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'status', 'assigned_doctor', 'assigned_slot', 'created_at', 'updated_at')
    list_filter = ('status', 'created_at', 'updated_at')
    search_fields = ('user__username', 'user__email', 'assigned_doctor__username', 'assigned_doctor__email', 'reason')
    ordering = ('-created_at',)
    list_select_related = ('user', 'assigned_doctor', 'assigned_slot')


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'title', 'type', 'is_read', 'target_url', 'created_at')
    list_filter = ('type', 'is_read', 'created_at')
    search_fields = ('user__username', 'user__email', 'title', 'message')
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)
    list_select_related = ('user',)


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = (
        'room_name',
        'doctor',
        'patient',
        'last_message_preview',
        'last_message_time',
        'unread_count_doctor',
        'unread_count_patient',
    )
    search_fields = ('room_name', 'doctor__username', 'doctor__email', 'patient__username', 'patient__email')
    ordering = ('-last_message_time',)
    list_select_related = ('doctor', 'patient')

    def last_message_preview(self, obj):
        if not obj.last_message:
            return '-'
        return (obj.last_message[:60] + '...') if len(obj.last_message) > 60 else obj.last_message

    last_message_preview.short_description = 'Last Message'


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ('room_name', 'sender', 'short_message', 'is_note', 'is_read', 'timestamp')
    list_filter = ('is_note', 'is_read', 'timestamp')
    search_fields = ('room_name', 'sender__username', 'sender__email', 'message')
    ordering = ('-timestamp',)
    list_select_related = ('sender',)

    def short_message(self, obj):
        if not obj.message:
            return '-'
        return (obj.message[:60] + '...') if len(obj.message) > 60 else obj.message

    short_message.short_description = 'Message'


@admin.register(TwoFactorCode)
class TwoFactorCodeAdmin(admin.ModelAdmin):
    list_display = ('user', 'purpose', 'code', 'expires_at', 'used_at', 'created_at')
    list_filter = ('purpose', 'created_at', 'expires_at', 'used_at')
    search_fields = ('user__username', 'user__email', 'code')
    ordering = ('-created_at',)
    list_select_related = ('user',)


@admin.register(DoctorPaymentDetails)
class DoctorPaymentDetailsAdmin(admin.ModelAdmin):
    list_display = ('doctor', 'esewa_id', 'consultation_fee', 'is_payment_setup_complete', 'created_at', 'updated_at')
    list_filter = ('is_payment_setup_complete', 'created_at')
    search_fields = ('doctor__username', 'doctor__email', 'esewa_id')
    ordering = ('-updated_at',)
    list_select_related = ('doctor',)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'user',
        'appointment',
        'amount',
        'transaction_id',
        'commission_amount',
        'doctor_earning',
        'status',
        'payout_status',
        'payout_batch',
        'created_at',
    )
    list_filter = ('status', 'payout_status', 'created_at')
    search_fields = ('user__username', 'user__email', 'appointment__id')
    ordering = ('-created_at',)
    list_select_related = ('user', 'appointment')
    actions = ('mark_payout_processing', 'mark_payout_paid')

    @admin.action(description='Mark payout as processing')
    def mark_payout_processing(self, request, queryset):
        updated = queryset.update(payout_status='processing')
        self.message_user(request, f'{updated} payment(s) marked as processing.')

    @admin.action(description='Mark payout as paid')
    def mark_payout_paid(self, request, queryset):
        now = timezone.now()
        updated = queryset.update(payout_status='paid', payout_paid_at=now)
        self.message_user(request, f'{updated} payment(s) marked as paid.')


@admin.register(PayoutBatch)
class PayoutBatchAdmin(admin.ModelAdmin):
    list_display = (
        'reference',
        'frequency',
        'period_start',
        'period_end',
        'status',
        'total_amount',
        'total_doctors',
        'processed_by',
        'created_at',
    )
    list_filter = ('frequency', 'status', 'created_at')
    search_fields = ('reference',)
    ordering = ('-created_at',)


@admin.register(ResourceCategory)
class ResourceCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'icon_class', 'sort_order', 'is_active', 'updated_at')
    list_filter = ('is_active', 'created_at', 'updated_at')
    search_fields = ('name', 'slug', 'description')
    prepopulated_fields = {'slug': ('name',)}
    ordering = ('sort_order', 'name')


@admin.register(ResourceItem)
class ResourceItemAdmin(admin.ModelAdmin):
    list_display = (
        'title',
        'category',
        'resource_type',
        'source_name',
        'sort_order',
        'is_active',
        'updated_at',
    )
    list_filter = ('resource_type', 'is_active', 'category', 'created_at', 'updated_at')
    search_fields = ('title', 'summary', 'source_name', 'external_url', 'category__name')
    list_select_related = ('category',)
    ordering = ('category__sort_order', 'sort_order', 'title')