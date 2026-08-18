"""Instalador de Craig self-hosted.

Craig no forma parte de este repositorio (es un proyecto aparte y su
configuración contiene secretos), así que se descarga con este script:

    python -m app.instalar_craig

El script deja `app/craig/` listo y crea `install.config` con los ajustes
correctos para Docker. Después sólo hay que rellenar dos valores secretos.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

from .config import DIR_CRAIG

REPO_CRAIG = "https://github.com/CraigChat/craig.git"

# Docker Compose fusiona automáticamente este archivo con el de Craig, así que
# podemos corregir cosas sin tocar los archivos originales (y sin que los
# cambios se pierdan al actualizar Craig).
#
# El problema que resuelve: el docker-compose.yml de Craig pide `image: postgres`
# sin versión, que hoy resuelve a PostgreSQL 18. La 18 cambió dónde espera los
# datos (`/var/lib/postgresql` en vez de `/var/lib/postgresql/data`), así que el
# contenedor entra en bucle de reinicio. Fijando la 16 se respeta la convención
# que Craig da por supuesta.
COMPOSE_OVERRIDE = """\
# Generado por Rolsumen (python -m app.instalar_craig).
# Docker Compose lo fusiona con docker-compose.yml automáticamente.

services:
  db:
    # Craig monta el volumen en /var/lib/postgresql/data, la convención
    # anterior a PostgreSQL 18. Sin fijar la versión, `postgres` resuelve a
    # la 18+ y el contenedor no arranca.
    image: postgres:16
