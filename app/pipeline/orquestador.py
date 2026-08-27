"""Encadenado completo: de la grabación de Craig al documento final."""

from __future__ import annotations

import shutil
import tempfile
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .. import config as cfg
from .. import craig_client
from ..craig_client import ErrorCraig, Grabacion
from . import combinador, resumidor, troceador
from .registro import Registro
from .tipos import Segmento
from .transcriptor import (
    ErrorTranscripcion,
    Transcriptor,
    cargar_transcripcion,
    guardar_transcripcion,
)

Avisar = Callable[[str], None]

# Errores esperables de cualquier fase; los demás son fallos de programación.
ERRORES_CONOCIDOS = (ErrorCraig, ErrorTranscripcion, resumidor.ErrorOllama, OSError)


@dataclass
class ResultadoProceso:
    id_grabacion: str
    ok: bool
    resumen: Path | None = None
    error: str = ""


def _no_avisar(_: str) -> None:
    pass


def _formatear_duracion(segundos: float) -> str:
    horas, resto = divmod(int(segundos), 3600)
    minutos, _ = divmod(resto, 60)
    return f"{horas} h {minutos} min" if horas else f"{minutos} min"


def _crear_transcriptor(configuracion: cfg.Config) -> Transcriptor:
    modelos = configuracion.modelos
    return Transcriptor(
        modelo=modelos.transcripcion,
        idioma=configuracion.idioma,
        dispositivo=modelos.dispositivo_efectivo(),
        precision=modelos.precision_efectiva(),
    )


def _mapa_hablantes(
    id_grabacion: str, configuracion: cfg.Config, avisar: Avisar = _no_avisar
) -> dict[str, str]:
    """Traduce el identificador de cada pista al nombre que verá el lector.

    Son dos saltos encadenados: número de pista -> usuario de Discord -> nombre
    del personaje. Si falta cualquiera, se usa lo que haya: antes el usuario que
    un número, y antes un número que nada.
    """
    numero_a_usuario = craig_client.usuarios(id_grabacion)
    if numero_a_usuario:
        avisar(f"Participantes: {', '.join(sorted(numero_a_usuario.values()))}")
    else:
        avisar("Aviso: no se pudo identificar a los participantes de la grabación.")

    mapa = {
        numero: configuracion.nombre_personaje(usuario)
        for numero, usuario in numero_a_usuario.items()
    }
    # Las pistas del ZIP de la web pública ya vienen con el nombre puesto.
    for usuario, personaje in configuracion.jugadores.items():
        mapa.setdefault(usuario, personaje)
    return mapa


def _guardar_resumen(
    documento: str, nombre: str, destinos: list[Path], avisar: Avisar
) -> Path:
    """Escribe el documento en todos los destinos y devuelve el principal.

    Que falle la carpeta adicional del usuario no debe tirar el proceso: el
    resumen ya está a salvo en la interna.
    """
    principal: Path | None = None

    for destino in destinos:
        try:
            destino.mkdir(parents=True, exist_ok=True)
            ruta = destino / nombre
            ruta.write_text(documento, encoding="utf-8")
            principal = principal or ruta
        except OSError as exc:
            avisar(f"Aviso: no se pudo escribir en {destino} ({exc})")

    if principal is None:
        raise OSError("No se pudo guardar el resumen en ninguna carpeta.")
    return principal


def _combinar_y_resumir(
    pistas: list[list[Segmento]],
    etiqueta: str,
    configuracion: cfg.Config,
    avisar: Avisar,
) -> Path:
    """De las pistas transcritas al documento guardado.

    Es la parte común a procesar una grabación nueva y a regenerar una ya
    transcrita. La etiqueta es "<fecha>_<id>".
    """
    fecha, _, id_grabacion = etiqueta.partition("_")

    linea = combinador.combinar(
        pistas, mapa_personajes=_mapa_hablantes(id_grabacion, configuracion, avisar)
    )
    if not linea:
        raise ErrorTranscripcion("No se transcribió nada. ¿Hay voz audible?")

    carpeta = cfg.DIR_TRANSCRIPCIONES / etiqueta
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / "linea_de_tiempo.txt").write_text(
        combinador.a_texto(linea), encoding="utf-8"
    )

    bloques = troceador.trocear(linea)
    avisar(f"Transcripción dividida en {len(bloques)} tramo(s).")

    resultado = resumidor.resumir(
        bloques,
        titulo=f"Sesión del {fecha}",
        metadatos={
            "Fecha": fecha,
            "Duración": _formatear_duracion(linea[-1].fin),
            "Participantes": ", ".join(sorted({s.hablante for s in linea})),
        },
        modelo=configuracion.modelos.resumen,
        contexto=configuracion.modelos.contexto_resumen,
        modo=configuracion.modo,
        avisar=avisar,
    )

    ruta = _guardar_resumen(
        resultado.documento, f"{etiqueta}.md", configuracion.destinos_resumen(), avisar
    )
    avisar(f"Crónica guardada en {ruta}")
    return ruta


