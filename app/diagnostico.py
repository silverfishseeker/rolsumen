"""Comprobación del estado de Craig, útil para depurar la puesta en marcha.

    python -m app.diagnostico

Revisa, por orden, todo lo que tiene que estar bien para que la aplicación
funcione, y dice exactamente qué falla si algo no está.
"""

from __future__ import annotations

import sys

from . import config as cfg
from . import craig_client, dependencias, docker_manager
from .pipeline import resumidor

OK = "[OK]"
MAL = "[--]"


def _linea(bien: bool, etiqueta: str, detalle: str = "") -> bool:
    print(f"{OK if bien else MAL} {etiqueta}" + (f": {detalle}" if detalle else ""))
    return bien


def _tabla_recording_existe() -> tuple[bool, str]:
    """Comprueba que las migraciones se aplicaron sobre la base de datos real.

    Craig ejecuta las migraciones durante la construcción de la imagen, cuando
    el servicio de base de datos todavía no existe, así que conviene verificar
    que la tabla está de verdad.
    """
    try:
        salida = craig_client._psql(
            "SELECT to_regclass('public.\"Recording\"') IS NOT NULL"
        )
        return "t" in salida.lower(), salida.strip()
    except craig_client.ErrorCraig as exc:
        return False, str(exc)


def main() -> int:
    print("=== Dependencias ===")
    for dependencia in dependencias.comprobar_todo():
        _linea(dependencia.disponible, dependencia.nombre, dependencia.ruta)

    print("\n=== Configuración ===")
    configuracion = cfg.cargar()
    _linea(cfg.RUTA_CONFIG.exists(), "config.ini", str(cfg.RUTA_CONFIG))
    faltan = configuracion.discord.faltantes()
    _linea(not faltan, "credenciales de Discord", ", ".join(faltan) or "completas")
    _linea(cfg.DIR_PROMPTS.exists(), "prompts", str(cfg.DIR_PROMPTS))

    print("\n=== Docker y Craig ===")
    diag = docker_manager.diagnostico()
    _linea(diag["docker_instalado"], "docker instalado")
    _linea(diag["docker_en_marcha"], "docker en marcha")
    _linea(diag["craig_instalado"], "craig descargado")
    _linea(diag["craig_configurado"], "install.config generado")

    servicios = docker_manager.servicios_con_estado()
    _linea(bool(servicios), "contenedores", f"{len(servicios)} en marcha")
    for servicio in servicios:
        print(f"     {servicio}")

    if diag["craig_levantado"]:
        existe, detalle = _tabla_recording_existe()
        _linea(existe, "tabla Recording en la base de datos", "" if existe else detalle)

        if existe:
            try:
                grabaciones = craig_client.grabaciones_terminadas()
                _linea(True, "grabaciones terminadas", str(len(grabaciones)))
                for grabacion in grabaciones[-5:]:
                    print(f"     {grabacion.id}  {grabacion.etiqueta_fecha}")
            except craig_client.ErrorCraig as exc:
                _linea(False, "consulta de grabaciones", str(exc))

    print("\n=== Ollama ===")
    disponible = resumidor.ollama_disponible()
    _linea(disponible, "servicio")
    if disponible:
        modelos = resumidor.modelos_disponibles()
        buscado = configuracion.modelos.resumen
        _linea(buscado in modelos, f"modelo {buscado}", ", ".join(modelos))

    return 0


if __name__ == "__main__":
    sys.exit(main())
