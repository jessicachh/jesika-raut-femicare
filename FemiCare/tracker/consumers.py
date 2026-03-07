# tracker/consumers.py
import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from .models import ChatMessage, User

class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_name = self.scope['url_route']['kwargs']['room_name']
        self.room_group_name = f'chat_{self.room_name}'

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        # Join broadcast group to receive real-time conversation updates
        await self.channel_layer.group_add(
            'broadcast',
            self.channel_name
        )
        
        await self.accept()

    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
        
        # Leave broadcast group
        await self.channel_layer.group_discard(
            'broadcast',
            self.channel_name
        )

    # Receive message from WebSocket
    async def receive(self, text_data):
        data = json.loads(text_data)
        message_type = data.get('type', 'chat_message')

        # Handle WebRTC signaling messages
        if message_type == 'call_offer':
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'webrtc_signal',
                    'signal_type': 'call_offer',
                    'offer': data['offer'],
                    'isVideo': data.get('isVideo', True),
                    'sender': self.scope["user"].username
                }
            )
        elif message_type == 'call_answer':
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'webrtc_signal',
                    'signal_type': 'call_answer',
                    'answer': data['answer'],
                    'sender': self.scope["user"].username
                }
            )
        elif message_type == 'ice_candidate':
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'webrtc_signal',
                    'signal_type': 'ice_candidate',
                    'candidate': data['candidate'],
                    'sender': self.scope["user"].username
                }
            )
        elif message_type == 'call_end':
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'webrtc_signal',
                    'signal_type': 'call_end',
                    'sender': self.scope["user"].username
                }
            )
        elif message_type == 'call_rejected':
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'webrtc_signal',
                    'signal_type': 'call_rejected',
                    'sender': self.scope["user"].username
                }
            )
        elif message_type == 'file_message':
            # Handle file message notification
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'file_message',
                    'file_url': data.get('file_url'),
                    'file_name': data.get('file_name'),
                    'file_type': data.get('file_type'),
                    'message': data.get('message', ''),
                    'username': self.scope["user"].username
                }
            )
        else:
            # Handle regular chat message
            message = data.get('message', '')
            is_note = data.get('is_note', False)
            username = self.scope["user"].username

            # Save message to database
            await self.save_message(username, self.room_name, message, is_note)
            
            # Broadcast to global channel so chat panels receive real-time updates
            await self.channel_layer.group_send(
                'broadcast',
                {
                    'type': 'broadcast_message',
                    'message_type': 'message',
                    'room_name': self.room_name,
                    'username': username,
                    'is_note': is_note
                }
            )

            # Send message to room group
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'chat_message',
                    'message': message,
                    'username': username,
                    'is_note': is_note
                }
            )

    # Receive message from room group
    async def chat_message(self, event):
        # Send message to WebSocket
        await self.send(text_data=json.dumps({
            'type': 'chat_message',
            'message': event['message'],
            'sender': event['username'],
            'is_note': event['is_note']
        }))
    
    # Handle broadcast messages for real-time conversation updates
    async def broadcast_message(self, event):
        # Send broadcast notification to WebSocket
        # This allows chat panels to refresh conversation lists in real-time
        await self.send(text_data=json.dumps({
            'type': 'broadcast',
            'message_type': event['message_type'],
            'room_name': event['room_name']
        }))

    # Handle WebRTC signaling messages
    async def webrtc_signal(self, event):
        # Don't send signaling message back to the sender
        if event['sender'] != self.scope["user"].username:
            signal_data = {
                'type': event['signal_type'],
                'sender': event['sender']
            }
            
            if event['signal_type'] == 'call_offer':
                signal_data['offer'] = event['offer']
                signal_data['isVideo'] = event['isVideo']
            elif event['signal_type'] == 'call_answer':
                signal_data['answer'] = event['answer']
            elif event['signal_type'] == 'ice_candidate':
                signal_data['candidate'] = event['candidate']
            
            await self.send(text_data=json.dumps(signal_data))

    # Handle file messages
    async def file_message(self, event):
        # Don't send file message back to the sender
        if event['username'] != self.scope["user"].username:
            await self.send(text_data=json.dumps({
                'type': 'file_message',
                'file_url': event['file_url'],
                'file_name': event['file_name'],
                'file_type': event['file_type'],
                'message': event.get('message', ''),
                'sender': event['username']
            }))

    @database_sync_to_async
    def save_message(self, username, room_name, message, is_note):
        from django.utils import timezone
        user = User.objects.get(username=username)
        chat_message = ChatMessage.objects.create(
            room_name=room_name,
            sender=user,
            message=message,
            is_note=is_note
        )
        
        # Update conversation if not a note
        if not is_note:
            from .models import Conversation
            try:
                # Extract doctor and patient IDs from room_name format: chat_patientID_doctorID
                parts = room_name.split('_')
                if len(parts) >= 3:
                    patient_id = int(parts[1])
                    doctor_id = int(parts[2])
                    
                    conversation = Conversation.objects.filter(
                        doctor_id=doctor_id,
                        patient_id=patient_id
                    ).first()
                    
                    if conversation:
                        conversation.last_message = message[:100] if message else 'File attachment'
                        conversation.last_message_time = timezone.now()
                        
                        # Increment unread count for the receiver
                        if user.role == 'doctor':
                            conversation.unread_count_patient += 1
                        else:
                            conversation.unread_count_doctor += 1
                        
                        conversation.save()
            except Exception as e:
                print(f"Error updating conversation: {e}")
        
        return chat_message


class BroadcastConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for broadcasting real-time conversation updates.
    Used by chat panels to refresh conversation lists when new messages arrive.
    """
    
    async def connect(self):
        # Only allow authenticated users
        user = self.scope['user']
        if not user.is_authenticated:
            await self.close()
            return
        
        # Join the broadcast group
        await self.channel_layer.group_add(
            'broadcast',
            self.channel_name
        )
        await self.accept()
    
    async def disconnect(self, close_code):
        # Leave the broadcast group
        await self.channel_layer.group_discard(
            'broadcast',
            self.channel_name
        )
    
    async def broadcast_message(self, event):
        # Send the broadcast message to the WebSocket
        await self.send(text_data=json.dumps({
            'type': 'message',
            'room_name': event['room_name']
        }))