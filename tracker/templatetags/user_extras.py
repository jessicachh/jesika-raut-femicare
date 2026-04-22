from django import template
import hashlib
from django.utils.html import format_html

register = template.Library()

@register.filter
def has_doctor_profile(user):
    return hasattr(user, 'doctor_profile')

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


def _avatar_seed(value):
    return hashlib.md5((value or 'u').encode('utf-8')).hexdigest()


def _avatar_color(value):
    seed_int = int(_avatar_seed(value)[:8], 16)
    hue = seed_int % 360
    saturation = 62 + (seed_int % 10)
    lightness = 72 + (seed_int % 8)
    return f"hsl({hue} {saturation}% {lightness}%)"


def _user_initial(user):
    username = getattr(user, 'username', '') or 'U'
    return username[:1].upper()


def _profile_photo_url(user):
    if not getattr(user, 'is_authenticated', False):
        return ''

    try:
        if getattr(user, 'doctor_profile', None) and user.doctor_profile.photo:
            return user.doctor_profile.photo.url
    except Exception:
        pass

    try:
        if getattr(user, 'user_profile', None) and user.user_profile.profile_picture:
            return user.user_profile.profile_picture.url
    except Exception:
        pass

    return ''


@register.simple_tag
def render_user_avatar(user, wrapper_class='user-avatar', alt='Avatar'):
    photo_url = _profile_photo_url(user)
    if photo_url:
        return format_html(
            '<span class="{}"><img src="{}" alt="{}"></span>',
            wrapper_class,
            photo_url,
            alt,
        )

    initial = _user_initial(user)
    bg_color = _avatar_color(getattr(user, 'username', ''))
    return format_html(
        '<span class="{}" aria-label="{}">'
        '<span class="avatar-fallback" style="--avatar-bg: {};">'
        '<span class="avatar-fallback-letter">{}</span>'
        '</span>'
        '</span>',
        wrapper_class,
        alt,
        bg_color,
        initial,
    )