#!/bin/bash
python manage.py migrate
python manage.py collectstatic --noinput
# daphne -b 0.0.0.0 -p 8080 FemiCare.asgi:application
daphne -b 0.0.0.0 -p $PORT FemiCare.asgi:application