"""De lo que escribe el usuario a algo reproducible.

Se mira en este orden, y el orden importa:

  1. Un archivo de la carpeta local. Suena siempre, sin depender de internet
     ni de que YouTube haya cambiado algo esta semana.
  2. Una URL, que se le pasa tal cual a yt-dlp.
  3. Lo demás: búsqueda en YouTube, primer resultado.

De YouTube **no se descarga nada**: yt-dlp da la URL del flujo de audio y
ffmpeg la lee sobre la marcha.
"""

from __future__ import annotations

import re
from pathlib import Path

from .lista import Pista

# Lo que ffmpeg sabe leer y suele haber en una carpeta de ambientación.
EXTENSIONES = (".mp3", ".ogg", ".opus", ".m4a", ".flac", ".wav", ".webm", ".aac")

_URL = re.compile(r"^https?://", re.IGNORECASE)

# Sin descargar, sin playlists y sin ruido por la salida estándar.
OPCIONES_YTDLP = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "default_search": "ytsearch",
    # Evita que yt-dlp se quede colgado si una fuente no responde.
    "socket_timeout": 20,
}


class ErrorBusqueda(RuntimeError):
    """No se encontró nada que reproducir."""


def buscar_local(consulta: str, carpeta: str) -> Pista | None:
    """Un archivo de la carpeta cuyo nombre contenga lo buscado.

    La comparación ignora mayúsculas y acentos no: se busca lo que la gente
    escribiría, «lluvia» para «Lluvia en el bosque.mp3».
    """
    if not carpeta or not consulta.strip():
        return None

    raiz = Path(carpeta)
    if not raiz.is_dir():
        return None

    agujas = consulta.strip().lower()
    candidatos = [
        a
        for a in sorted(raiz.rglob("*"))
        if a.is_file() and a.suffix.lower() in EXTENSIONES
    ]

    # Primero una coincidencia exacta del nombre; si no, que lo contenga.
    for archivo in candidatos:
        if archivo.stem.lower() == agujas:
            return Pista(archivo.stem, str(archivo), "", local=True)
    for archivo in candidatos:
        if agujas in archivo.stem.lower():
            return Pista(archivo.stem, str(archivo), "", local=True)
    return None


def _extraer(consulta: str) -> dict:
    """Metadatos de yt-dlp para una URL o una búsqueda."""
    try:
        import yt_dlp
    except ImportError as exc:  # pragma: no cover - depende de la instalación
        raise ErrorBusqueda(
            "Falta yt-dlp. Instálalo con: pip install -U yt-dlp"
        ) from exc

    objetivo = consulta if _URL.match(consulta) else f"ytsearch1:{consulta}"
    try:
        with yt_dlp.YoutubeDL(OPCIONES_YTDLP) as ydl:
            datos = ydl.extract_info(objetivo, download=False)
    except Exception as exc:  # noqa: BLE001 - yt-dlp lanza de todo
        raise ErrorBusqueda(f"YouTube no devolvió nada: {exc}") from exc

    # Una búsqueda devuelve una lista de resultados; una URL, el vídeo.
    if datos and datos.get("entries"):
        entradas = [e for e in datos["entries"] if e]
        if not entradas:
            raise ErrorBusqueda("La búsqueda no dio resultados.")
        datos = entradas[0]
    if not datos:
        raise ErrorBusqueda("La búsqueda no dio resultados.")
    return datos


def buscar_en_youtube(consulta: str) -> Pista:
    datos = _extraer(consulta)
    origen = datos.get("url")
    if not origen:
        raise ErrorBusqueda("No se pudo obtener el audio de ese resultado.")
    return Pista(
        titulo=datos.get("title") or consulta,
        origen=origen,
        pedida_por="",
        local=False,
        duracion=datos.get("duration"),
    )


def resolver(consulta: str, carpeta: str, pedida_por: str) -> Pista:
    """Lo que escribió el usuario, convertido en una pista concreta."""
    consulta = consulta.strip()
    if not consulta:
        raise ErrorBusqueda("Dime qué quieres escuchar.")

    local = buscar_local(consulta, carpeta)
    pista = local or buscar_en_youtube(consulta)
    # `pedida_por` se rellena aquí y no en la búsqueda: a quién responder no
    # es asunto de encontrar la música.
    return Pista(
        titulo=pista.titulo,
        origen=pista.origen,
        pedida_por=pedida_por,
        local=pista.local,
        duracion=pista.duracion,
    )
