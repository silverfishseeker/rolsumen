"""Instalador de Craig self-hosted.

Craig es un proyecto aparte y no forma parte de este repositorio, así que se
descarga con:

    python -m app.instalar_craig

Además de clonarlo, aquí se corrigen tres cosas que impiden que arranque en
Docker; cada una está explicada junto a la constante correspondiente. Las
credenciales no se tocan a mano: salen de `config.ini`.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

from . import config as cfg
from .config import DIR_CRAIG

REPO_CRAIG = "https://github.com/CraigChat/craig.git"

NOMBRE_OVERRIDE = "docker-compose.override.yml"

# Docker Compose fusiona este archivo con el de Craig automáticamente, así que
# la corrección sobrevive a una actualización suya sin tocar sus archivos.
COMPOSE_OVERRIDE = """\
# Generado por Rolsumen (python -m app.instalar_craig).
# Docker Compose lo fusiona con docker-compose.yml automáticamente.

services:
  db:
    # Craig monta el volumen en /var/lib/postgresql/data, la convención
    # anterior a PostgreSQL 18. Sin fijar la versión, `postgres` resuelve a
    # la 18+ y el contenedor entra en bucle de reinicio.
    image: postgres:16
    # Craig trae `restart: always` en db y redis. Esa política devuelve los
    # contenedores a la vida al arrancar Docker Desktop, aunque Rolsumen no se
    # haya abierto. Craig solo debe estar en marcha mientras la ventana lo está.
    restart: "no"
  redis:
    restart: "no"
  craig:
    restart: "no"
    depends_on:
      db:
        condition: service_healthy
        # Sin esto, cualquier reinicio de la base de datos arrastra al bot.
        restart: false
      redis:
        condition: service_started
