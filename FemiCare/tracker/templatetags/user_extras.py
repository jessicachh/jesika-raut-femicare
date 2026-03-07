from django import template

register = template.Library()

@register.filter
def has_doctor_profile(user):
    return hasattr(user, 'doctorprofile')

@register.filter
def is_image_file(file_url):
    """Check if a file URL is an image"""
    if not file_url:
        return False
    image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp']
    return any(file_url.lower().endswith(ext) for ext in image_extensions)

@register.filter
def get_filename(file_url):
    """Extract filename from file URL"""
    if not file_url:
        return ""
    return file_url.split('/')[-1]