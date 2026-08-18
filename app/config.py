"""Lectura de la configuración del usuario y rutas del proyecto.

La configuración es deliberadamente mínima: todo tiene un valor por defecto
razonable, de modo que la aplicación funcione sin que el usuario toque nada.
"""

from __future__ import annotations

import configparser
from dataclasses import dataclass, field
from pathlib import Path

# Raíz del proyecto (este archivo vive en <raíz>/app/config.py)
RAIZ = Path(__file__).resolve().parent.parent

RUTA_CONFIG = RAIZ / "app" / "config.ini"

# Carpetas internas: no configurables, siempre en el mismo sitio.
DIR_DATOS = RAIZ / "datos"
DIR_GRABACIONES = DIR_DATOS / "grabaciones"
DIR_TRANSCRIPCIONES = DIR_DATOS / "transcripciones"
DIR_RESUMENES = DIR_DATOS / "resumenes"

# Craig self-hosted
DIR_CRAIG = RAIZ / "app" / "craig"
DIR_REC = DIR_CRAIG / "rec"

# Registro de grabaciones ya procesadas (idempotencia)
RUTA_PROCESADAS = DIR_DATOS / "procesadas.json"

CONFIG_EJEMPLO = """\
# Configuración de Rolsumen.
#
# Salvo la sección [discord], todo es opcional: con el archivo tal cual la
# aplicación funciona con valores por defecto.

[discord]
# Credenciales de tu aplicación de Discord, necesarias para que Craig grabe.
# Se sacan de https://discord.com/developers/applications
#
# Este archivo NO se sube al repositorio, así que es seguro ponerlas aquí.
# La aplicación las copia sola a la configuración interna de Craig.

# Pestaña "Bot" -> botón "Reset Token"
token_bot =

# Pestaña "OAuth2" -> "Client Secret" -> botón "Reset Secret"
secreto_cliente =

# Pestaña "General Information" -> "Application ID"
# (sirve a la vez de APP_ID y de CLIENT_ID)
id_aplicacion = 1539028879342047263

[general]
# Carpeta ADICIONAL donde copiar los resúmenes.
# Los resúmenes se guardan siempre en datos/resumenes/; si indicas una ruta
# aquí, se guarda además una copia en ella.
# Ejemplo: carpeta_resumenes = C:\\Users\\tu_usuario\\Documents\\Rol
carpeta_resumenes =

# Modelo de Whisper para transcribir. large-v3 es el recomendado.
# Alternativas más rápidas y menos precisas: medium, small, base.
modelo_whisper = large-v3

# Modelo de Ollama para generar la cronología.
modelo_ollama = qwen3:8b

# Idioma de las grabaciones.
idioma = Spanish

[jugadores]
# Asocia cada usuario de Discord con el nombre de su personaje.
# Si un usuario no aparece aquí, se usa su nombre de Discord tal cual.
# Ejemplo:
# silverfishlord = Kaelen, el bardo
# caliece = Marina, la exploradora
"""


@dataclass
class Credenciales:
    """Credenciales de la aplicación de Discord que necesita Craig."""

    token_bot: str = ""
    secreto_cliente: str = ""
    id_aplicacion: str = ""

    @property
    def completas(self) -> bool:
        return bool(self.token_bot and self.secreto_cliente and self.id_aplicacion)

    def faltantes(self) -> list[str]:
        """Nombres legibles de lo que falta por rellenar."""
        pendientes = []
        if not self.id_aplicacion:
            pendientes.append("id_aplicacion")
        if not self.token_bot:
            pendientes.append("token_bot")
        if not self.secreto_cliente:
            pendientes.append("secreto_cliente")
        return pendientes


@dataclass
class Config:
    """Configuración efectiva de la aplicación."""

    carpeta_resumenes_extra: Path | None = None
    modelo_whisper: str = "large-v3"
    modelo_ollama: str = "qwen3:8b"
    idioma: str = "Spanish"
    jugadores: dict[str, str] = field(default_factory=dict)
    discord: Credenciales = field(default_factory=Credenciales)

    def nombre_personaje(self, usuario_discord: str) -> str:
        """Devuelve el nombre del personaje, o el nick de Discord si no hay mapeo."""
        return self.jugadores.get(usuario_discord.lower(), usuario_discord)

    def destinos_resumen(self) -> list[Path]:
        """Carpetas donde debe guardarse cada resumen."""
        destinos = [DIR_RESUMENES]
        if self.carpeta_resumenes_extra is not None:
            destinos.append(self.carpeta_resumenes_extra)
        return destinos


def crear_config_si_falta(ruta: Path = RUTA_CONFIG) -> bool:
    """Crea el archivo de configuración con valores por defecto si no existe.

    Devuelve True si lo ha creado, False si ya existía.
    """
    if ruta.exists():
        return False
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(CONFIG_EJEMPLO, encoding="utf-8")
    return True


def cargar(ruta: Path = RUTA_CONFIG) -> Config:
    """Carga la configuración. Si el archivo no existe, usa los valores por defecto."""
    cfg = Config()

    if not ruta.exists():
        return cfg

    # Sin interpolación: las rutas de Windows pueden llevar '%' y '$'.
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(ruta, encoding="utf-8")

    if parser.has_section("general"):
        general = parser["general"]

        carpeta = general.get("carpeta_resumenes", "").strip()
        if carpeta:
            cfg.carpeta_resumenes_extra = Path(carpeta).expanduser()

        cfg.modelo_whisper = general.get("modelo_whisper", cfg.modelo_whisper).strip()
        cfg.modelo_ollama = general.get("modelo_ollama", cfg.modelo_ollama).strip()
        cfg.idioma = general.get("idioma", cfg.idioma).strip()

    if parser.has_section("discord"):
        discord = parser["discord"]
        cfg.discord = Credenciales(
            token_bot=discord.get("token_bot", "").strip(),
            secreto_cliente=discord.get("secreto_cliente", "").strip(),
            id_aplicacion=discord.get("id_aplicacion", "").strip(),
        )

    if parser.has_section("jugadores"):
        cfg.jugadores = {
            usuario.lower(): personaje.strip()
            for usuario, personaje in parser["jugadores"].items()
            if personaje.strip()
        }

    return cfg


def asegurar_carpetas() -> None:
    """Crea las carpetas internas de datos si no existen."""
    for carpeta in (DIR_GRABACIONES, DIR_TRANSCRIPCIONES, DIR_RESUMENES, DIR_REC):
        carpeta.mkdir(parents=True, exist_ok=True)
