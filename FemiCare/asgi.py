import os
import django
from django.core.asgi import get_asgi_application

# Set the settings module environment variable
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'FemiCare.settings')

# Initialize the Django ASGI application first
django_asgi_app = get_asgi_application()

# NOW  import your channels-specific modules
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
import tracker.routing

application = ProtocolTypeRouter({
    # Use the initialized django_asgi_app here
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(
        URLRouter(
            tracker.routing.websocket_urlpatterns
        )
    ),
})