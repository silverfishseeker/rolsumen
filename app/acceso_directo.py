"""Crea un acceso directo para abrir Rolsumen sin usar la terminal.

    python -m app.acceso_directo                 en la raíz del proyecto
    python -m app.acceso_directo --escritorio    además, en el escritorio

Se genera un `.lnk` y no un `.bat` por dos razones: un `.bat` no puede llevar
icono propio, y abre una ventana de consola negra detrás de la aplicación.

## Por qué no vale cualquier intérprete

El Python de Microsoft Store se ejecuta como paquete MSIX. Windows le impone la
identidad y el icono del paquete e **ignora** lo que el proceso declare, así que
la barra de tareas muestra el icono de Python por muy bien que la ventana tenga
el suyo. Comprobado: los mismos archivos lanzados con un Python normal muestran
el icono correcto.

Por eso se busca un intérprete **no empaquetado**. Si a ese le faltan las
dependencias, se le prestan las del intérprete actual pasándole la ruta con
`--paquetes`, y así no hay que descargar nada.
"""

from __future__ import annotations

import argparse
import os
import site
import subprocess
import sys
from pathlib import Path

from . import config as cfg
from .procesos import SIN_CONSOLA

NOMBRE = "Rolsumen.lnk"

# El guion vive aparte porque, además de las propiedades corrientes, escribe
# System.AppUserModel.ID en el acceso directo, y eso pide interoperabilidad COM
# que en una cadena de Python resultaría ilegible.
GUION = cfg.RAIZ / "app" / "recursos" / "acceso_directo.ps1"

# Los alias de la Microsoft Store viven aquí; un intérprete bajo esta carpeta
# arrastra la identidad de paquete que estropea el icono.
MARCA_EMPAQUETADO = "windowsapps"

# Con qué se comprueba si un intérprete se basta solo.
MODULO_TESTIGO = "faster_whisper"


def _es_empaquetado(ruta: Path) -> bool:
    return MARCA_EMPAQUETADO in str(ruta).lower()


def candidatos() -> list[Path]:
    """Intérpretes sin consola que podrían servir, del mejor al peor.

    Sólo los de la misma versión: los paquetes que se prestan traen binarios
    compilados, y mezclar versiones no funcionaría.
    """
    version = f"{sys.version_info.major}{sys.version_info.minor}"
    encontrados: list[Path] = []

    for carpeta in (
        Path.home() / "AppData" / "Local" / "Programs" / "Python",
        Path("C:/"),
        Path(sys.base_prefix).parent,
    ):
        try:
            for sub in sorted(carpeta.glob(f"Python{version}*")):
                candidato = sub / "pythonw.exe"
                if candidato.is_file() and not _es_empaquetado(candidato):
                    encontrados.append(candidato)
        except OSError:
            continue

    actual = Path(sys.executable).with_name("pythonw.exe")
    if actual.is_file():
        encontrados.append(actual)
    return encontrados


def _entorno_limpio() -> dict[str, str]:
    """El entorno que tendrá la aplicación al abrirse desde el Explorador.

    El Python de Microsoft Store exporta `PYTHONUSERBASE` apuntando a sus
    propios paquetes, y los procesos hijos lo heredan. Sondear con esa variable
    puesta da un falso positivo: el intérprete parece tener las dependencias
    porque ve las del otro, pero al abrir la aplicación con doble clic no las
    encuentra y se queda sin torch, es decir, sin GPU.
    """
    return {c: v for c, v in os.environ.items() if not c.startswith("PYTHON")}


def _tiene_las_dependencias(interprete: Path) -> bool:
    try:
        proceso = subprocess.run(
            [str(interprete), "-c", f"import {MODULO_TESTIGO}"],
            capture_output=True,
            timeout=180,
            env=_entorno_limpio(),
            **SIN_CONSOLA,
        )
        return proceso.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


