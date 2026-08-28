"""Punto de entrada de Rolsumen.

    python -m app.main                  abre la ventana
    python -m app.main --consola        procesa lo pendiente sin GUI
    python -m app.main --rehacer lista  regenera una crónica ya transcrita
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rolsumen",
        description="Crónicas automáticas de sesiones grabadas en Discord.",
    )
    parser.add_argument(
        "--consola",
        action="store_true",
        help="procesa las grabaciones pendientes sin abrir la ventana",
    )
    parser.add_argument(
        "--paquetes",
        metavar="RUTA",
        help=(
            "carpeta de paquetes adicional. La usa el acceso directo para "
            "prestarle las dependencias a un intérprete que no las tenga"
        ),
    )
    parser.add_argument(
        "--rehacer",
        metavar="SESION",
        help=(
            "regenera la crónica de una sesión ya transcrita, sin volver a "
            "transcribir ('lista' muestra las disponibles)"
        ),
    )
    argumentos = parser.parse_args(argv)

    # Antes de importar nada que dependa de ellos.
    if argumentos.paquetes:
        _prestar_paquetes(argumentos.paquetes)

    if argumentos.rehacer:
        return _modo_rehacer(argumentos.rehacer)
    if argumentos.consola:
        return _modo_consola()

    from .gui import lanzar

    lanzar()
    return 0


def _prestar_paquetes(ruta: str) -> None:
    """Añade una carpeta de paquetes al principio de la búsqueda.

    El acceso directo apunta a un Python no empaquetado —el de Microsoft Store
    arrastra una identidad que estropea el icono de la barra de tareas— y ese
    intérprete puede no tener instaladas las dependencias. En vez de duplicar
    varios gigas, se le presta la carpeta del que sí las tiene.
    """
    carpeta = Path(ruta)
    if carpeta.is_dir() and str(carpeta) not in sys.path:
        sys.path.insert(0, str(carpeta))


def _avisar(texto: str) -> None:
    print(texto, flush=True)


def _modo_rehacer(sesion: str) -> int:
    """Regenera una crónica desde las transcripciones guardadas.

    Evita repetir la transcripción, que es lo que tarda, así que es la forma
    práctica de afinar los prompts o el mapeo de personajes.
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

    return 0 if orquestador.reprocesar(sesion, cfg.cargar(), _avisar).ok else 1


def _modo_consola() -> int:
    """Como la ventana pero por pantalla: mismas comprobaciones, sin GUI."""
    from . import config as cfg
    from . import dependencias, docker_manager
    from .pipeline import orquestador, resumidor

    cfg.crear_config_si_falta()
    cfg.asegurar_carpetas()
    dependencias.preparar_entorno()

    for dependencia in dependencias.comprobar_todo():
        if not dependencia.disponible:
            print(f"Aviso ({dependencia.nombre}): {dependencia.ayuda}", file=sys.stderr)

    configuracion = cfg.cargar()

    if faltan := configuracion.discord.faltantes():
        print(
            f"Faltan credenciales de Discord en {cfg.RUTA_CONFIG}, sección "
            f"[discord]: {', '.join(faltan)}",
            file=sys.stderr,
        )
        return 1

    if not docker_manager.docker_en_marcha():
        print("Docker no responde. Abre Docker Desktop.", file=sys.stderr)
        return 1

    if not docker_manager.esta_levantado():
        _avisar("Levantando Craig...")
        resultado = docker_manager.levantar(credenciales=configuracion.discord)
        if not resultado.ok:
            print(f"No se pudo levantar Craig: {resultado.mensaje}", file=sys.stderr)
            return 1

    if not resumidor.ollama_disponible():
        print("Ollama no responde. Arráncalo antes de continuar.", file=sys.stderr)
        return 1

    fallidos = [
        r
        for r in orquestador.procesar_pendientes(configuracion, avisar=_avisar)
        if not r.ok
    ]
    for resultado in fallidos:
        print(f"FALLÓ {resultado.id_grabacion}: {resultado.error}", file=sys.stderr)

    return 1 if fallidos else 0


if __name__ == "__main__":
    raise SystemExit(main())
