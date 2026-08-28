"""Ejecución de programas externos sin abrir ventanas de consola.

El acceso directo lanza la aplicación con `pythonw.exe`, que no tiene consola.
Windows entonces le crea una **nueva y visible** a cada subproceso, y como la
aplicación consulta a Docker cada pocos segundos, la pantalla se llena de
ventanas negras que aparecen y desaparecen sin parar.

`CREATE_NO_WINDOW` lo evita. Hay que pasarlo en todas las llamadas: basta con
que se olvide una que se ejecute a menudo para que el parpadeo vuelva.
"""

from __future__ import annotations

import subprocess
import sys

# La bandera sólo existe en Windows; en el resto se pasa un diccionario vacío.
SIN_CONSOLA: dict = (
    {"creationflags": subprocess.CREATE_NO_WINDOW}
    if sys.platform == "win32"
    else {}
)


def ejecutar(argumentos: list[str], **extra):
    """`subprocess.run` sin ventana de consola."""
    return subprocess.run(argumentos, **SIN_CONSOLA, **extra)


def lanzar(argumentos: list[str], **extra):
    """`subprocess.Popen` sin ventana de consola."""
    return subprocess.Popen(argumentos, **SIN_CONSOLA, **extra)
