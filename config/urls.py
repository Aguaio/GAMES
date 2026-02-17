from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    # Mantenemos solo la conexión principal a tu app 'juego'
    path('', include('juego.urls')),
]