"""

# Craig deja la configuración de Redis vacía, que significa "localhost". Dentro
# de un contenedor eso es el propio contenedor y no el servicio `redis`, así que
# el bot no arranca y llena el log de ECONNREFUSED 127.0.0.1:6379.
REDIS_VACIO = "redis: {},"
REDIS_DOCKER = """redis: { host: 'redis', port: 6379, keyPrefix: 'craig:' },"""

# `install.sh` copia estos _default.js a default.js, así que parchear el
# original basta para una instalación nueva.
CONFIGS_A_PARCHEAR = (
    "apps/bot/config/_default.js",
    "apps/tasks/config/_default.js",
)

# El ejemplo de Craig apunta a localhost, pero dentro de la red de Docker los
# servicios se llaman por su nombre en docker-compose.yml.
AJUSTES_DOCKER = {
    "DATABASE_URL": (
        '\\"postgresql://$POSTGRESQL_USER:$POSTGRESQL_PASSWORD'
        "@db:5432/$DATABASE_NAME?schema=public\\\""
    ),
    "REDIS_HOST": "redis",
    "REDIS_PORT": "6379",
}

CLAVES_CREDENCIALES = (
    "DISCORD_BOT_TOKEN",
    "DISCORD_APP_ID",
    "CLIENT_ID",
    "CLIENT_SECRET",
)


def _escribir_para_linux(ruta: Path, contenido: str) -> None:
    """Escribe con saltos de línea Unix.

    Estos archivos los lee el contenedor, que es Linux. Con los saltos de
    Windows su shell falla con `line 4: $'\\r': command not found`, que no
    menciona los saltos por ninguna parte. `newline="\\n"` no basta: no
    convierte los CRLF que ya vengan dentro del texto.
    """
    ruta.parent.mkdir(parents=True, exist_ok=True)
    normalizado = contenido.replace("\r\n", "\n").replace("\r", "\n")
    ruta.write_text(normalizado, encoding="utf-8", newline="\n")


def _sustituir(contenido: str, clave: str, valor: str) -> str:
    patron = re.compile(rf"^{re.escape(clave)}=.*$", re.MULTILINE)
    if patron.search(contenido):
        return patron.sub(f"{clave}={valor}", contenido)
    return contenido.rstrip("\n") + f"\n{clave}={valor}\n"


def clonar(destino: Path = DIR_CRAIG) -> bool:
    """Descarga Craig si no está ya. Devuelve True si ha clonado."""
    if (destino / "docker-compose.yml").exists():
        print(f"Craig ya está en {destino}")
        return False

    destino.parent.mkdir(parents=True, exist_ok=True)
    print(f"Descargando Craig en {destino}...")

    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", REPO_CRAIG, str(destino)], check=True
        )
    except FileNotFoundError:
        print("ERROR: no se encontró 'git'. Instálalo y vuelve a intentarlo.")
        raise SystemExit(1) from None
    except subprocess.CalledProcessError as exc:
        print(f"ERROR: falló la descarga de Craig ({exc}).")
        raise SystemExit(1) from None

    # El .git del clon estorba dentro de nuestro repositorio.
    shutil.rmtree(destino / ".git", ignore_errors=True)
    return True


def crear_override(destino: Path = DIR_CRAIG, forzar: bool = False) -> Path:
    ruta = destino / NOMBRE_OVERRIDE
    if not ruta.exists() or forzar:
        _escribir_para_linux(ruta, COMPOSE_OVERRIDE)
        print(f"Creado {ruta}")
    return ruta


def apuntar_redis_a_docker(destino: Path = DIR_CRAIG) -> list[Path]:
    """Hace que el bot y las tareas busquen Redis en el servicio de Docker."""
    parcheados: list[Path] = []

    for relativo in CONFIGS_A_PARCHEAR:
        original = destino / relativo
        if not original.exists():
            continue

        # El generado sólo existe si Craig ya se configuró alguna vez.
        for ruta in (original, original.parent / "default.js"):
            if not ruta.exists():
                continue
            contenido = ruta.read_text(encoding="utf-8")
            if REDIS_VACIO in contenido:
                _escribir_para_linux(
                    ruta, contenido.replace(REDIS_VACIO, REDIS_DOCKER, 1)
                )
                parcheados.append(ruta)

    return parcheados


def crear_config(
    destino: Path = DIR_CRAIG, app_id: str = "", forzar: bool = False
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
    for clave, valor in AJUSTES_DOCKER.items():
        contenido = _sustituir(contenido, clave, valor)

    # El identificador de la aplicación es público; los secretos nunca.
    if app_id:
        contenido = _sustituir(contenido, "DISCORD_APP_ID", app_id)
        contenido = _sustituir(contenido, "CLIENT_ID", app_id)

    _escribir_para_linux(config, contenido)
    print(f"Creado {config}")
    return config


def sincronizar_credenciales(
    credenciales, destino: Path = DIR_CRAIG
) -> tuple[bool, str]:
    """Vuelca las credenciales de config.ini en la configuración de Craig.

    Así el usuario mantiene un único archivo y el `install.config` pasa a ser un
    detalle interno que se genera solo. Devuelve (ok, mensaje).
    """
    if faltan := credenciales.faltantes():
        return False, (
            f"Faltan credenciales de Discord en {cfg.RUTA_CONFIG.name}, sección "
            f"[discord]: {', '.join(faltan)}."
        )

    config = destino / "install.config"
    if config.exists():
        contenido = config.read_text(encoding="utf-8")
    elif (destino / "install.config.example").exists():
        contenido = (destino / "install.config.example").read_text(encoding="utf-8")
        for clave, valor in AJUSTES_DOCKER.items():
            contenido = _sustituir(contenido, clave, valor)
    else:
        return False, (
            f"No se encontró la configuración de Craig en {destino}. "
            "Ejecuta: python -m app.instalar_craig"
        )

    for clave, valor in (
        ("DISCORD_BOT_TOKEN", credenciales.token_bot),
        ("CLIENT_SECRET", credenciales.secreto_cliente),
        ("DISCORD_APP_ID", credenciales.id_aplicacion),
        ("CLIENT_ID", credenciales.id_aplicacion),
    ):
        contenido = _sustituir(contenido, clave, valor)

    try:
        _escribir_para_linux(config, contenido)
    except OSError as exc:
        return False, f"No se pudo escribir {config}: {exc}"

    return True, "Credenciales de Discord sincronizadas."


def valores_pendientes(config: Path) -> list[str]:
    """Claves obligatorias que siguen vacías en el install.config de Craig."""
    if not config.exists():
        return list(CLAVES_CREDENCIALES)

    contenido = config.read_text(encoding="utf-8")
    return [
        clave
        for clave in CLAVES_CREDENCIALES
        if not (m := re.search(rf"^{clave}=(.*)$", contenido, re.MULTILINE))
        or not m.group(1).strip()
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="instalar_craig", description="Descarga y prepara Craig self-hosted."
    )
    parser.add_argument(
        "--rehacer-config",
        action="store_true",
        help="regenera install.config aunque ya exista",
    )
    argumentos = parser.parse_args(argv)

    clonar()
    crear_override(forzar=argumentos.rehacer_config)

    for ruta in apuntar_redis_a_docker():
        print(f"Ajustado Redis en {ruta.relative_to(DIR_CRAIG)}")

    config = crear_config(forzar=argumentos.rehacer_config)

    cfg.crear_config_si_falta()
    ok, mensaje = sincronizar_credenciales(cfg.cargar().discord)
    print(mensaje)

    if not ok:
        print(f"\nRellénalas en {cfg.RUTA_CONFIG} y vuelve a ejecutar este comando.")
        print("Los valores salen del portal de desarrolladores de Discord.")
        return 1

    print(f"\nCraig está listo ({config.name} generado). Abre la aplicación.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
