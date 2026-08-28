"""Encadenado completo: de la grabación de Craig al documento final."""

from __future__ import annotations

import json
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
Cancelado = Callable[[], bool]


class Cancelacion(Exception):
    """El usuario paro la tarea. No es un fallo: no se registra como error."""


def _nunca() -> bool:
    return False


def _rendirse_si_cancelado(cancelado: Cancelado) -> None:
    if cancelado():
        raise Cancelacion

# Errores esperables de cualquier fase; los demás son fallos de programación.
ERRORES_CONOCIDOS = (ErrorCraig, ErrorTranscripcion, resumidor.ErrorOllama, OSError)


@dataclass
class ResultadoProceso:
    id_grabacion: str
    ok: bool
    resumen: Path | None = None
    error: str = ""
    cancelada: bool = False


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


NOMBRE_HABLANTES = "hablantes.json"


def _ruta_hablantes(etiqueta: str) -> Path:
    return cfg.DIR_TRANSCRIPCIONES / etiqueta / NOMBRE_HABLANTES


def pistas_transcritas(etiqueta: str) -> list[Path]:
    """Los .json de la sesión que son pistas de verdad.

    En la carpeta hay más .json que pistas: `hablantes.json` guarda quién es
    cada una. Cargarlo como si fuera una pista revienta con TypeError, así que
    el filtro vive aqui y no repartido por cada `glob`.
    """
    carpeta = cfg.DIR_TRANSCRIPCIONES / etiqueta
    if not carpeta.is_dir():
        return []
    return sorted(
        a for a in carpeta.glob("*.json") if a.name != NOMBRE_HABLANTES
    )


