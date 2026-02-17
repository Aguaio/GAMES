from django.contrib import admin
from django.urls import path, include
from juego import views

urlpatterns = [
    # --- 1. RUTAS DE ADMINISTRACIÓN ---
    # (Las mantenemos aquí o podríamos moverlas a juego/urls.py después)
    path('sistema/login/', views.login_admin, name='login_admin'),
    path('sistema/panel/', views.panel_control, name='panel_control'),
    path('sistema/logout/', views.logout_admin, name='logout_admin'),

    # --- 2. INCLUIR LAS RUTAS DE LA APP 'JUEGO' ---
    # Esto conecta con juego/urls.py, donde están 'inicio', 'sala_espera'
    # Y LO MÁS IMPORTANTE: las nuevas APIs que te estaban fallando.
    path('', include('juego.urls')),

]
