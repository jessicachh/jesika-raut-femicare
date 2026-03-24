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


@register.filter
def file_type_badge(file_name):
    """Return short file type badge text like IMG, PDF, DOC."""
    if not file_name:
        return "FILE"

    lowered = file_name.lower()
    image_ext = ('.jpg', '.jpeg', '.png', '.gif', '.webp')
    doc_ext = ('.doc', '.docx')

    if lowered.endswith(image_ext):
        return "IMG"
    if lowered.endswith('.pdf'):
        return "PDF"
    if lowered.endswith(doc_ext):
        return "DOC"
    return "FILE"