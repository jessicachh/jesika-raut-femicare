from django import forms
from django.utils import timezone
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .models import CycleLog, DoctorProfile, UserProfile, User


MIN_HEIGHT_CM = 50
MAX_HEIGHT_CM = 250
MIN_WEIGHT_KG = 2
MAX_WEIGHT_KG = 300


def is_height_valid(value):
    if value is None:
        return False
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return False
    return MIN_HEIGHT_CM <= numeric_value <= MAX_HEIGHT_CM


def is_weight_valid(value):
    if value is None:
        return False
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return False
    return MIN_WEIGHT_KG <= numeric_value <= MAX_WEIGHT_KG


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def clean(self, data, initial=None):
        single_file_clean = super().clean

        if isinstance(data, (list, tuple)):
            return [single_file_clean(item, initial) for item in data]

        if data:
            return [single_file_clean(data, initial)]

        return []

class DoctorProfileForm(forms.ModelForm):
    class Meta:
        model = DoctorProfile
        fields = [
            'full_name',
            'specialization',
            'license_number',
            'experience_years',
            'hospital_name',
            'location',
            'certificate',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'

        for field_name in ['full_name', 'specialization', 'license_number', 'experience_years', 'location', 'certificate']:
            self.fields[field_name].required = True

        self.fields['experience_years'].widget.attrs.update({'min': '0', 'step': '1'})

    def clean_full_name(self):
        return (self.cleaned_data.get('full_name') or '').strip()

    def clean_specialization(self):
        return (self.cleaned_data.get('specialization') or '').strip()

    def clean_hospital_name(self):
        return (self.cleaned_data.get('hospital_name') or '').strip()

    def clean_location(self):
        return (self.cleaned_data.get('location') or '').strip()

    def clean_license_number(self):
        license_number = (self.cleaned_data.get('license_number') or '').strip().upper()
        if not license_number:
            return license_number

        existing = DoctorProfile.objects.filter(license_number__iexact=license_number)
        if self.instance and self.instance.pk:
            existing = existing.exclude(pk=self.instance.pk)

        if existing.exists():
            raise forms.ValidationError('A doctor with this license number already exists.')

        return license_number


class CycleLogForm(forms.ModelForm):
    class Meta:
        model = CycleLog
        fields = [
            'last_period_start',
            'length_of_cycle',
            'length_of_menses',
            'mean_bleeding_intensity',
            'total_menses_score',
            'unusual_bleeding',
        ]

        labels = {
            'last_period_start': 'When did your last period start?',
            'length_of_cycle': 'Cycle Length (days)',
            'length_of_menses': 'How many days did your period bleeding last?',
            'mean_bleeding_intensity': 'How heavy was your period flow on most days?',
            'total_menses_score': 'How painful was your period?',
            'unusual_bleeding': 'Any signs of unusual bleeding?',
        }

        help_texts = {
            "last_period_start": "Select the first day of bleeding.",
            "length_of_cycle": "Typical days from one period start to the next.",
            "length_of_menses": "From first bleeding day to when it stopped.",
            "unusual_bleeding": "Bleeding between periods or irregular bleeding.",
        }

        widgets = {
            'last_period_start': forms.DateInput(attrs={'type': 'date'}),
            'unusual_bleeding': forms.Select(
                choices=[
                    (False, 'No'),
                    (True, 'Yes'),
                ]
            ),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        last_log = kwargs.pop('last_log', None)
        super().__init__(*args, **kwargs)

        if user and last_log is None:
            last_log = (
                CycleLog.objects
                .filter(user=user)
                .order_by('-created_at')
                .first()
            )

        if last_log:
            self.fields['length_of_cycle'].initial = last_log.length_of_cycle
            self.fields['length_of_menses'].initial = last_log.length_of_menses
            self.fields['mean_bleeding_intensity'].initial = last_log.mean_bleeding_intensity
            self.fields['total_menses_score'].initial = last_log.total_menses_score
            self.fields['unusual_bleeding'].initial = last_log.unusual_bleeding

    def clean_length_of_cycle(self):
        value = self.cleaned_data.get('length_of_cycle')
        if value is None:
            return value

        if value < 21 or value > 35:
            raise forms.ValidationError(
                "According to the American College of Obstetricians and Gynecologists, a cycle length of 21 to 35 days is within the normal range. If your average cycle is below 21 days or above 35 days, you may have irregular cycles, so speak to a health care professional for more information."
            )
        return value

    def clean_length_of_menses(self):
        value = self.cleaned_data.get('length_of_menses')
        if value is None:
            return value

        if value < 2 or value > 7:
            raise forms.ValidationError(
                "According to the American College of Obstetricians and Gynecologists, a typical period lasts between two to seven days. If your period lasts less than two days or more than seven days, you may be experiencing abnormal bleeding. Speak to a health care professional for more information."
            )
        return value


class PeriodStartLogForm(forms.Form):
    period_start_date = forms.DateField(
        label='Period Start Date',
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
    )

    def clean_period_start_date(self):
        value = self.cleaned_data.get('period_start_date')
        if value and value > timezone.localdate():
            raise forms.ValidationError('You cannot log a future period start date.')
        return value


class PeriodLogForm(forms.Form):
    start_date = forms.DateField(
        label='Period Start Date',
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
    )
    end_date = forms.DateField(
        label='Period End Date',
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
    )

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')
        today = timezone.localdate()

        if not start_date:
            return cleaned_data

        if start_date > today:
            self.add_error('start_date', 'Start date cannot be in the future.')
            return cleaned_data

        if end_date:
            if end_date < start_date:
                self.add_error('end_date', 'End date cannot be before start date.')
            if end_date > today:
                self.add_error('end_date', 'End date cannot be in the future.')

        is_recent_period = (today - start_date).days <= 3

        if is_recent_period and end_date:
            self.add_error('end_date', 'For current or recent periods, leave end date empty and use End Period later.')

        if not is_recent_period and not end_date:
            self.add_error('end_date', 'Please provide end date for past periods older than 3 days.')

        return cleaned_data


class EndPeriodForm(forms.Form):
    end_date = forms.DateField(
        label='Period End Date',
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
    )

    def __init__(self, *args, **kwargs):
        self.start_date = kwargs.pop('start_date', None)
        super().__init__(*args, **kwargs)

    def clean_end_date(self):
        end_date = self.cleaned_data.get('end_date')
        today = timezone.localdate()

        if not end_date:
            return end_date

        if end_date > today:
            raise forms.ValidationError('End date cannot be in the future.')

        if self.start_date and end_date < self.start_date:
            raise forms.ValidationError('End date cannot be before start date.')

        return end_date


class UserProfileForm(forms.ModelForm):
    full_name = forms.CharField(max_length=150, required=True)

    class Meta:
        model = UserProfile
        fields = [
            'full_name',
            'date_of_birth',
            'profile_picture',
            'height_cm',
            'weight_kg',
            'address',
        ]
        widgets = {
            'phone_number': forms.TextInput(attrs={'placeholder': 'Enter phone number'}),
            'date_of_birth': forms.DateInput(attrs={'type': 'date'}),
            'address': forms.TextInput(attrs={'placeholder': 'Enter address'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user')
        last_log = kwargs.pop('last_log', None)
        super().__init__(*args, **kwargs)

        self.fields['full_name'].initial = self.user.get_full_name().strip() or self.user.username

        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'

        self.fields['profile_picture'].widget.attrs['class'] = 'form-control'

        self.fields['date_of_birth'].required = True
        self.fields['height_cm'].required = True
        self.fields['weight_kg'].required = True

        self.fields['date_of_birth'].widget.attrs['max'] = timezone.localdate().isoformat()
        self.fields['height_cm'].widget.attrs.update({
            'type': 'number',
            'min': str(MIN_HEIGHT_CM),
            'max': str(MAX_HEIGHT_CM),
            'step': '0.1',
        })
        self.fields['weight_kg'].widget.attrs.update({
            'type': 'number',
            'min': str(MIN_WEIGHT_KG),
            'max': str(MAX_WEIGHT_KG),
            'step': '0.1',
        })

        if last_log:
            self.fields['height_cm'].initial = last_log.height_cm
            self.fields['weight_kg'].initial = last_log.weight_kg

    def clean_date_of_birth(self):
        dob = self.cleaned_data.get('date_of_birth')
        if dob and dob > timezone.localdate():
            raise forms.ValidationError('Date of birth cannot be in the future.')
        return dob

    def clean(self):
        cleaned_data = super().clean()
        height_cm = cleaned_data.get('height_cm')
        weight_kg = cleaned_data.get('weight_kg')

        if height_cm is None or weight_kg is None:
            return cleaned_data

        if not is_height_valid(height_cm) or not is_weight_valid(weight_kg):
            raise forms.ValidationError('Please enter a valid height and weight.')

        return cleaned_data

    def save(self, commit=True):
        profile = super().save(commit=False)

        full_name = self.cleaned_data['full_name'].strip()
        name_parts = full_name.split(maxsplit=1)
        self.user.first_name = name_parts[0]
        self.user.last_name = name_parts[1] if len(name_parts) > 1 else ''

        if commit:
            self.user.save()
            profile.save()

        return profile


class AccountSettingsForm(forms.ModelForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = UserProfile
        fields = ['email', 'phone_number']
        widgets = {
            'phone_number': forms.TextInput(attrs={'placeholder': 'Enter phone number'}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user')
        super().__init__(*args, **kwargs)

        self.fields['email'].initial = self.user.email

        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'

    def save(self, commit=True, update_email=True):
        profile = super().save(commit=False)

        if commit:
            if update_email:
                self.user.email = self.cleaned_data['email']
                self.user.save(update_fields=['email'])
            profile.save()

        return profile


class DoctorEmailChangeRequestForm(forms.Form):
    email = forms.EmailField(required=True)
    current_password = forms.CharField(
        required=True,
        widget=forms.PasswordInput,
        label='Current Password',
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user')
        super().__init__(*args, **kwargs)

        self.fields['email'].initial = self.user.email
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()
        if email == (self.user.email or '').strip().lower():
            raise forms.ValidationError('Please enter a different email address.')

        if User.objects.filter(email=email).exclude(pk=self.user.pk).exists():
            raise forms.ValidationError('This email is already in use by another account.')
        return email

    def clean_current_password(self):
        current_password = self.cleaned_data.get('current_password')
        if not self.user.check_password(current_password):
            raise forms.ValidationError('Current password is incorrect.')
        return current_password


class DeleteAccountForm(forms.Form):
    confirm_text = forms.CharField(
        required=True,
        label='Type DELETE to confirm',
    )
    current_password = forms.CharField(
        required=True,
        widget=forms.PasswordInput,
        label='Current Password',
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user')
        super().__init__(*args, **kwargs)

        self.fields['confirm_text'].widget.attrs['class'] = 'form-control'
        self.fields['current_password'].widget.attrs['class'] = 'form-control'

    def clean_confirm_text(self):
        value = (self.cleaned_data.get('confirm_text') or '').strip()
        if value != 'DELETE':
            raise forms.ValidationError('Please type DELETE exactly to confirm account deletion.')
        return value

    def clean_current_password(self):
        current_password = self.cleaned_data.get('current_password')
        if not self.user.check_password(current_password):
            raise forms.ValidationError('Current password is incorrect.')
        return current_password


class RegistrationForm(forms.Form):
    username = forms.CharField(max_length=150)
    email = forms.EmailField()
    password = forms.CharField(widget=forms.PasswordInput)
    confirm_password = forms.CharField(widget=forms.PasswordInput)
    role = forms.ChoiceField(choices=User.ROLE_CHOICES, initial='user')

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError('Email already exists.')
        return email

    def clean_username(self):
        username = (self.cleaned_data.get('username') or '').strip()
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError('Username already exists.')
        return username

    def clean_password(self):
        password = self.cleaned_data.get('password')
        try:
            validate_password(password)
        except ValidationError as exc:
            raise forms.ValidationError(list(exc.messages))
        return password

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get('password')
        confirm_password = cleaned.get('confirm_password')
        if password and confirm_password and password != confirm_password:
            self.add_error('confirm_password', 'Passwords do not match.')
        return cleaned


class StrongPasswordChangeForm(PasswordChangeForm):
    def clean_new_password2(self):
        new_password2 = super().clean_new_password2()
        try:
            validate_password(new_password2, self.user)
        except ValidationError as exc:
            raise forms.ValidationError(list(exc.messages))
        return new_password2


class StrongSetPasswordForm(SetPasswordForm):
    def clean_new_password2(self):
        new_password2 = super().clean_new_password2()
        try:
            validate_password(new_password2, self.user)
        except ValidationError as exc:
            raise forms.ValidationError(list(exc.messages))
        return new_password2


class EmailVerificationForm(forms.Form):
    code = forms.CharField(max_length=6, min_length=6)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['code'].widget.attrs.update(
            {
                'class': 'form-control',
                'placeholder': 'Enter 6-digit code',
                'inputmode': 'numeric',
            }
        )


class SignupEmailVerificationForm(forms.Form):
    code = forms.CharField(max_length=6, min_length=6)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['code'].widget.attrs.update(
            {
                'class': 'form-control',
                'placeholder': 'Enter 6-digit code',
                'inputmode': 'numeric',
                'autocomplete': 'one-time-code',
            }
        )


class UserDocumentUploadForm(forms.Form):
    documents = MultipleFileField(
        required=False,
        widget=MultipleFileInput(attrs={'class': 'form-control', 'accept': '.pdf,.png,.jpg,.jpeg'})
    )

    def clean_documents(self):
        files = self.cleaned_data.get('documents', [])
        allowed_extensions = {'.pdf', '.png', '.jpg', '.jpeg'}

        for file in files:
            name = file.name.lower()
            if not any(name.endswith(ext) for ext in allowed_extensions):
                raise forms.ValidationError('Only PDF and image files are allowed.')

        return files