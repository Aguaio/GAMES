from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required, user_passes_test
from .models import SesionGameMaster, ConfiguracionGlobal, Categoria, PackPalabras, PartidaLocal, JugadorLocal
from django.utils import timezone
import datetime
import json
from django.http import JsonResponse
import random

# --- FLUJO DEL JUGADOR ---

def inicio(request):
    config = ConfiguracionGlobal.get_solo()
    
    # Si ya está logueado, lo mandamos directo al menú
    if request.session.get('gm_nick'):
        return redirect('menu_juegos')

    if request.method == 'POST':
        nick = request.POST.get('nickname').strip()
        
        # 1. Buscar si alguien ya tiene ese nombre
        # Usamos filter().first() para no causar error si no existe
        usuario_actual = SesionGameMaster.objects.filter(nickname__iexact=nick).first()
        
        if usuario_actual:
            # 2. Calcular límite de tiempo (Ahora - Tiempo Configurado)
            limite = timezone.now() - datetime.timedelta(minutes=config.tiempo_sesion_minutos)
            
            # 3. VERIFICAR: ¿Sigue activo?
            if usuario_actual.ultima_actividad > limite:
                # ESTÁ VIVO: Bloquear acceso
                messages.error(request, f"¡El usuario '{nick}' ya está conectado en otro dispositivo!")
                return render(request, 'juego/inicio.html')
            else:
                # EXPIRÓ: Podemos tomar el nombre (Reciclaje)
                usuario_actual.ultima_actividad = timezone.now()
                usuario_actual.save()
        else:
            # 4. NO EXISTE: Crear nuevo
            SesionGameMaster.objects.create(nickname=nick)
        
        # Login Exitoso
        request.session['gm_nick'] = nick
        return redirect('menu_juegos')

    return render(request, 'juego/inicio.html')

def menu_juegos(request):
    # MENÚ INTERMEDIO
    nick = request.session.get('gm_nick')
    if not nick: return redirect('inicio')
    
    # Actualizar actividad y Estado
    try: 
        jugador = SesionGameMaster.objects.get(nickname=nick)
        jugador.juego_actual = "En Menú"      # <--- Lo que verá el admin
        jugador.estado = "Conectado"
        jugador.save()
    except SesionGameMaster.DoesNotExist: 
        return redirect('inicio')

    return render(request, 'juego/menu_juegos.html', {'nick': nick})

def sala_espera(request):
    # LOBBY DE CONFIGURACIÓN
    nick = request.session.get('gm_nick')
    if not nick: return redirect('inicio')
    
    # Actualizar actividad
    try: 
        jugador = SesionGameMaster.objects.get(nickname=nick)
        jugador.juego = "El Impostor"
        jugador.save()
    except SesionGameMaster.DoesNotExist: 
        return redirect('inicio')

    # Filtramos categorías públicas o creadas por admin
    categorias = Categoria.objects.filter(es_publica=True) | Categoria.objects.filter(creada_por_admin=True)
    categorias = categorias.distinct().order_by('-suma_puntuacion')

    return render(request, 'juego/sala_espera.html', {
        'nick': nick,
        'categorias': categorias
    })

def logout_jugador(request):
    try: 
        SesionGameMaster.objects.filter(nickname=request.session.get('gm_nick')).delete()
    except: pass
    request.session.flush()
    return redirect('inicio')

# --- LÓGICA DEL JUEGO (MOTOR) ---

