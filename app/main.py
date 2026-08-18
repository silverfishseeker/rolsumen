"""Punto de entrada de Rolsumen.

Uso:
    python -m app.main          abre la ventana
    python -m app.main --consola procesa las grabaciones pendientes sin GUI
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rolsumen",
        description="Crónicas automáticas de sesiones de rol grabadas en Discord.",
    )
    parser.add_argument(
        "--consola",
        action="store_true",
        help="procesa las grabaciones pendientes sin abrir la ventana",
    )
    argumentos = parser.parse_args(argv)

    if argumentos.consola:
        return _modo_consola()

    from .gui import lanzar

    lanzar()
    return 0


def _modo_consola() -> int:
    """Procesa lo pendiente escribiendo el progreso por pantalla.

    Hace las mismas comprobaciones que la ventana (dependencias, credenciales,
    Craig) para poder depurar sin la GUI de por medio.
    """
    from . import config as cfg
    from . import dependencias, docker_manager
    from .pipeline import orquestador, resumidor

    def avisar(texto: str) -> None:
        print(texto, flush=True)

    cfg.crear_config_si_falta()
    cfg.asegurar_carpetas()
    dependencias.preparar_entorno()

    for dependencia in dependencias.comprobar_todo():
        if not dependencia.disponible:
            print(f"Aviso ({dependencia.nombre}): {dependencia.ayuda}", file=sys.stderr)

    configuracion = cfg.cargar()

    faltan = configuracion.discord.faltantes()
    if faltan:
        print(
            "Faltan credenciales de Discord en app/config.ini, sección "
            f"[discord]: {', '.join(faltan)}",
            file=sys.stderr,
        )
        return 1

    if not docker_manager.docker_en_marcha():
        print("Docker no responde. Abre Docker Desktop.", file=sys.stderr)
        return 1

    if not docker_manager.esta_levantado():
        avisar("Levantando Craig...")
        resultado = docker_manager.levantar(credenciales=configuracion.discord)
        if not resultado.ok:
            print(f"No se pudo levantar Craig: {resultado.mensaje}", file=sys.stderr)
            return 1

    if not resumidor.ollama_disponible():
        print("Ollama no responde. Arráncalo antes de continuar.", file=sys.stderr)
        return 1

    resultados = orquestador.procesar_pendientes(configuracion, avisar=avisar)

    fallidos = [r for r in resultados if not r.ok]
    for resultado in fallidos:
        print(f"FALLÓ {resultado.id_grabacion}: {resultado.error}", file=sys.stderr)

    return 1 if fallidos else 0


if __name__ == "__main__":
    raise SystemExit(main())
