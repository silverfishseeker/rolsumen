"""Ciclo de vida de Craig mediante Docker Compose.

La aplicación lo levanta al abrirse y lo baja al cerrarse, para no tenerlo
corriendo permanentemente. `docker compose up` es idempotente, así que si la
aplicación se cerró mal y los contenedores siguen en pie, no rompe nada.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import DIR_CRAIG

TIMEOUT_COMANDO = 300


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
    """En Windows equivale a comprobar si Docker Desktop está abierto."""
    return _ejecutar(["docker", "info"]).ok


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
    return bool(servicios_activos(dir_craig))


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
    return {
        "docker_instalado": docker_instalado(),
        "docker_en_marcha": docker_en_marcha(),
        "craig_instalado": hay_compose(dir_craig),
        "craig_configurado": hay_configuracion(dir_craig),
        "craig_levantado": esta_levantado(dir_craig),
    }