def distribuir_roles(partida):
    """ El cerebro que decide quién es quién """
    # 1. Elegir Pack de Palabras
    packs = list(PackPalabras.objects.filter(categoria=partida.categoria_actual))
    if not packs: return False
    
    pack_elegido = random.choice(packs)
    partida.palabra_secreta_actual = pack_elegido.palabra_principal
    partida.save()

    # 2. Obtener Jugadores y mezclar
    jugadores = list(partida.jugadores.all())
    random.shuffle(jugadores)

    total_jugadores = len(jugadores)
    cant_impostores = min(partida.cantidad_impostores, total_jugadores - 1)

    # 3. Definir Roles
    impostores = jugadores[:cant_impostores]
    inocentes_posibles = jugadores[cant_impostores:] 

    # Asignar datos a Impostores
    palabra_impostor = "" 
    if partida.modo_dificil:
        palabra_impostor = pack_elegido.palabra_relacionada_2 
    
    for imp in impostores:
        imp.es_impostor = True
        imp.palabra_asignada = palabra_impostor
        imp.save()

    # --- SEÑUELO (Si aplica) ---
    if partida.usar_senuelo and len(inocentes_posibles) > 0:
        senuelo = random.choice(inocentes_posibles)
        senuelo.es_senuelo = True
        senuelo.palabra_asignada = pack_elegido.palabra_relacionada_1
        senuelo.save()
        inocentes_posibles.remove(senuelo)

    # --- INOCENTES ---
    for inocente in inocentes_posibles:
        inocente.palabra_asignada = pack_elegido.palabra_principal
        inocente.save()

    return True

def vista_juego(request):
    """ La pantalla donde se pasan el celular """
    nick = request.session.get('gm_nick')
    if not nick: return redirect('inicio')
    
    try:
        gm = SesionGameMaster.objects.get(nickname=nick)
        gm.save() # Ping de actividad
        partida = PartidaLocal.objects.get(anfitrion=gm)
    except:
        return redirect('inicio')
    
    if not partida.en_curso:
        return redirect('sala_espera')

    # Obtenemos jugadores ordenados por su turno
    jugadores = partida.jugadores.all().order_by('orden_turno')
    config_global = ConfiguracionGlobal.get_solo()

    return render(request, 'juego/partida.html', {
        'partida': partida,
        'jugadores': jugadores,
        'tiempo_revelacion': config_global.tiempo_revelacion_segundos
    })


# --- APIs (AJAX) PARA EL JUGADOR ---

def api_ping(request):
    """ El cliente llama a esto para decir 'Estoy aquí' """
    nick = request.session.get('gm_nick')
    if nick:
        SesionGameMaster.objects.filter(nickname=nick).update(ultima_actividad=timezone.now())
        return JsonResponse({'status': 'ok'})
    return JsonResponse({'status': 'error'})

def iniciar_partida(request):
    if request.method == 'POST':
        nick = request.session.get('gm_nick')
        gm = get_object_or_404(SesionGameMaster, nickname=nick)
        
        try:
            data = json.loads(request.body)
            jugadores_nombres = data.get('jugadores', [])
            config_data = data.get('config', {})
            
            # Limpiar partida anterior
            PartidaLocal.objects.filter(anfitrion=gm).delete()
            
            # Crear Partida
            nueva_partida = PartidaLocal.objects.create(
                anfitrion=gm,
                categoria_actual_id=config_data.get('categoria_id'),
                cantidad_impostores=int(config_data.get('cant_impostores', 1)),
                modo_dificil=config_data.get('modo_dificil', False),
                usar_senuelo=config_data.get('usar_senuelo', False),
                senuelo_sabe_rol=config_data.get('senuelo_sabe', True),
                hermanos_impostores=config_data.get('hermanos', True),
                impostor_compulsivo=config_data.get('compulsivo', False),
                en_curso=True
            )

            # Crear Jugadores
            orden = 1
            for nombre in jugadores_nombres:
                if nombre.strip():
                    JugadorLocal.objects.create(
                        partida=nueva_partida,
                        nombre=nombre.strip(),
                        orden_turno=orden
                    )
                    orden += 1
            
            # Asignar Roles
            if not distribuir_roles(nueva_partida):
                return JsonResponse({'status': 'error', 'msg': 'La categoría no tiene palabras.'})

            return JsonResponse({'status': 'ok', 'redirect': '/juego/partida/'})
            
        except Exception as e:
            return JsonResponse({'status': 'error', 'msg': str(e)})

    return JsonResponse({'status': 'error'})

