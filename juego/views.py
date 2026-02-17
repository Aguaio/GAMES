from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required, user_passes_test
from .models import SesionGameMaster, ConfiguracionGlobal, Categoria, PackPalabras, PartidaLocal, JugadorLocal
from django.utils import timezone
from django.db.models import F 
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
        usuario_actual = SesionGameMaster.objects.filter(nickname__iexact=nick).first()
        
        if usuario_actual:
            # 2. Calcular límite de tiempo
            limite = timezone.now() - datetime.timedelta(minutes=config.tiempo_sesion_minutos)
            
            # 3. VERIFICAR: ¿Sigue activo?
            if usuario_actual.ultima_actividad > limite:
                messages.error(request, f"¡El usuario '{nick}' ya está conectado!")
                return render(request, 'juego/inicio.html')
            else:
                # EXPIRÓ: Podemos tomar el nombre
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
    nick = request.session.get('gm_nick')
    if not nick:
        return redirect('inicio')
    
    try: 
        jugador = SesionGameMaster.objects.get(nickname=nick)
        jugador.juego_actual = "En Menú"
        jugador.estado = "Conectado"
        jugador.save()
    except SesionGameMaster.DoesNotExist: 
        return redirect('inicio')

    return render(request, 'juego/menu_juegos.html', {'nick': nick})

def sala_espera(request):
    nick = request.session.get('gm_nick')
    if not nick:
        return redirect('inicio')
    
    try: 
        jugador = SesionGameMaster.objects.get(nickname=nick)
        jugador.juego_actual = "El Impostor"
        jugador.estado = "Configurando"
        jugador.save()
    except SesionGameMaster.DoesNotExist: 
        return redirect('inicio')

    # CAMBIO: Traemos TODAS las categorías (sin filtrar por pública)
    # Ordenamos por popularidad (veces jugada) y luego por nota.
    categorias = Categoria.objects.all().order_by('-cantidad_partidas', '-suma_puntuacion')

    return render(request, 'juego/sala_espera.html', {
        'nick': nick,
        'categorias': categorias
    })

def logout_jugador(request):
    try: 
        SesionGameMaster.objects.filter(nickname=request.session.get('gm_nick')).delete()
    except: 
        pass
    request.session.flush()
    return redirect('inicio')

# --- MOTOR DE JUEGO ---

# EN JUEGO/VIEWS.PY

def distribuir_roles(partida):
    """ El cerebro que decide quién es quién con memoria anti-repetición """
    packs = list(PackPalabras.objects.filter(categoria=partida.categoria_actual))
    if not packs: return False
    
    pack_elegido = random.choice(packs)
    partida.palabra_secreta_actual = pack_elegido.palabra_principal
    partida.save()

    jugadores = list(partida.jugadores.all())
    total_jugadores = len(jugadores)
    cant_impostores = min(partida.cantidad_impostores, total_jugadores - 1)
    
    # --- LÓGICA ANTI-REPETICIÓN ---
    # Obtenemos al anfitrión para ver la memoria
    gm = partida.anfitrion
    ultimo_impostor = gm.ultimo_impostor_nombre
    
    # Intentamos barajar hasta que el primer impostor NO sea el mismo de antes
    # (Solo si NO es modo compulsivo y hay suficientes jugadores para rotar)
    max_intentos = 10
    for _ in range(max_intentos):
        random.shuffle(jugadores)
        
        # Si está activado "Impostor Compulsivo", nos da igual repetir.
        if partida.impostor_compulsivo:
            break
            
        # Si no hay memoria previa, cualquier orden sirve.
        if not ultimo_impostor:
            break
            
        # Verificamos los candidatos a impostor
        nuevos_impostores = jugadores[:cant_impostores]
        nombres_nuevos = [j.nombre for j in nuevos_impostores]
        
        # Si el último impostor NO está en el nuevo grupo, aceptamos la mezcla
        if ultimo_impostor not in nombres_nuevos:
            break
        
        # Si llegamos aquí, se repitió. El bucle for intentará barajar de nuevo.

    # Seleccionamos definitivamente
    impostores = jugadores[:cant_impostores]
    inocentes_posibles = jugadores[cant_impostores:] 

    # --- GUARDAR MEMORIA PARA LA PRÓXIMA ---
    # Guardamos el nombre del primer impostor en la sesión del GM
    if impostores:
        gm.ultimo_impostor_nombre = impostores[0].nombre
        gm.save()

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
    nick = request.session.get('gm_nick')
    if not nick:
        return redirect('inicio')
    
    try:
        gm = SesionGameMaster.objects.get(nickname=nick)
        gm.save() # Ping de actividad
        partida = PartidaLocal.objects.get(anfitrion=gm)
    except:
        return redirect('inicio')
    
    if not partida.en_curso:
        return redirect('sala_espera')

    jugadores = partida.jugadores.all().order_by('orden_turno')
    config_global = ConfiguracionGlobal.get_solo()

    return render(request, 'juego/partida.html', {
        'partida': partida,
        'jugadores': jugadores,
        'tiempo_revelacion': config_global.tiempo_revelacion_segundos
    })

