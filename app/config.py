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

# En la raíz del proyecto, para tenerlo a mano.
RUTA_CONFIG = RAIZ / "config.ini"

# Plantillas de los prompts, editables sin tocar el código.
DIR_PROMPTS = RAIZ / "app" / "prompts"

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
# Qué tipo de resumen generar. Cada modo usa sus propios prompts, que están
# en la carpeta prompts/<modo>/ y se pueden editar.
#
# Modos permitidos:
{modos}
modo = {modo_por_defecto}

# Carpeta ADICIONAL donde copiar los resúmenes.
# Los resúmenes se guardan siempre en datos/resumenes/; si indicas una ruta
# aquí, se guarda además una copia en ella.
# Ejemplo: carpeta_resumenes = C:\\Users\\tu_usuario\\Documents\\Rol
carpeta_resumenes =

# Idioma de las grabaciones, en código ISO (es, en, fr, de, it, pt...).
idioma = es

[modelos]
# Modelo de transcripción. Se descarga solo la primera vez que se usa.
#   large-v3  el más preciso (recomendado)
#   medium    más rápido, comete más fallos
#   small     rápido y ligero
#   base      muy rápido, poco fiable
transcripcion = large-v3

# Precisión numérica de la transcripción. Afecta a la memoria de vídeo:
#   float16       calidad máxima (recomendado con 8 GB de VRAM o más)
#   int8_float16  ahorra memoria, casi misma calidad
#   int8          el más ligero, para GPUs pequeñas o CPU
precision = float16

# Dónde transcribir: auto (usa la GPU si la hay), cuda o cpu.
dispositivo = auto

# Modelo de Ollama que redacta la crónica. Debe estar descargado
# (comprobar con: ollama list).
resumen = qwen3:8b

# Tamaño de contexto que se le pide a Ollama. Por defecto Ollama usa 4096,
# muy poco para esto. Súbelo si tienes VRAM de sobra; bájalo si se queda
# sin memoria.
contexto_resumen = 16384

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
class Modelos:
    """Qué modelos se usan y cómo se ejecutan."""

    transcripcion: str = "large-v3"
    precision: str = "float16"
    dispositivo: str = "auto"
    resumen: str = "qwen3:8b"
    contexto_resumen: int = 16384

    def dispositivo_efectivo(self) -> str:
        """Resuelve 'auto' mirando si hay GPU disponible."""
        if self.dispositivo != "auto":
            return self.dispositivo
        try:
            import torch

            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"

    def precision_efectiva(self) -> str:
        """En CPU no existe float16: se degrada a int8 automáticamente."""
        if self.dispositivo_efectivo() == "cpu" and self.precision == "float16":
            return "int8"
        return self.precision


# Modos de resumen disponibles, con la descripción que se vuelca en el
# config.ini. Añadir uno aquí basta para que aparezca documentado en el
# archivo de configuración: así la lista no puede quedarse desfasada.
DESCRIPCION_MODOS = {
    "rol": (
        "Crónica de partida de rol. Recoge solo la acción DENTRO de la "
        "ficción e ignora la charla de la mesa (reglas, tiradas, bromas, "
        "temas ajenos a la partida)."
    ),
    "conversacion": (
        "Resumen de una conversación normal. Recoge todos los temas que se "
        "trataron, sin descartar ninguno por informal, pero condensándolos."
    ),
}

MODOS = tuple(DESCRIPCION_MODOS)
MODO_POR_DEFECTO = "rol"


def _comentario_modos(ancho: int = 76) -> str:
    """Genera la lista de modos que se escribe como comentario en config.ini.

    Se construye a partir de DESCRIPCION_MODOS para que la lista del archivo
    no pueda quedarse desfasada respecto a los modos que existen de verdad.
    """
    import textwrap

    # '#' + 3 espacios + nombre (13) + 1 espacio = la descripción empieza aquí.
    columna = 18
    sangria = " " * (columna - 1)  # el '#' ocupa la primera posición

    lineas = []
    for nombre, descripcion in DESCRIPCION_MODOS.items():
        envuelto = textwrap.wrap(descripcion, width=ancho - columna)
        lineas.append(f"#   {nombre:<13} {envuelto[0]}")
        lineas.extend(f"#{sangria}{resto}" for resto in envuelto[1:])
    return "\n".join(lineas)


@dataclass
class Config:
    """Configuración efectiva de la aplicación."""

    carpeta_resumenes_extra: Path | None = None
    modo: str = MODO_POR_DEFECTO
    idioma: str = "es"
    modelos: Modelos = field(default_factory=Modelos)
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


def plantilla_config() -> str:
    """El contenido del config.ini por defecto, con los modos ya listados."""
    return CONFIG_EJEMPLO.format(
        modos=_comentario_modos(), modo_por_defecto=MODO_POR_DEFECTO
    )


def crear_config_si_falta(ruta: Path = RUTA_CONFIG) -> bool:
    """Crea el archivo de configuración con valores por defecto si no existe.

    Devuelve True si lo ha creado, False si ya existía.
    """
    if ruta.exists():
        return False
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(plantilla_config(), encoding="utf-8")
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

        cfg.idioma = general.get("idioma", cfg.idioma).strip()

        modo = general.get("modo", "").strip().lower()
        # Un modo desconocido vuelve al de por defecto en vez de romper: es
        # preferible generar un resumen a no generar ninguno.
        cfg.modo = modo if modo in MODOS else MODO_POR_DEFECTO

    if parser.has_section("modelos"):
        modelos = parser["modelos"]
        try:
            contexto = int(modelos.get("contexto_resumen", "").strip() or 0)
        except ValueError:
            contexto = 0

        cfg.modelos = Modelos(
            transcripcion=modelos.get(
                "transcripcion", cfg.modelos.transcripcion
            ).strip()
            or cfg.modelos.transcripcion,
            precision=modelos.get("precision", cfg.modelos.precision).strip()
            or cfg.modelos.precision,
            dispositivo=modelos.get("dispositivo", cfg.modelos.dispositivo).strip()
            or cfg.modelos.dispositivo,
            resumen=modelos.get("resumen", cfg.modelos.resumen).strip()
            or cfg.modelos.resumen,
            contexto_resumen=contexto or cfg.modelos.contexto_resumen,
        )

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
