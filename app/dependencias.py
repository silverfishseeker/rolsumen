"""Comprobación de las herramientas externas que hacen falta.

Whisper invoca `ffmpeg` como proceso aparte, así que necesita encontrarlo en el
PATH. En Windows eso falla con facilidad: tras instalarlo con winget el PATH del
sistema cambia, pero los procesos ya abiertos siguen con el antiguo, y el error
que da entonces es `[WinError 2] El sistema no puede encontrar el archivo
especificado`, que no menciona ffmpeg. Por eso aquí se busca también en las
rutas habituales de instalación.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

CARPETAS_HABITUALES = (
    r"%LOCALAPPDATA%\Microsoft\WinGet\Links",
    r"%ProgramData%\chocolatey\bin",
    r"%ProgramFiles%\ffmpeg\bin",
    r"C:\ffmpeg\bin",
)

# winget instala el paquete real aquí dentro, en una subcarpeta con versión.
RAIZ_PAQUETES_WINGET = r"%LOCALAPPDATA%\Microsoft\WinGet\Packages"

AYUDA_FFMPEG = (
    "Whisper necesita ffmpeg para leer el audio. Instálalo con:\n"
    "    winget install Gyan.FFmpeg\n"
    "y reinicia la aplicación."
)

AYUDA_GPU = (
    "No se detecta GPU: la transcripción irá por CPU y será mucho más lenta. "
    "Para usar la GPU:\n"
    "    pip install torch --index-url "
    "https://download.pytorch.org/whl/cu128 --upgrade"
)


@dataclass
class Dependencia:
    nombre: str
    disponible: bool
    ruta: str = ""
    ayuda: str = ""


def _expandir(ruta: str) -> Path:
    return Path(os.path.expandvars(ruta))


def localizar(ejecutable: str = "ffmpeg") -> Path | None:
    """Ruta del ejecutable, buscando más allá del PATH."""
    if encontrado := shutil.which(ejecutable):
        return Path(encontrado)

    nombre = f"{ejecutable}.exe" if os.name == "nt" else ejecutable

    for carpeta in CARPETAS_HABITUALES:
        candidato = _expandir(carpeta) / nombre
        if candidato.is_file():
            return candidato

    raiz = _expandir(RAIZ_PAQUETES_WINGET)
    if raiz.is_dir():
        try:
            return next(
                (c for c in raiz.glob(f"*/**/{nombre}") if c.is_file()), None
            )
        except OSError:
            return None
    return None


def asegurar_en_path(ejecutable: str = "ffmpeg") -> bool:
    """Deja el ejecutable invocable desde este proceso, aunque no esté en el PATH."""
    if shutil.which(ejecutable):
        return True

    ruta = localizar(ejecutable)
    if ruta is None:
        return False

    os.environ["PATH"] = str(ruta.parent) + os.pathsep + os.environ.get("PATH", "")
    return shutil.which(ejecutable) is not None


def comprobar_ffmpeg() -> Dependencia:
    if asegurar_en_path("ffmpeg"):
        return Dependencia("ffmpeg", True, ruta=str(localizar("ffmpeg") or ""))
    return Dependencia("ffmpeg", False, ayuda=AYUDA_FFMPEG)


def comprobar_gpu() -> Dependencia:
    """Sin GPU la transcripción funciona, pero es mucho más lenta."""
    try:
        import torch
    except ImportError:
        return Dependencia(
            "PyTorch", False, ayuda="Falta PyTorch: pip install faster-whisper torch"
        )

    if torch.cuda.is_available():
        return Dependencia("GPU", True, ruta=torch.cuda.get_device_name(0))
    return Dependencia("GPU", False, ayuda=AYUDA_GPU)


def comprobar_todo() -> list[Dependencia]:
    return [comprobar_ffmpeg(), comprobar_gpu()]


def preparar_entorno() -> None:
    asegurar_en_path("ffmpeg")