def interprete_sin_consola() -> Path:
    """El mejor intérprete para el acceso directo.

    Se prefiere uno no empaquetado aunque le falten las dependencias: se le
    pueden prestar, y a cambio el icono de la barra de tareas funciona.
    """
    posibles = candidatos()
    for candidato in posibles:
        if not _es_empaquetado(candidato):
            return candidato
    return posibles[0] if posibles else Path(sys.executable)


def paquetes_prestados(interprete: Path) -> str:
    """Ruta de paquetes que prestarle, o cadena vacía si no le hace falta."""
    if interprete == Path(sys.executable).with_name("pythonw.exe"):
        return ""
    if _tiene_las_dependencias(interprete):
        return ""
    return site.getusersitepackages()


def crear(destino: Path | None = None) -> Path:
    if sys.platform != "win32":
        raise RuntimeError(
            "Los accesos directos .lnk son de Windows. En otros sistemas, "
            "lanza la aplicación con: python -m app.main"
        )

    destino = destino or cfg.RAIZ / NOMBRE
    from .gui import ID_APLICACION

    interprete = interprete_sin_consola()
    argumentos = "-m app.main"
    if prestados := paquetes_prestados(interprete):
        argumentos += f' --paquetes "{prestados}"'

    proceso = subprocess.run(
        [
            "powershell", "-NoProfile", "-NonInteractive",
            "-ExecutionPolicy", "Bypass", "-File", str(GUION),
            "-Destino", str(destino),
            "-Interprete", str(interprete),
            "-Argumentos", argumentos,
            "-Carpeta", str(cfg.RAIZ),
            "-Icono", str(cfg.RUTA_ICONO),
            "-Id", ID_APLICACION,
        ],
        capture_output=True,
        text=True,
        timeout=240,
        **SIN_CONSOLA,
    )
    if proceso.returncode != 0 or not destino.exists():
        raise RuntimeError(
            f"No se pudo crear el acceso directo: "
            f"{(proceso.stderr or proceso.stdout).strip()}"
        )
    return destino


def escritorio() -> Path:
    return Path.home() / "Desktop"


def menu_inicio() -> Path:
    """Carpeta de programas del menú Inicio del usuario.

    Windows 11 ancla a Inicio desde su lista de aplicaciones, y ahí sólo salen
    los accesos directos que viven en esta carpeta. Un `.lnk` suelto en una
    carpeta cualquiera no cuenta como aplicación instalada, y por eso anclarlo
    no funciona bien.
    """
    return (
        Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
    )


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
    parser.add_argument(
        "--menu-inicio",
        action="store_true",
        help=(
            "crea también una copia en el menú Inicio; hace falta para poder "
            "anclarla a Inicio o a la barra de tareas"
        ),
    )
    argumentos = parser.parse_args(argv)

    if not cfg.RUTA_ICONO.exists():
        print(
            f"Falta el icono en {cfg.RUTA_ICONO}. "
            "Genéralo con: python -m app.recursos.generar_icono",
            file=sys.stderr,
        )
        return 1

    interprete = interprete_sin_consola()
    if _es_empaquetado(interprete):
        print(
            "Aviso: sólo se encontró el Python de Microsoft Store. Windows le "
            "impone el icono del paquete, así que en la barra de tareas se verá "
            "el de Python.",
            file=sys.stderr,
        )

    try:
        print(f"Intérprete: {interprete}")
        if prestados := paquetes_prestados(interprete):
            print(f"Paquetes prestados de: {prestados}")
        print(f"Creado {crear()}")
        for pedido, carpeta, donde in (
            (argumentos.escritorio, escritorio(), "el escritorio"),
            (argumentos.menu_inicio, menu_inicio(), "el menú Inicio"),
        ):
            if not pedido:
                continue
            if not carpeta.is_dir():
                print(f"No se encontró {donde} en {carpeta}.", file=sys.stderr)
                return 1
            print(f"Creado {crear(carpeta / NOMBRE)}")
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
