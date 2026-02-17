from django.db import models
from django.utils import timezone
import datetime

# --- 1. SISTEMA DE PALABRAS Y CATEGORÍAS ---

class Categoria(models.Model):
    nombre = models.CharField(max_length=50, unique=True)
    creada_por_admin = models.BooleanField(default=False) 
    
    # Comunidad
    es_publica = models.BooleanField(default=False)
    autor = models.CharField(max_length=50, default="Anónimo")
    
    # Puntuación
    suma_puntuacion = models.IntegerField(default=0)
    cantidad_votos = models.IntegerField(default=0)
    
    # ESTADÍSTICAS
    cantidad_partidas = models.IntegerField(default=0, verbose_name="Veces Jugada")
    
    @property
    def ranking(self):
        if self.cantidad_votos == 0: return 0
        return round(self.suma_puntuacion / self.cantidad_votos, 1)

    def __str__(self):
        return self.nombre

class PackPalabras(models.Model):
    categoria = models.ForeignKey(Categoria, on_delete=models.CASCADE, related_name='packs')
    palabra_principal = models.CharField(max_length=100)
    palabra_relacionada_1 = models.CharField(max_length=100) # Para Señuelo o Difícil A
    palabra_relacionada_2 = models.CharField(max_length=100) # Para Difícil B
    
    def __str__(self):
        return f"{self.palabra_principal} en {self.categoria.nombre}"

# --- 2. SESIÓN DE USUARIO (ANFITRIÓN) ---

class SesionGameMaster(models.Model):
    nickname = models.CharField(max_length=50, unique=True)
    ultima_actividad = models.DateTimeField(auto_now=True)
    
    # Estado para el Panel de Admin
    juego_actual = models.CharField(max_length=50, default="-")
    estado = models.CharField(max_length=20, default="Conectado")

    # MEMORIA DE IMPOSTOR
    ultimo_impostor_nombre = models.CharField(max_length=50, blank=True, default="")

    def __str__(self):
        return self.nickname

# --- 3. LÓGICA DE PARTIDA (PASS & PLAY) ---

class PartidaLocal(models.Model):
    anfitrion = models.OneToOneField(SesionGameMaster, on_delete=models.CASCADE)
    
    # Configuración de la partida
    categoria_actual = models.ForeignKey(Categoria, on_delete=models.SET_NULL, null=True)
    cantidad_impostores = models.IntegerField(default=1)
    
    # Modos de Juego
    modo_dificil = models.BooleanField(default=False)
    usar_senuelo = models.BooleanField(default=False)
    senuelo_sabe_rol = models.BooleanField(default=True)
    hermanos_impostores = models.BooleanField(default=True)
    impostor_compulsivo = models.BooleanField(default=False)
    
    # Estado
    en_curso = models.BooleanField(default=False)
    palabra_secreta_actual = models.CharField(max_length=100, blank=True)

class JugadorLocal(models.Model):
    partida = models.ForeignKey(PartidaLocal, on_delete=models.CASCADE, related_name='jugadores')
    nombre = models.CharField(max_length=20)
    
    # Roles y Estado
    es_impostor = models.BooleanField(default=False)
    es_senuelo = models.BooleanField(default=False)
    palabra_asignada = models.CharField(max_length=100, blank=True)
    
    orden_turno = models.IntegerField(default=0)

    def __str__(self):
        return self.nombre

# --- 4. CONFIG GLOBAL DEL SISTEMA (ADMIN) ---

class ConfiguracionGlobal(models.Model):
    tiempo_sesion_minutos = models.IntegerField(default=30)
    tiempo_aviso_minutos = models.IntegerField(default=1)
    tiempo_afk_visual_minutos = models.IntegerField(default=1)
    
    # Timer configurable para Pass & Play
    tiempo_revelacion_segundos = models.IntegerField(default=5, verbose_name="Tiempo para ver rol (seg)")

    # Límite mínimo para crear categorías (Default 40 como pediste)
    min_packs_categoria = models.IntegerField(default=40, verbose_name="Mínimo packs requeridos")

    def save(self, *args, **kwargs):
        if not self.pk and ConfiguracionGlobal.objects.exists(): return
        super(ConfiguracionGlobal, self).save(*args, **kwargs)
    
    @classmethod
    def get_solo(cls):
        obj, created = cls.objects.get_or_create(id=1)
        return obj