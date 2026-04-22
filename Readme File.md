# FemiCare – Menstrual Health Tracking

FemiCare is a web-based healthcare system designed to support women in managing their menstrual health, tracking symptoms, and consulting with verified doctors. The platform provides intelligent cycle prediction, health insights, real-time consultation, and emergency support features in a secure and user-friendly environment.

# Project Objective

* Provide a digital solution for menstrual health tracking
* Improve awareness of women’s health through insights and resources
* Enable easy access to verified doctors for consultation
* Support early detection of health risks through symptom tracking
* Offer emergency consultation support when needed

# Features

The system provides the following features:

**User Features:**

* User registration and secure login (with email verification & 2FA)
* Profile and health data management
* Manual cycle logging and history tracking
* 3-month cycle prediction with calendar view
* Symptom and mood tracking
* Health insights dashboard
* Emergency alert system
* Appointment booking with doctors
* Real-time consultation (chat, audio, video)
* Report export (health summary)
* Resource section (articles, videos)

**Doctor Features:**

* Doctor registration and profile verification
* Profile completion and license validation
* Set availability (date & time slots)
* Appointment management (accept/reject)
* Consultation via chat/audio/video
* Payment confirmation system
* Patient interaction and review system

# Technologies Used

Frontend

* HTML
* CSS
* JavaScript

Backend

* Django

Database

* MySQL(Development)
* PostgreSQL (Production)

Deployment

* Railway

# System Requirements

Hardware

* Computer or Laptop
* Stable Internet connection

Software

* Python
* Django
* Web browser such as Google Chrome or Firefox

# Installation and Setup

Steps to run the project locally.

1. Clone the repository

git clone https://github.com/jessicachh/jesika-raut-femicare.git

1. Go to the project folder

cd femicare

1. Install required dependencies

pip install -r requirements.txt

1. Create and activate virtual environment

python –m venv env

env\scripts\activate

1. Run Migrations

python manage.py makemigrations

python manage.py migrate

1. Run the application

python manage.py runserver

# Live Project

Live URL of the deployed system:

<https://femicare.up.railway.app/>

# Project Structure

FYP/

├── FemiCare/ # Django project configuration

├── media/ # uploaded files

├── tracker/ # main Django app

├── .gitignore # files to ignore in git

├── manage.py # Django project management script

├── requirements.txt # list of python dependencies for the project

├── railpack.toml # deployment configuration

├── start.sh # startup script for deployment environment

# Screenshots

* Major Home Pages

![](data:image/jpeg;base64...)

![](data:image/jpeg;base64...)

![](data:image/jpeg;base64...)

* Register Page

![](data:image/png;base64...)

* Login page

![](data:image/png;base64...)

* User Dashboard

![](data:image/png;base64...)

* Add Cycle

![](data:image/png;base64...)

* Calendar View

![](data:image/png;base64...)

* Doctor Verification

**![](data:image/png;base64...)**

* Doctor Dashboard

![](data:image/png;base64...)

* Appointment Book

![](data:image/png;base64...)

* Consultation Chat

**![](data:image/png;base64...)**

* Consultation Audio/Video Call

![](data:image/jpeg;base64...)

![](data:image/jpeg;base64...)

* Health Insights

![](data:image/png;base64...)

* Emergency Trigger

![](data:image/jpeg;base64...)

![](data:image/jpeg;base64...)

# Future Improvements

Possible improvements for the system:

* AI-based advanced prediction model
* Mobile application (Android/iOS)
* Doctor reward system for emergency consultations
* Automated payment split (commission system)
* Enhanced analytics and reporting
* Integration with worldwide payment gateways

# Authors

Jesika Raut

BSc (Hons) / Computing

London Metropolitan/ Itahari International College

# License

This project is created for educational purposes as part of a Final Year Project.