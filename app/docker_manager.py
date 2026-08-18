"""Control del ciclo de vida de Craig (self-hosted) mediante Docker Compose.

La aplicación levanta Craig al abrirse y lo baja al cerrarse, para no tenerlo
corriendo permanentemente. `docker compose up` es idempotente, así que si la
aplicación se cerró mal y los contenedores siguen en pie, volver a levantarlos
no rompe nada.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import DIR_CRAIG

TIMEOUT_COMANDO = 300


@dataclass
class ResultadoComando:
    """Salida de un comando de Docker."""

    ok: bool
    salida: str
    error: str

    @property
    def mensaje(self) -> str:
        return (self.error or self.salida).strip()


class ErrorDocker(RuntimeError):
    """Fallo al operar con Docker."""


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
        return ResultadoComando(
            ok=proceso.returncode == 0,
            salida=proceso.stdout or "",
            error=proceso.stderr or "",
        )
    except FileNotFoundError:
        return ResultadoComando(
            ok=False,
            salida="",
            error="No se encontró el comando 'docker'. ¿Está Docker instalado?",
        )
    except subprocess.TimeoutExpired:
        return ResultadoComando(
            ok=False, salida="", error="El comando de Docker tardó demasiado."
        )
    except OSError as exc:
        return ResultadoComando(ok=False, salida="", error=str(exc))


def docker_instalado() -> bool:
    """¿Está el ejecutable de Docker disponible?"""
    return _ejecutar(["docker", "--version"]).ok


def docker_en_marcha() -> bool:
    """¿Está el demonio de Docker aceptando comandos?

    En Windows esto equivale a comprobar si Docker Desktop está abierto.
    """
    return _ejecutar(["docker", "info"]).ok


def hay_compose(dir_craig: Path = DIR_CRAIG) -> bool:
    """¿Está el docker-compose.yml de Craig en su sitio?"""
    return (dir_craig / "docker-compose.yml").exists()


def hay_configuracion(dir_craig: Path = DIR_CRAIG) -> bool:
    """¿Existe el install.config con los tokens de Discord?"""
    return (dir_craig / "install.config").exists()


def servicios_activos(dir_craig: Path = DIR_CRAIG) -> list[str]:
    """Nombres de los servicios de Craig que están corriendo."""
    resultado = _ejecutar(
        ["docker", "compose", "ps", "--services", "--filter", "status=running"],
        cwd=dir_craig,
    )
    if not resultado.ok:
        return []
    return [linea.strip() for linea in resultado.salida.splitlines() if linea.strip()]


def esta_levantado(dir_craig: Path = DIR_CRAIG) -> bool:
    """¿Está Craig en marcha?"""
    return bool(servicios_activos(dir_craig))


def levantar(
    dir_craig: Path = DIR_CRAIG, credenciales=None
) -> ResultadoComando:
    """Levanta Craig en segundo plano (`docker compose up -d`).

    Antes de arrancar vuelca las credenciales de Discord de nuestro config.ini
    en la configuración interna de Craig, para que el usuario sólo tenga que
    mantener un archivo.
    """
    if not hay_compose(dir_craig):
        return ResultadoComando(
            ok=False,
            salida="",
            error=(
                f"No se encontró Craig en {dir_craig}. "
                "Instálalo con: python -m app.instalar_craig"
            ),
        )

    if credenciales is not None:
        from .instalar_craig import sincronizar_credenciales

        ok, mensaje = sincronizar_credenciales(credenciales, dir_craig)
        if not ok:
            return ResultadoComando(ok=False, salida="", error=mensaje)

    if not hay_configuracion(dir_craig):
        return ResultadoComando(
            ok=False,
            salida="",
            error=(
                "Faltan las credenciales de Discord. Rellena la sección "
                "[discord] de app/config.ini."
            ),
        )

    return _ejecutar(["docker", "compose", "up", "-d"], cwd=dir_craig)


def bajar(dir_craig: Path = DIR_CRAIG) -> ResultadoComando:
    """Para y elimina los contenedores (`docker compose down`).

    No borra los volúmenes: la base de datos y las grabaciones sobreviven.
    """
    if not hay_compose(dir_craig):
        return ResultadoComando(ok=True, salida="Craig no está instalado.", error="")
    return _ejecutar(["docker", "compose", "down"], cwd=dir_craig)


def diagnostico(dir_craig: Path = DIR_CRAIG) -> dict[str, bool]:
    """Estado de cada requisito, para pintarlo en la interfaz."""
    return {
        "docker_instalado": docker_instalado(),
        "docker_en_marcha": docker_en_marcha(),
        "craig_instalado": hay_compose(dir_craig),
        "craig_configurado": hay_configuracion(dir_craig),
        "craig_levantado": esta_levantado(dir_craig),
    }
