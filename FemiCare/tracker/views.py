from django.shortcuts import render
from django.conf import settings
import os

def main(request):    
    return render(request, 'main.html')

def home(request):    
    return render(request, 'home.html')

def service(request):    
    return render(request, 'how-it-works.html')

def contact(request):    
    return render(request, 'contact.html')

def signup(request):    
    return render(request, 'signup.html')

def login(request):    
    return render(request, 'login.html')

def dashboard_home(request):
    return render(request, 'dashboard/first.html', {
        'active_page': 'first'
    })

def appointment(request):
    return render(request, 'dashboard/appointment.html', {
        'active_page': 'appointments'
    })