from django.urls import path
from . import views

urlpatterns = [
    # --- RUTAS PÚBLICAS ---
    path('', views.inicio, name='inicio'),
    path('menu/', views.menu_juegos, name='menu_juegos'), # El nuevo menú
    path('salir/', views.logout_jugador, name='logout_jugador'),

    # --- RUTAS DEL JUEGO "EL IMPOSTOR" ---
    path('impostor/configurar/', views.sala_espera, name='sala_espera'), # Lobby
    path('juego/partida/', views.vista_juego, name='vista_juego'),       # Pantalla de juego
    path('crear-categoria/', views.crear_categoria_usuario, name='crear_categoria_usuario'),

    # --- APIs JUGADOR (AJAX) ---
    path('api/ping/', views.api_ping, name='api_ping'),
    path('api/iniciar-partida/', views.iniciar_partida, name='iniciar_partida'),
    path('api/votar/', views.api_votar_categoria, name='api_votar_categoria'),
    
    # --- RUTAS ADMIN ---
    path('sistema/login/', views.login_admin_custom, name='login_admin'),
    path('sistema/panel/', views.panel_control, name='panel_control'),
    path('sistema/logout/', views.logout_admin, name='logout_admin'),

    # --- APIs ADMIN (AJAX) ---
    path('api/panel-datos/', views.api_datos_panel, name='api_datos_panel'),
    path('api/crear-categoria/', views.api_crear_categoria, name='api_crear_categoria'),
    path('api/listar-categorias/', views.api_listar_categorias, name='api_listar_categorias'),
    path('api/eliminar-categoria/', views.api_eliminar_categoria, name='api_eliminar_categoria'),
]

