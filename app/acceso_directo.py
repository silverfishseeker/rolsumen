"""Crea un acceso directo para abrir Rolsumen sin usar la terminal.

    python -m app.acceso_directo                 en la raíz del proyecto
    python -m app.acceso_directo --escritorio    además, en el escritorio

Se genera un `.lnk` y no un `.bat` por dos razones: un `.bat` no puede llevar
icono propio, y abre una ventana de consola negra detrás de la aplicación.

El acceso directo apunta a `pythonw.exe`, que es el intérprete sin consola.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from . import config as cfg
from .procesos import SIN_CONSOLA

NOMBRE = "Rolsumen.lnk"

# PowerShell es la vía estándar en Windows para escribir un .lnk sin añadir
# dependencias (pywin32 haría falta si no).
PLANTILLA = """
$enlace = (New-Object -ComObject WScript.Shell).CreateShortcut('{destino}')
$enlace.TargetPath = '{interprete}'
$enlace.Arguments = '-m app.main'
$enlace.WorkingDirectory = '{raiz}'
$enlace.IconLocation = '{icono}'
$enlace.Description = 'Crónicas automáticas de partidas grabadas en Discord'
$enlace.Save()
"""


def interprete_sin_consola() -> Path:
    """`pythonw.exe` si está, y si no el intérprete normal.

    Con `python.exe` la aplicación funciona igual, pero deja una consola negra
    abierta detrás de la ventana mientras dure la sesión.
    """
    actual = Path(sys.executable)
    sin_consola = actual.with_name("pythonw.exe")
    return sin_consola if sin_consola.exists() else actual


def crear(destino: Path | None = None) -> Path:
    if sys.platform != "win32":
        raise RuntimeError(
            "Los accesos directos .lnk son de Windows. En otros sistemas, "
            "lanza la aplicación con: python -m app.main"
        )

    destino = destino or cfg.RAIZ / NOMBRE
    guion = PLANTILLA.format(
        destino=destino,
        interprete=interprete_sin_consola(),
        raiz=cfg.RAIZ,
        icono=cfg.RUTA_ICONO,
    )

    proceso = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", guion],
        capture_output=True,
        text=True,
        timeout=60,
        **SIN_CONSOLA,
    )
    if proceso.returncode != 0 or not destino.exists():
        raise RuntimeError(
            f"No se pudo crear el acceso directo: {proceso.stderr.strip()}"
        )
    return destino


def escritorio() -> Path:
    return Path.home() / "Desktop"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="acceso_directo",
        description="Crea un acceso directo para abrir Rolsumen con doble clic.",
    )
    parser.add_argument(
        "--escritorio",
        action="store_true",
        help="crea también una copia en el escritorio",
    )
    argumentos = parser.parse_args(argv)

    if not cfg.RUTA_ICONO.exists():
        print(
            f"Falta el icono en {cfg.RUTA_ICONO}. "
            "Genéralo con: python -m app.recursos.generar_icono",
            file=sys.stderr,
        )
        return 1

    try:
        print(f"Creado {crear()}")
        if argumentos.escritorio:
            carpeta = escritorio()
            if not carpeta.is_dir():
                print(
                    f"No se encontró el escritorio en {carpeta}.", file=sys.stderr
                )
                return 1
            print(f"Creado {crear(carpeta / NOMBRE)}")
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