# --- APIs (AJAX) ---

def api_ping(request):
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
            
            # --- VALIDACIÓN DE SEGURIDAD (FIX) ---
            # Si viene vacío, texto o basura, forzamos a 1
            try:
                c_imp = int(config_data.get('cant_impostores'))
            except (ValueError, TypeError):
                c_imp = 1 
            # -------------------------------------

            # Limpiar partida anterior
            PartidaLocal.objects.filter(anfitrion=gm).delete()
            
            # 1. Crear Partida
            nueva_partida = PartidaLocal.objects.create(
                anfitrion=gm,
                categoria_actual_id=config_data.get('categoria_id'),
                cantidad_impostores=c_imp, # Usamos la variable validada
                modo_dificil=config_data.get('modo_dificil', False),
                usar_senuelo=config_data.get('usar_senuelo', False),
                senuelo_sabe_rol=config_data.get('senuelo_sabe', True),
                hermanos_impostores=config_data.get('hermanos', True),
                impostor_compulsivo=config_data.get('compulsivo', False),
                en_curso=True
            )

            # 2. CONTADOR DE PARTIDAS (+1)
            cat_id = config_data.get('categoria_id')
            if cat_id:
                Categoria.objects.filter(id=cat_id).update(cantidad_partidas=F('cantidad_partidas') + 1)

            # 3. Crear Jugadores
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
            return JsonResponse({'status': 'error', 'msg': f"Error interno: {str(e)}"})

    return JsonResponse({'status': 'error'})

