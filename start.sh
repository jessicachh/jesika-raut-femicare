#!/bin/bash
python manage.py migrate
gunicorn FemiCare.wsgi:application --bind 0.0.0.0:8000