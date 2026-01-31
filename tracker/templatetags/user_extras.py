from django import template

register = template.Library()

@register.filter
def has_doctor_profile(user):
    return hasattr(user, 'doctorprofile')