# tracker/routing.py
from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    # This regex captures the room name from the URL
    re_path(r'ws/chat/(?P<room_name>\w+)/$', consumers.ChatConsumer.as_asgi()),
]