def crear_categoria_usuario(request):
    nick = request.session.get('gm_nick')
    if not nick:
        return redirect('inicio')

    # Obtenemos la config para saber el mínimo
    config_global = ConfiguracionGlobal.get_solo()

    if request.method == 'POST':
        try:
            nombre = request.POST.get('nombre_categoria')
            palabras = json.loads(request.POST.get('lista_palabras'))
            
            # 1. VALIDACIÓN DE NOMBRE
            if Categoria.objects.filter(nombre__iexact=nombre).exists():
                return JsonResponse({'status': 'error', 'msg': 'Ese nombre ya existe.'})

            # 2. VALIDACIÓN DE CANTIDAD MÍNIMA (NUEVO)
            minimo = config_global.min_packs_categoria
            if len(palabras) < minimo:
                return JsonResponse({
                    'status': 'error', 
                    'msg': f'Faltan palabras. Mínimo requerido: {minimo}. Tienes: {len(palabras)}.'
                })

            # Crear Categoría (Siempre pública)
            cat = Categoria.objects.create(
                nombre=nombre, 
                creada_por_admin=False, 
                es_publica=True, 
                autor=nick
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

    # Pasamos el mínimo al template para mostrarlo
    return render(request, 'juego/crear_categoria_usuario.html', {
        'nick': nick,
        'min_packs': config_global.min_packs_categoria
    })

def api_votar_categoria(request):
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
        # 1. ACTUALIZAR CONFIGURACIÓN
        if 'update_time' in request.POST:
            config.tiempo_sesion_minutos = int(request.POST.get('tiempo_total'))
            config.tiempo_aviso_minutos = int(request.POST.get('tiempo_aviso'))
            config.tiempo_afk_visual_minutos = int(request.POST.get('tiempo_afk_visual'))
            config.tiempo_revelacion_segundos = int(request.POST.get('tiempo_revelacion'))
            
            # NUEVO CAMPO
            config.min_packs_categoria = int(request.POST.get('min_packs'))
            
            config.save()
            messages.success(request, 'Configuración actualizada.')
        
        # 2. CREAR MODERADOR
        elif 'new_admin' in request.POST:
            if request.user.is_superuser:
                u = request.POST.get('new_user')
                p = request.POST.get('new_pass')
                if not User.objects.filter(username=u).exists():
                    User.objects.create_user(u, '', p, is_staff=True)
                    messages.success(request, f'Moderador {u} creado.')
                else:
                    messages.error(request, 'El usuario ya existe.')
            else:
                messages.error(request, 'No tienes permiso.')

        # 3. ELIMINAR ADMIN
        elif 'delete_admin_id' in request.POST:
            if request.user.is_superuser:
                target_id = int(request.POST.get('delete_admin_id'))
                if target_id != request.user.id:
                    User.objects.filter(id=target_id).delete()
                    messages.success(request, 'Usuario eliminado.')
                else:
                    messages.error(request, 'No puedes eliminarte a ti mismo.')
            else:
                messages.error(request, 'No tienes permiso.')

    admins = User.objects.filter(is_staff=True)
    return render(request, 'juego/panel_control.html', {'config': config, 'admins': admins})


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
        
        # BUSCAMOS QUÉ ESTÁ JUGANDO
        try:
            partida = PartidaLocal.objects.get(anfitrion=j)
            if partida.en_curso:
                info_juego = "Jugando Impostor"
            else:
                info_juego = "Sala de Espera"
            
            if partida.categoria_actual:
                info_cat = partida.categoria_actual.nombre
            else:
                info_cat = "-"
        except PartidaLocal.DoesNotExist:
            info_juego = j.juego_actual if j.juego_actual else "En Menú"
            info_cat = "-"

        lista_jugadores.append({
            'nickname': j.nickname,
            'ultima': j.ultima_actividad.strftime("%H:%M:%S"),
            'estado': "AUSENTE (AFK)" if es_afk else "ACTIVO",
            'color': "orange" if es_afk else "#2ecc71",
            'juego': info_juego,
            'categoria': info_cat
        })

    return JsonResponse({'jugadores': lista_jugadores})

@login_required
@user_passes_test(lambda u: u.is_staff)
def api_crear_categoria(request):
    if request.method == 'POST':
        try:
            nombre = request.POST.get('nombre_categoria')
            palabras = json.loads(request.POST.get('lista_palabras'))
            
            # CAMBIO: Eliminamos la lectura del checkbox. Siempre True.
            
            if Categoria.objects.filter(nombre__iexact=nombre).exists():
                return JsonResponse({'status': 'error', 'msg': 'Categoría ya existe'})

            cat = Categoria.objects.create(
                nombre=nombre, 
                creada_por_admin=True, 
                es_publica=True, # Siempre visible
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
    # Añadimos 'jugada' al JSON
    data = [{
        'id': c.id, 
        'nombre': c.nombre, 
        'total': c.packs.count(), 
        'publica': c.es_publica, 
        'jugada': c.cantidad_partidas
    } for c in cats]
    return JsonResponse({'categorias': data})

@login_required
@user_passes_test(lambda u: u.is_staff)
def api_eliminar_categoria(request):
    if request.method == 'POST':
        Categoria.objects.filter(id=request.POST.get('id')).delete()
        return JsonResponse({'status': 'ok'})
    return JsonResponse({'status': 'error'})

# LOGIN/LOGOUT ADMIN
from django.contrib import messages

def login_admin(request):
    if request.method == 'POST':
        u = request.POST.get('user')
        p = request.POST.get('pass')
        user = authenticate(username=u, password=p)
        
        if user is not None and user.is_staff:
            login(request, user)
            return redirect('panel_control')
        else:
            # CLAVE: No redireccionamos. Recargamos el mismo archivo con el error.
            messages.error(request, "Usuario o contraseña incorrectos.")
            return render(request, 'juego/login_admin.html')
            
    return render(request, 'juego/login_admin.html')

def logout_admin(request):
    logout(request)

    return redirect('inicio')


