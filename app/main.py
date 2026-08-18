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
    parser.add_argument(
        "--rehacer",
        metavar="SESION",
        help=(
            "regenera la crónica de una sesión ya transcrita, sin volver a "
            "transcribir (usa 'lista' para ver las disponibles)"
        ),
    )
    argumentos = parser.parse_args(argv)

    if argumentos.rehacer:
        return _modo_rehacer(argumentos.rehacer)

    if argumentos.consola:
        return _modo_consola()

    from .gui import lanzar

    lanzar()
    return 0


def _modo_rehacer(sesion: str) -> int:
    """Regenera la crónica de una sesión ya transcrita.

    Útil tras afinar los prompts o el mapeo de personajes: evita repetir la
    transcripción, que es lo que tarda.
    """
    from . import config as cfg
    from .pipeline import orquestador

    disponibles = orquestador.sesiones_transcritas()

    if sesion == "lista" or sesion not in disponibles:
        if not disponibles:
            print("No hay ninguna sesión transcrita todavía.", file=sys.stderr)
            return 1
        if sesion != "lista":
            print(f"No se encontró la sesión '{sesion}'.", file=sys.stderr)
        print("Sesiones disponibles:")
        for etiqueta in disponibles:
            print(f"  {etiqueta}")
        return 0 if sesion == "lista" else 1

    resultado = orquestador.reprocesar(
        sesion, cfg.cargar(), avisar=lambda t: print(t, flush=True)
    )
    return 0 if resultado.ok else 1


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
