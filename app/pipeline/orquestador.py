"""Encadenado completo: de la grabación de Craig al documento de crónica."""

from __future__ import annotations

import shutil
import tempfile
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from .. import config as cfg
from .. import craig_client
from ..craig_client import ErrorCraig, Grabacion
from . import combinador, resumidor, troceador
from .registro import Registro
from .transcriptor import ErrorTranscripcion, Transcriptor, guardar_transcripcion

Avisar = Callable[[str], None]


@dataclass
class ResultadoProceso:
    """Qué ha pasado al procesar una grabación."""

    id_grabacion: str
    ok: bool
    resumen: Path | None = None
    error: str = ""


def _no_avisar(_: str) -> None:
    """Callback por defecto: no hacer nada."""


def _formatear_duracion(segundos: float) -> str:
    total = int(segundos)
    horas, resto = divmod(total, 3600)
    minutos, _ = divmod(resto, 60)
    if horas:
        return f"{horas} h {minutos} min"
    return f"{minutos} min"


def _guardar_resumen(
    documento: str, nombre: str, destinos: list[Path], avisar: Avisar
) -> Path:
    """Escribe el documento en todas las carpetas de destino.

    Devuelve la ruta principal (la primera). Un fallo al copiar en la carpeta
    adicional del usuario no debe tirar todo el proceso: el resumen ya está a
    salvo en la carpeta interna.
    """
    principal: Path | None = None

    for destino in destinos:
        try:
            destino.mkdir(parents=True, exist_ok=True)
            ruta = destino / nombre
            ruta.write_text(documento, encoding="utf-8")
            if principal is None:
                principal = ruta
        except OSError as exc:
            avisar(f"Aviso: no se pudo escribir en {destino} ({exc})")

    if principal is None:
        raise OSError("No se pudo guardar el resumen en ninguna carpeta.")

    return principal


def procesar_grabacion(
    grabacion: Grabacion,
    configuracion: cfg.Config,
    transcriptor: Transcriptor | None = None,
    avisar: Avisar = _no_avisar,
) -> ResultadoProceso:
    """Procesa una grabación de principio a fin."""
    etiqueta = f"{grabacion.etiqueta_fecha}_{grabacion.id}"
    avisar(f"Procesando grabación {grabacion.id}...")

    try:
        # 1. Cocinar: convertir el crudo de Craig en pistas FLAC por jugador.
        avisar("Extrayendo el audio de Craig (esto puede tardar)...")
        zip_destino = cfg.DIR_GRABACIONES / f"{etiqueta}.zip"
        craig_client.cocinar(grabacion.id, zip_destino)

        # 2. Descomprimir en una carpeta temporal.
        with tempfile.TemporaryDirectory(prefix="rolsumen_") as tmp:
            pistas = craig_client.extraer_pistas(zip_destino, Path(tmp))
            if not pistas:
                raise ErrorCraig("La grabación no contiene ninguna pista de audio.")

            avisar(f"{len(pistas)} pista(s) de audio encontradas.")

            # 3. Transcribir cada pista.
            transcriptor = transcriptor or Transcriptor(
                modelo=configuracion.modelo_whisper, idioma=configuracion.idioma
            )
            pistas_transcritas = []
            for numero, pista in enumerate(pistas, start=1):
                avisar(f"Transcribiendo pista {numero} de {len(pistas)}...")
                segmentos = transcriptor.transcribir(pista, avisar=avisar)
                pistas_transcritas.append(segmentos)

                guardar_transcripcion(
                    segmentos,
                    cfg.DIR_TRANSCRIPCIONES / etiqueta / f"{pista.stem}.json",
                )

        # 4. Combinar en una única línea de tiempo.
        avisar("Combinando las pistas en una línea de tiempo...")
        linea = combinador.combinar(
            pistas_transcritas, mapa_personajes=configuracion.jugadores
        )
        if not linea:
            raise ErrorTranscripcion(
                "No se transcribió nada. ¿La grabación tiene voz audible?"
            )

        (cfg.DIR_TRANSCRIPCIONES / etiqueta).mkdir(parents=True, exist_ok=True)
        (cfg.DIR_TRANSCRIPCIONES / etiqueta / "linea_de_tiempo.txt").write_text(
            combinador.a_texto(linea), encoding="utf-8"
        )

        # 5. Trocear para que quepa en el modelo.
        bloques = troceador.trocear(linea)
        avisar(f"Transcripción dividida en {len(bloques)} tramo(s).")

        # 6. Generar la crónica.
        duracion = _formatear_duracion(linea[-1].fin)
        titulo = f"Sesión del {grabacion.etiqueta_fecha}"
        resultado = resumidor.resumir(
            bloques,
            titulo=titulo,
            metadatos={
                "Fecha": grabacion.etiqueta_fecha,
                "Duración": duracion,
                "Participantes": ", ".join(
                    sorted({seg.hablante for seg in linea})
                ),
            },
            modelo=configuracion.modelo_ollama,
            avisar=avisar,
        )

        # 7. Guardar (siempre en datos/resumenes, y en la carpeta extra si la hay).
        ruta = _guardar_resumen(
            resultado.documento,
            f"{etiqueta}.md",
            configuracion.destinos_resumen(),
            avisar,
        )
        avisar(f"Crónica guardada en {ruta}")

        return ResultadoProceso(id_grabacion=grabacion.id, ok=True, resumen=ruta)

    except (ErrorCraig, ErrorTranscripcion, resumidor.ErrorOllama, OSError) as exc:
        avisar(f"ERROR: {exc}")
        return ResultadoProceso(id_grabacion=grabacion.id, ok=False, error=str(exc))
    except Exception as exc:  # noqa: BLE001 - la GUI nunca debe morir por esto
        avisar(f"ERROR inesperado: {exc}")
        return ResultadoProceso(
            id_grabacion=grabacion.id,
            ok=False,
            error=f"{exc}\n{traceback.format_exc()}",
        )


