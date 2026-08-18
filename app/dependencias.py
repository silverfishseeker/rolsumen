"""Comprobación y localización de las herramientas externas que hacen falta.

Whisper invoca `ffmpeg` como proceso aparte, así que necesita encontrarlo en el
PATH. En Windows esto falla con más frecuencia de la esperada: tras instalar
ffmpeg con winget, el PATH del sistema cambia pero los procesos ya abiertos
siguen con el antiguo, y el error que da Whisper en ese caso es
"[WinError 2] El sistema no puede encontrar el archivo especificado", que no
menciona ffmpeg por ninguna parte.

Para evitar ese callejón sin salida, aquí se busca ffmpeg también en las rutas
habituales de instalación y se añade al PATH del proceso si hace falta.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

# Sitios donde suele acabar ffmpeg en Windows aunque no esté en el PATH.
CARPETAS_HABITUALES = (
    r"%LOCALAPPDATA%\Microsoft\WinGet\Links",
    r"%ProgramData%\chocolatey\bin",
    r"%ProgramFiles%\ffmpeg\bin",
    r"C:\ffmpeg\bin",
)

# winget instala el paquete real aquí dentro, en una subcarpeta con versión.
RAIZ_PAQUETES_WINGET = r"%LOCALAPPDATA%\Microsoft\WinGet\Packages"


@dataclass
class Dependencia:
    """Estado de una herramienta externa."""

    nombre: str
    disponible: bool
    ruta: str = ""
    ayuda: str = ""


def _expandir(ruta: str) -> Path:
    return Path(os.path.expandvars(ruta))


def _buscar_en_paquetes_winget(ejecutable: str) -> Path | None:
    """Busca el ejecutable dentro de las carpetas de paquetes de winget."""
    raiz = _expandir(RAIZ_PAQUETES_WINGET)
    if not raiz.is_dir():
        return None
    try:
        for candidato in raiz.glob(f"*/**/{ejecutable}"):
            if candidato.is_file():
                return candidato
    except OSError:
        return None
    return None


def localizar(ejecutable: str = "ffmpeg") -> Path | None:
    """Devuelve la ruta del ejecutable, buscando más allá del PATH."""
    encontrado = shutil.which(ejecutable)
    if encontrado:
        return Path(encontrado)

    nombre_exe = f"{ejecutable}.exe" if os.name == "nt" else ejecutable

    for carpeta in CARPETAS_HABITUALES:
        candidato = _expandir(carpeta) / nombre_exe
        if candidato.is_file():
            return candidato

    return _buscar_en_paquetes_winget(nombre_exe)


def asegurar_en_path(ejecutable: str = "ffmpeg") -> bool:
    """Se asegura de que el ejecutable sea invocable desde este proceso.

    Si está instalado pero fuera del PATH (caso típico tras instalarlo con
    winget sin reiniciar la sesión), añade su carpeta al PATH del proceso.
    """
    if shutil.which(ejecutable):
        return True

    ruta = localizar(ejecutable)
    if ruta is None:
        return False

    carpeta = str(ruta.parent)
    os.environ["PATH"] = carpeta + os.pathsep + os.environ.get("PATH", "")
    return shutil.which(ejecutable) is not None


def comprobar_ffmpeg() -> Dependencia:
    """Estado de ffmpeg, que es lo que usa Whisper para leer el audio."""
    if asegurar_en_path("ffmpeg"):
        return Dependencia(
            nombre="ffmpeg", disponible=True, ruta=str(localizar("ffmpeg") or "")
        )
    return Dependencia(
        nombre="ffmpeg",
        disponible=False,
        ayuda=(
            "Whisper necesita ffmpeg para leer el audio. Instálalo con:\n"
            "    winget install Gyan.FFmpeg\n"
            "y reinicia la aplicación."
        ),
    )


def comprobar_gpu() -> Dependencia:
    """Comprueba si PyTorch puede usar la GPU (transcribir en CPU es mucho más lento)."""
    try:
        import torch
    except ImportError:
        return Dependencia(
            nombre="PyTorch",
            disponible=False,
            ayuda="Falta PyTorch. Instálalo con: pip install openai-whisper",
        )

    if torch.cuda.is_available():
        return Dependencia(
            nombre="GPU", disponible=True, ruta=torch.cuda.get_device_name(0)
        )

    return Dependencia(
        nombre="GPU",
        disponible=False,
        ayuda=(
            "No se detecta GPU: la transcripción irá por CPU y será mucho más "
            "lenta. Para usar la GPU:\n"
            "    pip install torch --index-url "
            "https://download.pytorch.org/whl/cu128 --upgrade"
        ),
    )


def comprobar_todo() -> list[Dependencia]:
    """Comprueba todas las dependencias externas de una vez."""
    return [comprobar_ffmpeg(), comprobar_gpu()]


def preparar_entorno() -> None:
    """Ajustes que conviene hacer una sola vez al arrancar la aplicación."""
    asegurar_en_path("ffmpeg")