def procesar_grabacion(
    grabacion: Grabacion,
    configuracion: cfg.Config,
    transcriptor: Transcriptor | None = None,
    avisar: Avisar = _no_avisar,
) -> ResultadoProceso:
    etiqueta = f"{grabacion.etiqueta_fecha}_{grabacion.id}"
    avisar(f"Procesando grabación {grabacion.id}...")

    try:
        avisar("Extrayendo el audio de Craig (esto puede tardar)...")
        zip_destino = cfg.DIR_GRABACIONES / f"{etiqueta}.zip"
        craig_client.cocinar(grabacion.id, zip_destino)

        with tempfile.TemporaryDirectory(prefix="rolsumen_") as tmp:
            pistas_audio = craig_client.extraer_pistas(zip_destino, Path(tmp))
            if not pistas_audio:
                raise ErrorCraig("La grabación no contiene ninguna pista de audio.")
            avisar(f"{len(pistas_audio)} pista(s) de audio encontradas.")

            transcriptor = transcriptor or _crear_transcriptor(configuracion)
            pistas = []
            for numero, pista in enumerate(pistas_audio, start=1):
                avisar(f"Transcribiendo pista {numero} de {len(pistas_audio)}...")
                segmentos = transcriptor.transcribir(pista, avisar=avisar)
                pistas.append(segmentos)
                guardar_transcripcion(
                    segmentos, cfg.DIR_TRANSCRIPCIONES / etiqueta / f"{pista.stem}.json"
                )

        ruta = _combinar_y_resumir(pistas, etiqueta, configuracion, avisar)
        return ResultadoProceso(grabacion.id, ok=True, resumen=ruta)

    except ERRORES_CONOCIDOS as exc:
        avisar(f"ERROR: {exc}")
        return ResultadoProceso(grabacion.id, ok=False, error=str(exc))
    except Exception as exc:  # noqa: BLE001 - la ventana nunca debe morir por esto
        avisar(f"ERROR inesperado: {exc}")
        return ResultadoProceso(
            grabacion.id, ok=False, error=f"{exc}\n{traceback.format_exc()}"
        )


def procesar_pendientes(
    configuracion: cfg.Config,
    avisar: Avisar = _no_avisar,
    detener: Callable[[], bool] | None = None,
) -> list[ResultadoProceso]:
    """Procesa las grabaciones terminadas que aún no se hayan resumido."""
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
    transcriptor = _crear_transcriptor(configuracion)
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


def sesiones_transcritas() -> list[str]:
    if not cfg.DIR_TRANSCRIPCIONES.exists():
        return []
    return sorted(
        carpeta.name
        for carpeta in cfg.DIR_TRANSCRIPCIONES.iterdir()
        if carpeta.is_dir() and any(carpeta.glob("*.json"))
    )


def reprocesar(
    etiqueta: str, configuracion: cfg.Config, avisar: Avisar = _no_avisar
) -> ResultadoProceso:
    """Regenera la crónica de una sesión ya transcrita.

    Se salta la extracción y la transcripción, que son las fases lentas, para
    poder afinar prompts o el mapeo de personajes en un minuto en vez de volver
    a transcribir horas de audio.
    """
    archivos = sorted((cfg.DIR_TRANSCRIPCIONES / etiqueta).glob("*.json"))
    if not archivos:
        return ResultadoProceso(
            etiqueta,
            ok=False,
            error=f"No hay transcripciones guardadas en {etiqueta}.",
        )

    try:
        avisar(f"Cargando {len(archivos)} pista(s) transcrita(s)...")
        pistas = [cargar_transcripcion(archivo) for archivo in archivos]
        ruta = _combinar_y_resumir(pistas, etiqueta, configuracion, avisar)
        return ResultadoProceso(etiqueta, ok=True, resumen=ruta)
    except ERRORES_CONOCIDOS as exc:
        avisar(f"ERROR: {exc}")
        return ResultadoProceso(etiqueta, ok=False, error=str(exc))


def limpiar_temporales() -> None:
    """Borra restos de ejecuciones interrumpidas."""
    for resto in Path(tempfile.gettempdir()).glob("rolsumen_*"):
        if resto.is_dir():
            shutil.rmtree(resto, ignore_errors=True)
