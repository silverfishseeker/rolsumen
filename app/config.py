"""Lectura de la configuración del usuario y rutas del proyecto.

La configuración es deliberadamente mínima: todo tiene un valor por defecto
razonable, de modo que la aplicación funcione sin que el usuario toque nada.
"""

from __future__ import annotations

import configparser
import re
import textwrap
from dataclasses import dataclass, field, fields
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

# Cómo avanza el trabajo:
{ejecuciones}
ejecucion = {ejecucion_por_defecto}

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
# sin memoria: si el contexto no cabe en la GPU, Ollama pasa capas a la CPU
# y la generación se vuelve lentísima.
contexto_resumen = {contexto}

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

    def faltantes(self) -> list[str]:
        """Nombres de las credenciales que siguen sin rellenar."""
        return [c.name for c in fields(self) if not getattr(self, c.name)]

    @property
    def completas(self) -> bool:
        return not self.faltantes()


# El techo no lo marca el modelo sino la memoria de vídeo: si el modelo y su
# caché de atención no caben, Ollama descarga capas a la CPU y la generación se
# desploma. Medido con qwen3:8b en 8 GB: 8192 va al 100% en GPU, 12288 ya no.
CONTEXTO_POR_DEFECTO = 8192


@dataclass
class Modelos:
    """Qué modelos se usan y cómo se ejecutan."""

    transcripcion: str = "large-v3"
    precision: str = "float16"
    dispositivo: str = "auto"
    resumen: str = "qwen3:8b"
    contexto_resumen: int = CONTEXTO_POR_DEFECTO

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

# Cómo avanza el trabajo de una grabación a su crónica.
DESCRIPCION_EJECUCION = {
    "automatico": (
        "Al terminar una grabacion en Craig, la transcribe y la resume sin "
        "intervención. Las grabaciones anteriores a abrir la app no se tocan."
    ),
    "manual": (
        "No hace nada por su cuenta: cada paso se lanza desde la pestaña "
        "Trabajo."
    ),
}
EJECUCIONES = tuple(DESCRIPCION_EJECUCION)
EJECUCION_POR_DEFECTO = "automatico"


def _comentario_modos(descripciones: dict | None = None, ancho: int = 76) -> str:
    """Genera la lista de modos que se escribe como comentario en config.ini.

    Se construye a partir de DESCRIPCION_MODOS para que la lista del archivo
    no pueda quedarse desfasada respecto a los modos que existen de verdad.
    """
    # '#' + 3 espacios + nombre (13) + 1 espacio = la descripción empieza aquí.
    columna = 18
    sangria = " " * (columna - 1)  # el '#' ocupa la primera posición

    lineas = []
    for nombre, descripcion in (descripciones or DESCRIPCION_MODOS).items():
        envuelto = textwrap.wrap(descripcion, width=ancho - columna)
        lineas.append(f"#   {nombre:<13} {envuelto[0]}")
        lineas.extend(f"#{sangria}{resto}" for resto in envuelto[1:])
    return "\n".join(lineas)


@dataclass
class Config:
    """Configuración efectiva de la aplicación."""

    carpeta_resumenes_extra: Path | None = None
    modo: str = MODO_POR_DEFECTO
    ejecucion: str = EJECUCION_POR_DEFECTO
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
        modos=_comentario_modos(DESCRIPCION_MODOS),
        modo_por_defecto=MODO_POR_DEFECTO,
        ejecuciones=_comentario_modos(DESCRIPCION_EJECUCION),
        ejecucion_por_defecto=EJECUCION_POR_DEFECTO,
        contexto=CONTEXTO_POR_DEFECTO,
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


def _texto(seccion, clave: str, defecto: str) -> str:
    """Valor de una clave; en blanco cuenta como ausente."""
    return seccion.get(clave, "").strip() or defecto


def _entero(seccion, clave: str, defecto: int) -> int:
    try:
        return int(seccion.get(clave, "").strip()) or defecto
    except ValueError:
        return defecto


def cargar(ruta: Path = RUTA_CONFIG) -> Config:
    """Carga la configuración; sin archivo, usa los valores por defecto."""
    cfg = Config()
    if not ruta.exists():
        return cfg

    # Sin interpolación: las rutas de Windows pueden llevar '%' y '$'.
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(ruta, encoding="utf-8")

    if parser.has_section("general"):
        general = parser["general"]

        carpeta = _texto(general, "carpeta_resumenes", "")
        if carpeta:
            cfg.carpeta_resumenes_extra = Path(carpeta).expanduser()

        cfg.idioma = _texto(general, "idioma", cfg.idioma)

        # Un modo desconocido cae al de por defecto: mejor generar un resumen
        # con el modo equivocado que no generar ninguno.
        modo = _texto(general, "modo", "").lower()
        cfg.modo = modo if modo in MODOS else MODO_POR_DEFECTO

        ejecucion = _texto(general, "ejecucion", "").lower()
        cfg.ejecucion = (
            ejecucion if ejecucion in EJECUCIONES else EJECUCION_POR_DEFECTO
        )

    if parser.has_section("modelos"):
        m = parser["modelos"]
        por_defecto = cfg.modelos
        cfg.modelos = Modelos(
            transcripcion=_texto(m, "transcripcion", por_defecto.transcripcion),
            precision=_texto(m, "precision", por_defecto.precision),
            dispositivo=_texto(m, "dispositivo", por_defecto.dispositivo),
            resumen=_texto(m, "resumen", por_defecto.resumen),
            contexto_resumen=_entero(
                m, "contexto_resumen", por_defecto.contexto_resumen
            ),
        )

    if parser.has_section("discord"):
        d = parser["discord"]
        cfg.discord = Credenciales(
            token_bot=_texto(d, "token_bot", ""),
            secreto_cliente=_texto(d, "secreto_cliente", ""),
            id_aplicacion=_texto(d, "id_aplicacion", ""),
        )

    if parser.has_section("jugadores"):
        cfg.jugadores = {
            usuario.lower(): personaje.strip()
            for usuario, personaje in parser["jugadores"].items()
            if personaje.strip()
        }

    return cfg


