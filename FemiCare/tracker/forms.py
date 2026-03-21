from django import forms

from .models import CycleLog, DoctorProfile, UserProfile


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
        fields = ['photo', 'bio']


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


class UserProfileForm(forms.ModelForm):
    full_name = forms.CharField(max_length=150, required=True)

    class Meta:
        model = UserProfile
        fields = [
            'full_name',
            'phone_number',
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

        if last_log:
            self.fields['height_cm'].initial = last_log.height_cm
            self.fields['weight_kg'].initial = last_log.weight_kg

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