# --- NUEVAS VISTAS PARA EL USUARIO ---

def crear_categoria_usuario(request):
    """ Vista para que el usuario cree categorías """
    nick = request.session.get('gm_nick')
    if not nick: return redirect('inicio')

    if request.method == 'POST':
        try:
            nombre = request.POST.get('nombre_categoria')
            palabras = json.loads(request.POST.get('lista_palabras'))
            
            if Categoria.objects.filter(nombre__iexact=nombre).exists():
                return JsonResponse({'status': 'error', 'msg': 'Ese nombre ya existe.'})

            # Creamos la categoría (Pública por defecto y con el autor)
            cat = Categoria.objects.create(
                nombre=nombre, 
                creada_por_admin=False, # Es de usuario
                es_publica=True, 
                autor=nick # Guardamos el nickname del creador
            )
            
            for p in palabras:
                PackPalabras.objects.create(
                    categoria=cat,
                    palabra_principal=p['principal'],
                    palabra_relacionada_1=p['rel1'],
                    palabra_relacionada_2=p['rel2']
                )
            return JsonResponse({'status': 'ok'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'msg': str(e)})

    return render(request, 'juego/crear_categoria_usuario.html', {'nick': nick})


def api_votar_categoria(request):
    """ Recibe el voto al final de la partida """
    if request.method == 'POST':
        try:
            cat_id = request.POST.get('categoria_id')
            puntos = int(request.POST.get('puntos'))
            
            if 1 <= puntos <= 5:
                cat = Categoria.objects.get(id=cat_id)
                cat.suma_puntuacion += puntos
                cat.cantidad_votos += 1
                cat.save()
                return JsonResponse({'status': 'ok'})
        except:
            pass
    return JsonResponse({'status': 'error'})


# --- PANEL DE CONTROL ADMIN ---

@login_required
@user_passes_test(lambda u: u.is_staff)
def panel_control(request):
    config = ConfiguracionGlobal.get_solo()
    
    if request.method == 'POST':
        # 1. ACTUALIZAR TIEMPOS
        if 'update_time' in request.POST:
            config.tiempo_sesion_minutos = int(request.POST.get('tiempo_total'))
            config.tiempo_aviso_minutos = int(request.POST.get('tiempo_aviso'))
            config.tiempo_afk_visual_minutos = int(request.POST.get('tiempo_afk_visual'))
            config.tiempo_revelacion_segundos = int(request.POST.get('tiempo_revelacion'))
            config.save()
            messages.success(request, 'Configuración actualizada.')
        
        # 2. CREAR MODERADOR (Solo Superusuario)
        elif 'new_admin' in request.POST:
            if request.user.is_superuser:
                u = request.POST.get('new_user')
                p = request.POST.get('new_pass')
                if not User.objects.filter(username=u).exists():
                    user = User.objects.create_user(u, '', p)
                    user.is_staff = True 
                    user.save()
                    messages.success(request, f'Moderador {u} creado.')
                else:
                    messages.error(request, 'El usuario ya existe.')
            else:
                messages.error(request, 'No tienes permiso para crear administradores.')

        # 3. ELIMINAR ADMIN (Solo Superusuario)
        elif 'delete_admin_id' in request.POST:
            if request.user.is_superuser:
                target_id = int(request.POST.get('delete_admin_id'))
                if target_id != request.user.id:
                    User.objects.filter(id=target_id).delete()
                    messages.success(request, 'Usuario eliminado.')
                else:
                    messages.error(request, 'No puedes eliminarte a ti mismo.')
            else:
                messages.error(request, 'No tienes permiso para eliminar administradores.')

    admins = User.objects.filter(is_staff=True)
    return render(request, 'juego/panel_control.html', {'config': config, 'admins': admins})


# --- APIs ADMIN (AJAX) ---