def guardar_hablantes(etiqueta: str, numero_a_usuario: dict[str, str]) -> None:
    """Deja junto a las transcripciones quién es cada pista.

    Craig borra las grabaciones pasado su plazo de retención, y con ellas el
    archivo `.ogg.users` del que sale esta correspondencia. Sin copia local,
    regenerar una crónica antigua daría hablantes llamados «1», «2» y «3».
    """
    ruta = _ruta_hablantes(etiqueta)
    # Solo se anota junto a una sesion que ya existe: crear la carpeta aquí
    # sembraría sesiones fantasma con cualquier etiqueta que llegue.
    if not numero_a_usuario or not ruta.parent.is_dir():
        return
    ruta.write_text(
        json.dumps(numero_a_usuario, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def hablantes_guardados(etiqueta: str) -> dict[str, str]:
    try:
        datos = json.loads(_ruta_hablantes(etiqueta).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {str(k): str(v) for k, v in datos.items()} if isinstance(datos, dict) else {}


def _mapa_hablantes(
    etiqueta: str, configuracion: cfg.Config, avisar: Avisar = _no_avisar
) -> dict[str, str]:
    """Traduce el identificador de cada pista al nombre que verá el lector.

    Son dos saltos encadenados: número de pista -> usuario de Discord -> nombre
    del personaje. Si falta cualquiera, se usa lo que haya: antes el usuario que
    un número, y antes un número que nada.
    """
    _, _, id_grabacion = etiqueta.partition("_")

    numero_a_usuario = craig_client.usuarios(id_grabacion)
    if numero_a_usuario:
        guardar_hablantes(etiqueta, numero_a_usuario)
    else:
        # Craig ya no la tiene (o no responde): sirve la copia local.
        numero_a_usuario = hablantes_guardados(etiqueta)

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
    cancelado: Cancelado = _nunca,
) -> Path:
    """De las pistas transcritas al documento guardado.

    Es la parte común a procesar una grabación nueva y a regenerar una ya
    transcrita. La etiqueta es "<fecha>_<id>".
    """
    fecha = etiqueta.partition("_")[0]

    linea = combinador.combinar(
        pistas, mapa_personajes=_mapa_hablantes(etiqueta, configuracion, avisar)
    )
    if not linea:
        raise ErrorTranscripcion("No se transcribió nada. ¿Hay voz audible?")

    carpeta = cfg.DIR_TRANSCRIPCIONES / etiqueta
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / "linea_de_tiempo.txt").write_text(
        combinador.a_texto(linea), encoding="utf-8"
    )

    modelos = configuracion.modelos
    bloques = troceador.trocear(linea, presupuesto=modelos.tokens_por_bloque)
    avisar(f"Transcripción dividida en {len(bloques)} tramo(s).")

    resultado = resumidor.resumir(
        bloques,
        titulo=f"Sesión del {fecha}",
        metadatos={
            "Fecha": fecha,
            "Duración": _formatear_duracion(linea[-1].fin),
            "Participantes": ", ".join(sorted({s.hablante for s in linea})),
        },
        modelo=modelos.resumen,
        url=modelos.url_ollama,
        contexto=modelos.contexto_resumen,
        temperatura=modelos.temperatura,
        modo=configuracion.modo,
        avisar=avisar,
        entre_bloques=lambda: _rendirse_si_cancelado(cancelado),
    )

    ruta = _guardar_resumen(
        resultado.documento, f"{etiqueta}.md", configuracion.destinos_resumen(), avisar
    )
    avisar(f"Crónica guardada en {ruta}")
    return ruta


def etiqueta_de(grabacion: Grabacion) -> str:
    """Nombre con el que se guarda todo lo de una grabación: <fecha>_<id>."""
    return f"{grabacion.etiqueta_fecha}_{grabacion.id}"


def transcribir_grabacion(
    grabacion: Grabacion,
    configuracion: cfg.Config,
    transcriptor: Transcriptor | None = None,
    avisar: Avisar = _no_avisar,
    cancelado: Cancelado = _nunca,
) -> ResultadoProceso:
    """Primer paso: del audio guardado en Craig a una transcripción por pista.

    No resume a propósito. En modo manual el usuario decide cuándo dar el
    segundo paso; en automático lo encadena la cola.
    """
    etiqueta = etiqueta_de(grabacion)
    avisar(f"Extrayendo el audio de {grabacion.id} (esto puede tardar)...")

    try:
        zip_destino = cfg.DIR_GRABACIONES / f"{etiqueta}.zip"
        craig_client.cocinar(grabacion.id, zip_destino)
        _rendirse_si_cancelado(cancelado)

        with tempfile.TemporaryDirectory(prefix="rolsumen_") as tmp:
            pistas_audio = craig_client.extraer_pistas(zip_destino, Path(tmp))
            if not pistas_audio:
                raise ErrorCraig("La grabación no contiene ninguna pista de audio.")
            avisar(f"{len(pistas_audio)} pista(s) de audio encontradas.")

            transcriptor = transcriptor or _crear_transcriptor(configuracion)
            for numero, pista in enumerate(pistas_audio, start=1):
                _rendirse_si_cancelado(cancelado)
                avisar(f"Transcribiendo pista {numero} de {len(pistas_audio)}...")
                segmentos = transcriptor.transcribir(pista, avisar=avisar)
                if not guardar_transcripcion(
                    segmentos, cfg.DIR_TRANSCRIPCIONES / etiqueta / f"{pista.stem}.json"
                ):
                    avisar(
                        f"Aviso: la pista {numero} no produjo texto; se conserva "
                        "la transcripción anterior."
                    )

        avisar(f"Transcripción de {etiqueta} terminada.")
        return ResultadoProceso(etiqueta, ok=True)

    except Cancelacion:
        avisar("Tarea cancelada.")
        return ResultadoProceso(etiqueta, ok=False, error="cancelada", cancelada=True)
    except ERRORES_CONOCIDOS as exc:
        avisar(f"ERROR: {exc}")
        return ResultadoProceso(etiqueta, ok=False, error=str(exc))
    except Exception as exc:  # noqa: BLE001 - la ventana nunca debe morir por esto
        avisar(f"ERROR inesperado: {exc}")
        return ResultadoProceso(
            etiqueta, ok=False, error=f"{exc}\n{traceback.format_exc()}"
        )


def procesar_grabacion(
    grabacion: Grabacion,
    configuracion: cfg.Config,
    transcriptor: Transcriptor | None = None,
    avisar: Avisar = _no_avisar,
    cancelado: Cancelado = _nunca,
) -> ResultadoProceso:
    """Los dos pasos encadenados, que es lo que hace el modo automático."""
    transcrita = transcribir_grabacion(
        grabacion, configuracion, transcriptor, avisar, cancelado
    )
    if not transcrita.ok:
        return ResultadoProceso(
            grabacion.id,
            ok=False,
            error=transcrita.error,
            cancelada=transcrita.cancelada,
        )

    resumida = reprocesar(etiqueta_de(grabacion), configuracion, avisar, cancelado)
    return ResultadoProceso(
        grabacion.id,
        ok=resumida.ok,
        resumen=resumida.resumen,
        error=resumida.error,
        cancelada=resumida.cancelada,
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

    parar = detener or _nunca

    for grabacion in pendientes:
        if parar():
            avisar("Proceso interrumpido.")
            break

        resultado = procesar_grabacion(
            grabacion,
            configuracion,
            transcriptor=transcriptor,
            avisar=avisar,
            # Sin esto solo se podía interrumpir entre grabaciones, nunca
            # durante una transcripción, que es lo que de verdad tarda.
            cancelado=parar,
        )
        resultados.append(resultado)

        if resultado.cancelada:
            # Cancelar no es fallar: anotarlo como error ensucia el registro
            # y no aporta nada, porque igualmente se reintentará.
            break
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
        if carpeta.is_dir() and pistas_transcritas(carpeta.name)
    )


def reprocesar(
    etiqueta: str,
    configuracion: cfg.Config,
    avisar: Avisar = _no_avisar,
    cancelado: Cancelado = _nunca,
) -> ResultadoProceso:
    """Segundo paso: de las transcripciones guardadas a la crónica.

    Se salta la extracción y la transcripción, que son las fases lentas, para
    poder afinar prompts o el mapeo de personajes en un minuto en vez de volver
    a transcribir horas de audio.
    """
    archivos = pistas_transcritas(etiqueta)
    if not archivos:
        return ResultadoProceso(
            etiqueta,
            ok=False,
            error=f"No hay transcripciones guardadas en {etiqueta}.",
        )

    try:
        avisar(f"Cargando {len(archivos)} pista(s) transcrita(s)...")
        pistas = [cargar_transcripcion(archivo) for archivo in archivos]
        ruta = _combinar_y_resumir(pistas, etiqueta, configuracion, avisar, cancelado)
        return ResultadoProceso(etiqueta, ok=True, resumen=ruta)
    except Cancelacion:
        avisar("Tarea cancelada.")
        return ResultadoProceso(etiqueta, ok=False, error="cancelada", cancelada=True)
    except ERRORES_CONOCIDOS as exc:
        avisar(f"ERROR: {exc}")
        return ResultadoProceso(etiqueta, ok=False, error=str(exc))


@dataclass(frozen=True)
class Disponible:
    """Una fila de las listas de la pestaña Trabajo."""

    clave: str          # id de grabación, etiqueta de sesión o nombre de archivo
    titulo: str
    detalle: str = ""
    ruta: Path | None = None


def grabaciones_disponibles(avisar: Avisar = _no_avisar) -> list[Disponible]:
    """Grabaciones terminadas en Craig, con lo que ya se ha hecho de cada una.

    Craig borra las grabaciones antiguas de su almacén, pero la fila sigue en su
    base de datos: por eso se marcan las que ya no se pueden extraer.
    """
    try:
        grabaciones = craig_client.grabaciones_terminadas()
    except ErrorCraig as exc:
        avisar(f"No se pudieron consultar las grabaciones: {exc}")
        return []

    transcritas = set(sesiones_transcritas())
    filas = []
    for grabacion in grabaciones:
        etiqueta = etiqueta_de(grabacion)
        if etiqueta in transcritas:
            estado = "transcrita"
        elif (cfg.DIR_GRABACIONES / f"{etiqueta}.zip").exists():
            estado = "audio listo"
        else:
            estado = "pendiente"
        filas.append(
            Disponible(clave=grabacion.id, titulo=etiqueta, detalle=estado)
        )
    return filas


def transcripciones_disponibles() -> list[Disponible]:
    filas = []
    for etiqueta in sesiones_transcritas():
        carpeta = cfg.DIR_TRANSCRIPCIONES / etiqueta
        pistas = len(pistas_transcritas(etiqueta))
        resumida = (cfg.DIR_RESUMENES / f"{etiqueta}.md").exists()
        filas.append(
            Disponible(
                clave=etiqueta,
                titulo=etiqueta,
                detalle=f"{pistas} pistas"
                + (" · resumida" if resumida else " · pendiente"),
                ruta=carpeta,
            )
        )
    return filas


def resumenes_disponibles() -> list[Disponible]:
    if not cfg.DIR_RESUMENES.exists():
        return []
    filas = []
    for archivo in sorted(cfg.DIR_RESUMENES.glob("*.md")):
        kb = archivo.stat().st_size / 1024
        filas.append(
            Disponible(
                clave=archivo.name,
                titulo=archivo.stem,
                detalle=f"{kb:,.0f} KB",
                ruta=archivo,
            )
        )
    return filas


def ids_terminadas() -> set[str] | None:
    """Identificadores de las grabaciones terminadas, o None si no se pudo pedir.

    La diferencia importa: confundir "Craig no contesta" con "no hay ninguna"
    hace que, en cuanto conteste, el historial entero parezca recién llegado.
    """
    try:
        return {g.id for g in craig_client.grabaciones_terminadas()}
    except ErrorCraig:
        return None


def grabaciones_nuevas(conocidas: set[str]) -> list[Grabacion]:
    """Grabaciones terminadas que no estaban cuando se abrió la aplicación.

    El modo automático solo actúa sobre estas: al arrancar se queda esperando y
    no toca el historial, que es cosa de la pestaña Trabajo.
    """
    try:
        return [
            g for g in craig_client.grabaciones_terminadas() if g.id not in conocidas
        ]
    except ErrorCraig:
        return []


def limpiar_temporales() -> None:
    """Borra restos de ejecuciones interrumpidas."""
    for resto in Path(tempfile.gettempdir()).glob("rolsumen_*"):
        if resto.is_dir():
            shutil.rmtree(resto, ignore_errors=True)
