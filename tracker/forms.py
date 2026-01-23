from django import forms
from .models import CycleLog


class CycleLogForm(forms.ModelForm):
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
            'last_period_start': 'First day of last period',
            'length_of_cycle': 'Average cycle length (days)',
            'length_of_menses': 'Period duration (days)',
            'mean_menses_length': 'Usual period length',
            'mean_bleeding_intensity': 'Bleeding intensity',
            'total_menses_score': 'Period pain level',
            'unusual_bleeding': 'Any unusual bleeding?',
            'height_cm': 'Height (cm)',
            'weight_kg': 'Weight (kg)',
        }

        widgets = {
            'last_period_start': forms.DateInput(attrs={'type': 'date'}),
            'unusual_bleeding': forms.RadioSelect(choices=[(True, 'Yes'), (False, 'No')]),
        }