@login_required
@user_passes_test(lambda u: u.is_staff)
def api_datos_panel(request):
    config = ConfiguracionGlobal.get_solo()
    
    # 1. Limpieza de inactivos
    limite_borrado = timezone.now() - datetime.timedelta(minutes=config.tiempo_sesion_minutos)
    SesionGameMaster.objects.filter(ultima_actividad__lt=limite_borrado).delete()

    # 2. Obtener datos ENRIQUECIDOS
    jugadores = SesionGameMaster.objects.all().order_by('-ultima_actividad')
    lista_jugadores = []
    
    limite_afk_visual = timezone.now() - datetime.timedelta(minutes=config.tiempo_afk_visual_minutos)

    for j in jugadores:
        es_afk = j.ultima_actividad < limite_afk_visual
        
        # BUSCAMOS QUÉ ESTÁ JUGANDO Y QUÉ CATEGORÍA
        info_juego = "En Menú"
        info_cat = "-"
        
        try:
            partida = PartidaLocal.objects.get(anfitrion=j)
            if partida.en_curso:
                info_juego = "Jugando Impostor"
            else:
                info_juego = "Configurando"
            
            if partida.categoria_actual:
                info_cat = partida.categoria_actual.nombre
        except PartidaLocal.DoesNotExist:
            pass # Está en el menú o recién logueado

        lista_jugadores.append({
            'nickname': j.nickname,
            'ultima': j.ultima_actividad.strftime("%H:%M:%S"),
            'estado': "AUSENTE (AFK)" if es_afk else "ACTIVO",
            'color': "orange" if es_afk else "#2ecc71",
            'juego': info_juego,   # <--- NUEVO CAMPO
            'categoria': info_cat  # <--- NUEVO CAMPO
        })

    return JsonResponse({'jugadores': lista_jugadores})

@login_required
@user_passes_test(lambda u: u.is_staff)
def api_crear_categoria(request):
    if request.method == 'POST':
        try:
            nombre = request.POST.get('nombre_categoria')
            palabras = json.loads(request.POST.get('lista_palabras'))
            es_publica = request.POST.get('es_publica') == 'true'
            
            if Categoria.objects.filter(nombre__iexact=nombre).exists():
                return JsonResponse({'status': 'error', 'msg': 'Categoría ya existe'})

            cat = Categoria.objects.create(
                nombre=nombre, 
                creada_por_admin=True, 
                es_publica=es_publica, 
                autor="Admin"
            )
            
            for p in palabras:
                PackPalabras.objects.create(
                    categoria=cat,
                    palabra_principal=p['principal'],
                    palabra_relacionada_1=p['rel1'],
                    palabra_relacionada_2=p['rel2']
                )
            return JsonResponse({'status': 'ok'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'msg': str(e)})
    return JsonResponse({'status': 'error'})

@login_required
@user_passes_test(lambda u: u.is_staff)
def api_listar_categorias(request):
    cats = Categoria.objects.all().order_by('-id')
    data = [{'id': c.id, 'nombre': c.nombre, 'total': c.packs.count(), 'publica': c.es_publica} for c in cats]
    return JsonResponse({'categorias': data})

@login_required
@user_passes_test(lambda u: u.is_staff)
def api_eliminar_categoria(request):
    if request.method == 'POST':
        Categoria.objects.filter(id=request.POST.get('id')).delete()
        return JsonResponse({'status': 'ok'})
    return JsonResponse({'status': 'error'})

# LOGIN/LOGOUT ADMIN
def login_admin_custom(request):
    if request.user.is_staff: return redirect('panel_control')
    if request.method == 'POST':
        user = authenticate(request, username=request.POST.get('username'), password=request.POST.get('password'))
        if user and user.is_staff:
            login(request, user)
            return redirect('panel_control')
    return render(request, 'juego/login_admin.html')

def logout_admin(request):
    logout(request)
    return redirect('inicio')

