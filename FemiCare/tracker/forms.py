from django import forms
from .models import CycleLog, DoctorProfile

class DoctorProfileForm(forms.ModelForm):
    class Meta:
        model = DoctorProfile
        fields = ['photo', 'bio']


class CycleLogForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        if user:
            last_log = (
                CycleLog.objects
                .filter(user=user)
                .order_by("-created_at")
                .first()
            )

            if last_log:
                prefill_note = (
                    "Pre-filled from your last cycle — you can update if needed."
                )

                # Fields we want to prefill
                prefill_fields = [
                    "height_cm",
                    "weight_kg",
                    "mean_menses_length",
                    "length_of_cycle",
                ]

                for field in prefill_fields:
                    value = getattr(last_log, field, None)
                    if value is not None:
                        self.fields[field].initial = value

                        # 👇 add the small helper text
                        existing_help = self.fields[field].help_text or ""
                        self.fields[field].help_text = (
                            f"{existing_help} "
                            f"<span class='text-muted fst-italic d-block mt-1'>"
                            f"{prefill_note}</span>"
                        )

    class Meta:
        model = CycleLog
        fields = [
            'last_period_start',
            'length_of_cycle',
            'length_of_menses',
            'mean_menses_length',
            'mean_bleeding_intensity',
            'total_menses_score',
            'unusual_bleeding',
            'height_cm',
            'weight_kg',
        ]

        labels = {
            'last_period_start': 'When did your last period start?',
            'length_of_cycle': 'About how many days were there from the start of one period to the start of the next?',
            'length_of_menses': 'How many days did your period bleeding last?',
            'mean_menses_length': 'Usual period length',
            'mean_bleeding_intensity': 'How heavy was your period flow on most days?',
            'total_menses_score': 'How painful was your period?',
            'unusual_bleeding': 'Any signs of unusual bleeding?',
            'height_cm': 'Height (cm)',
            'weight_kg': 'Weight (kg)',
        }

        help_texts = {
            "last_period_start": "Select the first day of bleeding.",
            "length_of_cycle": "From the start of one period to the next.",
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
        super().__init__(*args, **kwargs)

        if user:
            last_log = (
                CycleLog.objects
                .filter(user=user)
                .order_by('-created_at')
                .first()
            )

            if last_log:
                self.fields['height_cm'].initial = last_log.height_cm
                self.fields['weight_kg'].initial = last_log.weight_kg
                self.fields['mean_menses_length'].initial = last_log.mean_menses_length
                self.fields['length_of_cycle'].initial = last_log.length_of_cycle