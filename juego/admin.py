from django.contrib import admin
from .models import Categoria, PackPalabras, ConfiguracionGlobal, SesionGameMaster

@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'es_publica', 'creada_por_admin', 'cantidad_partidas', 'ranking')
    search_fields = ('nombre',)

@admin.register(PackPalabras)
class PackPalabrasAdmin(admin.ModelAdmin):
    list_display = ('palabra_principal', 'categoria')
    list_filter = ('categoria',)

admin.site.register(ConfiguracionGlobal)
admin.site.register(SesionGameMaster)