_ASIGNACION = re.compile(r"^(\s*)([^#;=\s][^=]*?)(\s*=\s*)(.*)$")
_SECCION = re.compile(r"^\s*\[([^\]]+)\]\s*$")


def _seccion_de(linea: str) -> str | None:
    encontrada = _SECCION.match(linea)
    return encontrada.group(1).strip().lower() if encontrada else None


def guardar_valores(
    cambios: dict[tuple[str, str], str], ruta: Path = RUTA_CONFIG
) -> None:
    """Escribe valores en config.ini **conservando comentarios y orden**.

    `configparser` sabe leer el archivo pero al reescribirlo tira todos los
    comentarios, que aquí son la documentación de cada opción. Por eso se
    sustituye el valor línea a línea y se deja el resto intacto.

    Las claves que no existan se añaden al final de su sección; las secciones
    que falten, al final del archivo.
    """
    if not cambios:
        return

    pendientes = {(s.lower(), c.lower()): str(v) for (s, c), v in cambios.items()}
    lineas = (
        ruta.read_text(encoding="utf-8").splitlines() if ruta.exists() else []
    )

    resultado: list[str] = []
    seccion = ""
    for linea in lineas:
        nombre = _seccion_de(linea)
        if nombre is not None:
            seccion = nombre
            resultado.append(linea)
            continue

        asignacion = _ASIGNACION.match(linea)
        if asignacion:
            clave = asignacion.group(2).strip().lower()
            valor = pendientes.pop((seccion, clave), None)
            if valor is not None:
                sangria, nombre_original, _, _ = asignacion.groups()
                resultado.append(f"{sangria}{nombre_original.strip()} = {valor}")
                continue
        resultado.append(linea)

    for (seccion_faltante, clave), valor in pendientes.items():
        resultado = _insertar(resultado, seccion_faltante, f"{clave} = {valor}")

    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(
        "\n".join(resultado).rstrip("\n") + "\n",
        encoding="utf-8",
    )


def _insertar(lineas: list[str], seccion: str, asignacion: str) -> list[str]:
    """Mete una asignación al final de su sección, creándola si no existe."""
    inicio = next(
        (i for i, l in enumerate(lineas) if _seccion_de(l) == seccion), None
    )
    if inicio is None:
        cola = lineas + ([""] if lineas and lineas[-1] else [])
        return cola + [f"[{seccion}]", asignacion]

    fin = next(
        (
            i
            for i in range(inicio + 1, len(lineas))
            if _seccion_de(lineas[i]) is not None
        ),
        len(lineas),
    )
    # Detrás del último contenido, no de las lineas en blanco que separan.
    while fin > inicio + 1 and not lineas[fin - 1].strip():
        fin -= 1
    return lineas[:fin] + [asignacion] + lineas[fin:]


def guardar_jugadores(mapa: dict[str, str], ruta: Path = RUTA_CONFIG) -> None:
    """Reemplaza la sección [jugadores] conservando sus comentarios."""
    lineas = (
        ruta.read_text(encoding="utf-8").splitlines() if ruta.exists() else []
    )
    inicio = next(
        (i for i, l in enumerate(lineas) if _seccion_de(l) == "jugadores"), None
    )
    nuevas = [f"{usuario} = {personaje}" for usuario, personaje in mapa.items()]

    if inicio is None:
        cuerpo = lineas + ([""] if lineas and lineas[-1] else [])
        cuerpo += ["[jugadores]"] + nuevas
    else:
        fin = next(
            (
                i
                for i in range(inicio + 1, len(lineas))
                if _seccion_de(lineas[i]) is not None
            ),
            len(lineas),
        )
        # Se conservan los comentarios de la sección y se tiran las asignaciones.
        comentarios = [
            l for l in lineas[inicio + 1 : fin] if not _ASIGNACION.match(l)
        ]
        while comentarios and not comentarios[-1].strip():
            comentarios.pop()
        cuerpo = lineas[: inicio + 1] + comentarios + nuevas + lineas[fin:]

    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(
        "\n".join(cuerpo).rstrip("\n") + "\n",
        encoding="utf-8",
    )


def asegurar_carpetas() -> None:
    """Crea las carpetas internas de datos si no existen."""
    for carpeta in (DIR_GRABACIONES, DIR_TRANSCRIPCIONES, DIR_RESUMENES, DIR_REC):
        carpeta.mkdir(parents=True, exist_ok=True)
