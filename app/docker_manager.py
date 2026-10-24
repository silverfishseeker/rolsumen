"""Ciclo de vida de Craig mediante Docker Compose.

La aplicación lo levanta al abrirse y lo baja al cerrarse, para no tenerlo
corriendo permanentemente. `docker compose up` es idempotente, así que si la
aplicación se cerró mal y los contenedores siguen en pie, no rompe nada.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .config import DIR_CRAIG
from .procesos import SIN_CONSOLA

TIMEOUT_COMANDO = 300

# El contenedor que de verdad graba. Los otros dos le hacen falta, pero que
# ellos esten en pie no significa que se pueda grabar.
SERVICIO_CRAIG = "craig"

# Con cualquiera de estos abierto, Docker Desktop esta al menos intentandolo.
PROCESOS_DOCKER = ("Docker Desktop.exe", "com.docker.backend.exe", "dockerd.exe")


@dataclass
class ResultadoComando:
    ok: bool
    salida: str
    error: str

    @property
    def mensaje(self) -> str:
        return (self.error or self.salida).strip()


def _ejecutar(argumentos: list[str], cwd: Path | None = None) -> ResultadoComando:
    """Ejecuta un comando y captura su salida sin lanzar excepción."""
    try:
        proceso = subprocess.run(
            argumentos,
            cwd=str(cwd) if cwd else None,
            **SIN_CONSOLA,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_COMANDO,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        return ResultadoComando(
            False, "", "No se encontró el comando 'docker'. ¿Está Docker instalado?"
        )
    except subprocess.TimeoutExpired:
        return ResultadoComando(False, "", "El comando de Docker tardó demasiado.")
    except OSError as exc:
        return ResultadoComando(False, "", str(exc))

    return ResultadoComando(
        proceso.returncode == 0, proceso.stdout or "", proceso.stderr or ""
    )


def docker_instalado() -> bool:
    return _ejecutar(["docker", "--version"]).ok


def docker_en_marcha() -> bool:
    """Si el motor responde. En Windows, que Docker Desktop terminó de abrirse."""
    return _ejecutar(["docker", "info"]).ok


def docker_abriendose() -> bool:
    """Docker Desktop está abierto pero su motor todavía no responde.

    `docker info` falla exactamente igual con Docker cerrado que con Docker a
    medio arrancar, y entre esas dos cosas hay casi un minuto de diferencia y
    un consejo distinto que dar: en un caso hay que abrir Docker Desktop, en
    el otro hay que esperar y no tocar nada. Mirar si el proceso existe es la
    forma barata de distinguirlas.

    Se usa sólo cuando `docker_en_marcha()` ya ha dicho que no.
    """
    if sys.platform != "win32":  # pragma: no cover - el usuario va en Windows
        return False
    for imagen in PROCESOS_DOCKER:
        resultado = _ejecutar(["tasklist", "/FI", f"IMAGENAME eq {imagen}", "/NH"])
        # Sin coincidencias, `tasklist` imprime un aviso en el idioma del
        # sistema en vez de una tabla vacía; buscar el nombre evita depender
        # de cómo esté traducido ese aviso.
        if resultado.ok and imagen.lower() in resultado.salida.lower():
            return True
    return False


def hay_compose(dir_craig: Path = DIR_CRAIG) -> bool:
    return (dir_craig / "docker-compose.yml").exists()


def hay_configuracion(dir_craig: Path = DIR_CRAIG) -> bool:
    return (dir_craig / "install.config").exists()


def servicios_activos(dir_craig: Path = DIR_CRAIG) -> list[str]:
    resultado = _ejecutar(
        ["docker", "compose", "ps", "--services", "--filter", "status=running"],
        cwd=dir_craig,
    )
    return (
        [l.strip() for l in resultado.salida.splitlines() if l.strip()]
        if resultado.ok
        else []
    )


def servicios_con_estado(dir_craig: Path = DIR_CRAIG) -> list[str]:
    """Como `servicios_activos` pero incluyendo los caídos y su estado."""
    resultado = _ejecutar(
        ["docker", "compose", "ps", "--format", "{{.Service}}\t{{.State}}"],
        cwd=dir_craig,
    )
    return [l.strip() for l in resultado.salida.splitlines() if l.strip()]


def esta_levantado(dir_craig: Path = DIR_CRAIG) -> bool:
    """Si hay **algo** de Craig en pie. Para saber si se puede grabar, no sirve."""
    return bool(servicios_activos(dir_craig))


def craig_en_marcha(dir_craig: Path = DIR_CRAIG) -> bool:
    """Si corre el contenedor que graba.

    Es la pregunta que importa y no es la misma que `esta_levantado()`: `db` y
    `redis` pueden estar perfectamente en pie con el contenedor de Craig
    muerto, y entonces no se graba nada aunque «haya servicios activos».
    """
    return SERVICIO_CRAIG in servicios_activos(dir_craig)


def levantar(dir_craig: Path = DIR_CRAIG, credenciales=None) -> ResultadoComando:
    """Levanta Craig, volcando antes las credenciales de config.ini."""
    if not hay_compose(dir_craig):
        return ResultadoComando(
            False,
            "",
            f"No se encontró Craig en {dir_craig}. "
            "Instálalo con: python -m app.instalar_craig",
        )

    if credenciales is not None:
        from .instalar_craig import sincronizar_credenciales

        ok, mensaje = sincronizar_credenciales(credenciales, dir_craig)
        if not ok:
            return ResultadoComando(False, "", mensaje)

    if not hay_configuracion(dir_craig):
        return ResultadoComando(
            False,
            "",
            "Faltan las credenciales de Discord. Rellena la sección "
            "[discord] de config.ini.",
        )

    return _ejecutar(["docker", "compose", "up", "-d"], cwd=dir_craig)


def bajar(dir_craig: Path = DIR_CRAIG) -> ResultadoComando:
    """Detiene Craig conservando los contenedores.

    Es `stop`, no `down`, y la diferencia son quince minutos en cada arranque:
    Craig hace su instalación completa (yarn, prisma, compilar los binarios del
    `cook`) al arrancar el contenedor, y deja el marcador `/app/.installed` en
    su capa de escritura. `down` borra el contenedor y con él el marcador, así
    que la instalación entera se repite en el siguiente `up`.

    Detenidos siguen sin consumir nada, y con `restart: "no"` tampoco vuelven
    solos al arrancar Docker Desktop.
    """
    if not hay_compose(dir_craig):
        return ResultadoComando(True, "Craig no está instalado.", "")
    return _ejecutar(["docker", "compose", "stop"], cwd=dir_craig)


def diagnostico(dir_craig: Path = DIR_CRAIG) -> dict[str, bool]:
    """Todo lo que la pestaña Estado necesita saber, en una sola pasada."""
    en_marcha = docker_en_marcha()
    # Preguntar por los contenedores con el motor caído sólo sirve para
    # esperar a que cada comando agote su plazo.
    activos = servicios_activos(dir_craig) if en_marcha else []
    return {
        "docker_instalado": docker_instalado(),
        "docker_en_marcha": en_marcha,
        "docker_abriendose": False if en_marcha else docker_abriendose(),
        "craig_instalado": hay_compose(dir_craig),
        "craig_configurado": hay_configuracion(dir_craig),
        "craig_levantado": bool(activos),
        "craig_en_marcha": SERVICIO_CRAIG in activos,
        "servicios_activos": activos,
    }