"""

NOMBRE_OVERRIDE = "docker-compose.override.yml"

# Craig deja la configuración de Redis vacía, lo que significa "conéctate a
# localhost". Dentro de un contenedor, localhost es el propio contenedor, no el
# servicio `redis` del compose, así que el bot no arranca y llena el log de
# ECONNREFUSED 127.0.0.1:6379.
REDIS_VACIO = "redis: {},"
REDIS_DOCKER = """redis: { host: 'redis', port: 6379, keyPrefix: 'craig:' },"""

# `install.sh` copia estos _default.js a default.js al configurar, así que
# parcheando el original basta para una instalación nueva.
CONFIGS_A_PARCHEAR = (
    "apps/bot/config/_default.js",
    "apps/tasks/config/_default.js",
)

# Identificador público de la aplicación de Discord del usuario.
APP_ID_POR_DEFECTO = "1539028879342047263"

# Ajustes que hay que cambiar respecto al ejemplo para que funcione en Docker.
# El ejemplo apunta a localhost, pero dentro de la red de Docker los servicios
# se llaman por el nombre que tienen en docker-compose.yml ('db' y 'redis').
AJUSTES_DOCKER = {
    "DATABASE_URL": (
        '\\"postgresql://$POSTGRESQL_USER:$POSTGRESQL_PASSWORD'
        '@db:5432/$DATABASE_NAME?schema=public\\"'
    ),
    "REDIS_HOST": "redis",
    "REDIS_PORT": "6379",
}


def clonar(destino: Path = DIR_CRAIG) -> bool:
    """Descarga Craig si no está ya. Devuelve True si ha clonado."""
    if (destino / "docker-compose.yml").exists():
        print(f"Craig ya está en {destino}")
        return False

    destino.parent.mkdir(parents=True, exist_ok=True)
    print(f"Descargando Craig en {destino}...")

    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", REPO_CRAIG, str(destino)],
            check=True,
        )
    except FileNotFoundError:
        print("ERROR: no se encontró 'git'. Instálalo y vuelve a intentarlo.")
        raise SystemExit(1) from None
    except subprocess.CalledProcessError as exc:
        print(f"ERROR: falló la descarga de Craig ({exc}).")
        raise SystemExit(1) from None

    # El .git del clon estorba dentro de nuestro repositorio.
    git_anidado = destino / ".git"
    if git_anidado.exists():
        import shutil

        shutil.rmtree(git_anidado, ignore_errors=True)

    return True


def _escribir_para_linux(ruta: Path, contenido: str) -> None:
    """Escribe un archivo con saltos de línea Unix.

    Estos archivos los consume el contenedor de Craig, que es Linux. Si Python
    los escribe con los saltos de Windows (CRLF), el shell del contenedor falla
    al interpretarlos con un error tan poco evidente como
    `line 4: $'\\r': command not found`.
    """
    ruta.parent.mkdir(parents=True, exist_ok=True)
    # `newline="\n"` sólo evita que Python traduzca los saltos al escribir; no
    # toca los CRLF que ya vinieran en el texto (por ejemplo, al releer un
    # archivo que se editó con el Bloc de notas). Hay que normalizarlos.
    normalizado = contenido.replace("\r\n", "\n").replace("\r", "\n")
    ruta.write_text(normalizado, encoding="utf-8", newline="\n")


def crear_override(destino: Path = DIR_CRAIG, forzar: bool = False) -> Path:
    """Escribe el docker-compose.override.yml con nuestras correcciones."""
    ruta = destino / NOMBRE_OVERRIDE
    if ruta.exists() and not forzar:
        return ruta
    _escribir_para_linux(ruta, COMPOSE_OVERRIDE)
    print(f"Creado {ruta}")
    return ruta


def apuntar_redis_a_docker(destino: Path = DIR_CRAIG) -> list[Path]:
    """Hace que el bot y las tareas busquen Redis en el servicio de Docker.

    Devuelve los archivos que ha modificado.
    """
    parcheados: list[Path] = []

    for relativo in CONFIGS_A_PARCHEAR:
        ruta = destino / relativo
        if not ruta.exists():
            continue

        contenido = ruta.read_text(encoding="utf-8")
        if REDIS_DOCKER in contenido:
            continue  # ya estaba parcheado
        if REDIS_VACIO not in contenido:
            continue  # Craig ha cambiado el formato: mejor no tocar nada

        _escribir_para_linux(ruta, contenido.replace(REDIS_VACIO, REDIS_DOCKER, 1))
        parcheados.append(ruta)

        # Si la configuración ya se había generado, actualizarla también.
        generado = ruta.parent / "default.js"
        if generado.exists():
            actual = generado.read_text(encoding="utf-8")
            if REDIS_VACIO in actual:
                _escribir_para_linux(
                    generado, actual.replace(REDIS_VACIO, REDIS_DOCKER, 1)
                )
                parcheados.append(generado)

    return parcheados


def _sustituir(contenido: str, clave: str, valor: str) -> str:
    """Cambia el valor de una clave del archivo de configuración."""
    patron = re.compile(rf"^{re.escape(clave)}=.*$", re.MULTILINE)
    if patron.search(contenido):
        return patron.sub(f"{clave}={valor}", contenido)
    return contenido.rstrip("\n") + f"\n{clave}={valor}\n"


def crear_config(
    destino: Path = DIR_CRAIG,
    app_id: str = APP_ID_POR_DEFECTO,
    forzar: bool = False,
) -> Path:
    """Crea install.config a partir del ejemplo, ajustado para Docker."""
    ejemplo = destino / "install.config.example"
    config = destino / "install.config"

    if not ejemplo.exists():
        print(f"ERROR: no se encontró {ejemplo}. ¿Se descargó Craig bien?")
        raise SystemExit(1)

    if config.exists() and not forzar:
        print(f"Ya existe {config} (no se toca).")
        return config

    contenido = ejemplo.read_text(encoding="utf-8")

    # Ajustes imprescindibles para que funcione dentro de Docker.
    for clave, valor in AJUSTES_DOCKER.items():
        contenido = _sustituir(contenido, clave, valor)

    # El identificador de la aplicación es público; los secretos no.
    if app_id:
        contenido = _sustituir(contenido, "DISCORD_APP_ID", app_id)
        contenido = _sustituir(contenido, "CLIENT_ID", app_id)

    _escribir_para_linux(config, contenido)
    print(f"Creado {config}")
    return config


def sincronizar_credenciales(
    credenciales, destino: Path = DIR_CRAIG
) -> tuple[bool, str]:
    """Vuelca las credenciales de nuestro config.ini en el de Craig.

    Así el usuario sólo tiene un archivo de configuración que tocar
    (`app/config.ini`); el `install.config` de Craig pasa a ser un detalle
    interno que se genera solo.

    Devuelve (ok, mensaje).
    """
    faltan = credenciales.faltantes()
    if faltan:
        return False, (
            "Faltan credenciales de Discord en app/config.ini, sección "
            f"[discord]: {', '.join(faltan)}."
        )

    ejemplo = destino / "install.config.example"
    config = destino / "install.config"

    if config.exists():
        contenido = config.read_text(encoding="utf-8")
    elif ejemplo.exists():
        contenido = ejemplo.read_text(encoding="utf-8")
        for clave, valor in AJUSTES_DOCKER.items():
            contenido = _sustituir(contenido, clave, valor)
    else:
        return False, (
            f"No se encontró la configuración de Craig en {destino}. "
            "Ejecuta: python -m app.instalar_craig"
        )

    contenido = _sustituir(contenido, "DISCORD_BOT_TOKEN", credenciales.token_bot)
    contenido = _sustituir(contenido, "CLIENT_SECRET", credenciales.secreto_cliente)
    contenido = _sustituir(contenido, "DISCORD_APP_ID", credenciales.id_aplicacion)
    contenido = _sustituir(contenido, "CLIENT_ID", credenciales.id_aplicacion)

    try:
        _escribir_para_linux(config, contenido)
    except OSError as exc:
        return False, f"No se pudo escribir {config}: {exc}"

    return True, "Credenciales de Discord sincronizadas."


def valores_pendientes(config: Path) -> list[str]:
    """Claves obligatorias que siguen vacías."""
    if not config.exists():
        return ["DISCORD_BOT_TOKEN", "DISCORD_APP_ID", "CLIENT_ID", "CLIENT_SECRET"]

    contenido = config.read_text(encoding="utf-8")
    pendientes = []
    for clave in ("DISCORD_BOT_TOKEN", "DISCORD_APP_ID", "CLIENT_ID", "CLIENT_SECRET"):
        coincidencia = re.search(rf"^{clave}=(.*)$", contenido, re.MULTILINE)
        if coincidencia is None or not coincidencia.group(1).strip():
            pendientes.append(clave)
    return pendientes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="instalar_craig", description="Descarga y prepara Craig self-hosted."
    )
    parser.add_argument(
        "--app-id",
        default=APP_ID_POR_DEFECTO,
        help="identificador de la aplicación de Discord",
    )
    parser.add_argument(
        "--rehacer-config",
        action="store_true",
        help="sobrescribe install.config aunque ya exista",
    )
    argumentos = parser.parse_args(argv)

    clonar()
    crear_override(forzar=argumentos.rehacer_config)

    parcheados = apuntar_redis_a_docker()
    for ruta in parcheados:
        print(f"Ajustado Redis en {ruta.relative_to(DIR_CRAIG)}")

    config = crear_config(app_id=argumentos.app_id, forzar=argumentos.rehacer_config)

    pendientes = valores_pendientes(config)
    if pendientes:
        print("\n" + "=" * 62)
        print("FALTA RELLENAR (a mano, en install.config):")
        for clave in pendientes:
            print(f"  - {clave}")
        print(f"\nArchivo: {config}")
        print("Los valores se sacan del portal de desarrolladores de Discord.")
        print("=" * 62)
        return 1

    print("\nCraig está listo. Abre la aplicación para levantarlo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