def procesar_pendientes(
    configuracion: cfg.Config,
    avisar: Avisar = _no_avisar,
    detener: Callable[[], bool] | None = None,
) -> list[ResultadoProceso]:
    """Busca grabaciones terminadas sin procesar y las procesa todas.

    Args:
        detener: si devuelve True, se para tras la grabación en curso.
    """
    cfg.asegurar_carpetas()
    registro = Registro.cargar(cfg.RUTA_PROCESADAS)

    try:
        grabaciones = craig_client.grabaciones_terminadas()
    except ErrorCraig as exc:
        avisar(f"No se pudo consultar las grabaciones: {exc}")
        return []

    pendientes = [g for g in grabaciones if not registro.ya_procesada(g.id)]

    if not pendientes:
        avisar("No hay grabaciones nuevas que procesar.")
        return []

    avisar(f"{len(pendientes)} grabación(es) pendiente(s).")

    # Un único transcriptor para todas: cargar el modelo es lo más lento.
    transcriptor = Transcriptor(
        modelo=configuracion.modelo_whisper, idioma=configuracion.idioma
    )

    resultados: list[ResultadoProceso] = []
    for grabacion in pendientes:
        if detener and detener():
            avisar("Proceso interrumpido.")
            break

        resultado = procesar_grabacion(
            grabacion, configuracion, transcriptor=transcriptor, avisar=avisar
        )
        resultados.append(resultado)

        if resultado.ok and resultado.resumen:
            registro.marcar_ok(grabacion.id, resultado.resumen)
        else:
            registro.marcar_error(grabacion.id, resultado.error)

    return resultados


def limpiar_temporales() -> None:
    """Borra restos de ejecuciones interrumpidas."""
    for resto in Path(tempfile.gettempdir()).glob("rolsumen_*"):
        if resto.is_dir():
            shutil.rmtree(resto, ignore_errors=True)
