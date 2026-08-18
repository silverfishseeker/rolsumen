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
from .transcriptor import (
    ErrorTranscripcion,
    Transcriptor,
    cargar_transcripcion,
    guardar_transcripcion,
)

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


def _mapa_hablantes(
    id_grabacion: str, configuracion: cfg.Config, avisar: Avisar = _no_avisar
) -> dict[str, str]:
    """Traduce el identificador de cada pista al nombre que verá el lector.

    Hay dos saltos encadenados:

        número de pista  ->  usuario de Discord  ->  nombre del personaje

    El primero lo da Craig (las pistas del `cook` self-hosted se llaman `1`,
    `2`, `3`); el segundo, el mapeo opcional de `config.ini`. Si falta
    cualquiera de los dos, se usa lo que haya: antes el usuario de Discord que
    un número, y antes un número que nada.
    """
    mapa: dict[str, str] = {}

    numero_a_usuario = craig_client.usuarios(id_grabacion)
    if numero_a_usuario:
        avisar(f"Participantes: {', '.join(sorted(numero_a_usuario.values()))}")
    else:
        avisar("Aviso: no se pudo identificar a los participantes de la grabación.")

    for numero, usuario in numero_a_usuario.items():
        mapa[numero] = configuracion.nombre_personaje(usuario)

    # Un usuario puede venir ya con nombre en la pista (ZIP de la web pública).
    for usuario, personaje in configuracion.jugadores.items():
        mapa.setdefault(usuario, personaje)

    return mapa


def _crear_transcriptor(configuracion: cfg.Config) -> Transcriptor:
    """Construye el transcriptor con los ajustes del usuario."""
    modelos = configuracion.modelos
    return Transcriptor(
        modelo=modelos.transcripcion,
        idioma=configuracion.idioma,
        dispositivo=modelos.dispositivo_efectivo(),
        precision=modelos.precision_efectiva(),
    )


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
            transcriptor = transcriptor or _crear_transcriptor(configuracion)
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
            pistas_transcritas,
            mapa_personajes=_mapa_hablantes(grabacion.id, configuracion, avisar),
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
            modelo=configuracion.modelos.resumen,
            contexto=configuracion.modelos.contexto_resumen,
            modo=configuracion.modo,
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
    """Etiquetas de las sesiones que ya tienen transcripción guardada."""
    if not cfg.DIR_TRANSCRIPCIONES.exists():
        return []
    return sorted(
        carpeta.name
        for carpeta in cfg.DIR_TRANSCRIPCIONES.iterdir()
        if carpeta.is_dir() and any(carpeta.glob("*.json"))
    )


def reprocesar(
    etiqueta: str,
    configuracion: cfg.Config,
    avisar: Avisar = _no_avisar,
) -> ResultadoProceso:
    """Regenera la crónica de una sesión ya transcrita.

    Se salta la extracción del audio y la transcripción, que son las fases
    lentas, y rehace sólo el combinado y el resumen. Sirve para afinar los
    prompts o el mapeo de personajes y ver el resultado en un minuto en vez de
    volver a transcribir horas de audio.
    """
    carpeta = cfg.DIR_TRANSCRIPCIONES / etiqueta
    archivos = sorted(carpeta.glob("*.json"))

    if not archivos:
        return ResultadoProceso(
            id_grabacion=etiqueta,
            ok=False,
            error=f"No hay transcripciones guardadas en {carpeta}.",
        )

    # La etiqueta es "<fecha>_<id>"; el id es lo que va detrás del primer '_'.
    id_grabacion = etiqueta.split("_", 1)[-1]
    fecha = etiqueta.split("_", 1)[0]

    try:
        avisar(f"Cargando {len(archivos)} pista(s) transcrita(s)...")
        pistas = [cargar_transcripcion(archivo) for archivo in archivos]

        linea = combinador.combinar(
            pistas,
            mapa_personajes=_mapa_hablantes(id_grabacion, configuracion, avisar),
        )
        if not linea:
            raise ErrorTranscripcion("Las transcripciones guardadas están vacías.")

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
            resultado.documento,
            f"{etiqueta}.md",
            configuracion.destinos_resumen(),
            avisar,
        )
        avisar(f"Crónica guardada en {ruta}")

        return ResultadoProceso(id_grabacion=etiqueta, ok=True, resumen=ruta)

    except (ErrorTranscripcion, resumidor.ErrorOllama, OSError) as exc:
        avisar(f"ERROR: {exc}")
        return ResultadoProceso(id_grabacion=etiqueta, ok=False, error=str(exc))


def limpiar_temporales() -> None:
    """Borra restos de ejecuciones interrumpidas."""
    for resto in Path(tempfile.gettempdir()).glob("rolsumen_*"):
        if resto.is_dir():
            shutil.rmtree(resto, ignore_errors=True)
