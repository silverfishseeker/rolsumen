"""Transcripción de pistas de audio con Whisper.

Cada pista corresponde a un único jugador (grabación multipista de Craig), así
que no hace falta diarización: el hablante se deduce del nombre del archivo.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Callable

from .. import dependencias
from .tipos import Segmento

# Craig nombra las pistas como "1-usuario.flac", "2-otro.ogg", ...
PATRON_PISTA = re.compile(r"^(\d+)[-_](.+)$")

# Umbrales de detección de silencio. Son los mismos que usa Whisper
# internamente: por encima de esta probabilidad de "sin voz" y por debajo de
# esta confianza, lo transcrito suele ser inventado.
UMBRAL_SIN_VOZ = 0.6
UMBRAL_CONFIANZA = -1.0

# A partir de cuántas apariciones se considera muletilla una frase corta, y
# cuántas palabras puede tener para contar como "corta".
MINIMO_REPETICIONES = 3
PALABRAS_MAXIMAS_MULETILLA = 4

# Frases que Whisper alucina de forma recurrente al final de un audio
# (créditos de subtítulos aprendidos del corpus de entrenamiento).
ALUCINACIONES_HABITUALES = {
    "subtítulos realizados por la comunidad de amara.org",
    "subtitulos realizados por la comunidad de amara.org",
    "más videos en www.youtube.com",
    "gracias por ver el video",
    "gracias por ver el vídeo",
    "¡suscríbete al canal!",
    "subtítulos por la comunidad de amara.org",
}


class ErrorTranscripcion(RuntimeError):
    """Fallo al transcribir una pista."""


def nombre_hablante(ruta: Path) -> str:
    """Extrae el nombre del usuario a partir del nombre del archivo.

    'craig-test/2-silverfishlord.flac' -> 'silverfishlord'
    """
    tallo = ruta.stem
    coincidencia = PATRON_PISTA.match(tallo)
    if coincidencia:
        return coincidencia.group(2)
    return tallo


def duracion_audio(ruta: Path) -> float | None:
    """Duración real del archivo en segundos, según ffprobe.

    Devuelve None si ffprobe no está disponible o falla: en ese caso
    simplemente no se filtran las alucinaciones por duración.
    """
    try:
        salida = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(ruta),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        return float(salida.stdout.strip())
    except (subprocess.SubprocessError, ValueError, FileNotFoundError, OSError):
        return None


def _es_alucinacion(texto: str) -> bool:
    """Detecta frases-basura típicas de Whisper en tramos sin voz."""
    limpio = texto.strip().lower().rstrip(".!¡")
    if not limpio:
        return True
    return limpio in ALUCINACIONES_HABITUALES


def _normalizar(texto: str) -> str:
    """Forma canónica de una frase, para comparar repeticiones.

    Se quitan signos por ambos lados: en español la exclamación abre con '¡',
    así que '¡Gracias!' y 'Gracias.' deben considerarse la misma frase.
    """
    return texto.strip().lower().strip(".!?¡¿,… ")


def _frases_repetidas(
    segmentos_crudos: list[dict],
    minimo: int = MINIMO_REPETICIONES,
    palabras_maximas: int = PALABRAS_MAXIMAS_MULETILLA,
) -> set[str]:
    """Frases cortas que se repiten tantas veces que no pueden ser reales.

    Se limita a frases de pocas palabras: una frase larga repetida puede ser
    una coletilla legítima del jugador, pero "Gracias." veinte veces no lo es.
    """
    cuenta: dict[str, int] = {}
    for crudo in segmentos_crudos:
        texto = str(crudo.get("text", "")).strip()
        if not texto or len(texto.split()) > palabras_maximas:
            continue
        clave = _normalizar(texto)
        cuenta[clave] = cuenta.get(clave, 0) + 1

    return {clave for clave, veces in cuenta.items() if veces >= minimo}


def _es_silencio(crudo: dict) -> bool:
    """¿El propio Whisper cree que este tramo no tiene voz?

    Whisper adjunta a cada segmento `no_speech_prob` (probabilidad de que no
    haya voz) y `avg_logprob` (lo seguro que está de lo que ha escrito). Cuando
    ambas señales van mal a la vez, lo escrito es casi siempre inventado: sobre
    silencio o ruido, Whisper tiende a producir muletillas como "Gracias." o
    créditos de subtítulos.

    Se usan los mismos umbrales que Whisper aplica internamente.
    """
    sin_voz = float(crudo.get("no_speech_prob", 0.0))
    confianza = float(crudo.get("avg_logprob", 0.0))
    return sin_voz > UMBRAL_SIN_VOZ and confianza < UMBRAL_CONFIANZA


def filtrar_segmentos(
    segmentos_crudos: list[dict],
    duracion: float | None,
    hablante: str,
    margen: float = 0.5,
) -> list[Segmento]:
    """Convierte la salida de Whisper en Segmentos, descartando alucinaciones.

    Se descartan tres cosas:
      1. Segmentos que empiezan más allá del final real del archivo: `large-v3`
         inventa texto repetido al terminar el audio.
      2. Tramos que el propio Whisper marca como "sin voz" (ver `_es_silencio`).
      3. Muletillas conocidas y repeticiones consecutivas.
    """
    # Una frase corta que se repite muchas veces a lo largo de la pista es
    # casi siempre inventada: sobre silencio, Whisper produce la misma
    # muletilla en cada ventana de análisis (se han observado 'Gracias.' en
    # 0 s, 30 s y 60 s exactos). No basta con mirar repeticiones seguidas,
    # porque entre medias puede colarse otra alucinación distinta.
    repetidas = _frases_repetidas(segmentos_crudos)

    segmentos: list[Segmento] = []
    texto_anterior: str | None = None
    vistas: set[str] = set()

    for crudo in segmentos_crudos:
        inicio = float(crudo.get("start", 0.0))
        fin = float(crudo.get("end", inicio))
        texto = str(crudo.get("text", "")).strip()

        if not texto:
            continue

        # Alucinación por marca de tiempo fuera del audio real.
        if duracion is not None and inicio >= duracion + margen:
            continue

        if _es_silencio(crudo):
            continue

        if _es_alucinacion(texto):
            continue

        # Alucinación por repetición: la misma frase una y otra vez.
        if texto_anterior is not None and texto == texto_anterior:
            continue

        # Muletilla repetida por toda la pista: se conserva sólo la primera
        # aparición, por si acaso fuera real.
        clave = _normalizar(texto)
        if clave in repetidas:
            if clave in vistas:
                continue
            vistas.add(clave)

        # Recortar el final al límite real del audio.
        if duracion is not None:
            fin = min(fin, duracion)
            if fin <= inicio:
                fin = inicio

        segmentos.append(
            Segmento(inicio=inicio, fin=fin, texto=texto, hablante=hablante)
        )
        texto_anterior = texto

    return segmentos


class Transcriptor:
    """Envoltorio sobre Whisper que carga el modelo una sola vez.

    Cargar el modelo `large-v3` lleva bastantes segundos, así que se reutiliza
    entre pistas de la misma sesión.
    """

    def __init__(self, modelo: str = "large-v3", idioma: str = "Spanish") -> None:
        self.nombre_modelo = modelo
        self.idioma = idioma
        self._modelo = None

    def cargar(self, avisar: Callable[[str], None] | None = None) -> None:
        """Carga el modelo en memoria (descarga la primera vez que se usa)."""
        if self._modelo is not None:
            return
        if avisar:
            avisar(f"Cargando modelo Whisper '{self.nombre_modelo}'...")

        import whisper  # import perezoso: tarda y sólo hace falta al transcribir

        self._modelo = whisper.load_model(self.nombre_modelo)

    def dispositivo(self) -> str:
        """'cuda' o 'cpu', según dónde haya quedado cargado el modelo."""
        if self._modelo is None:
            return "desconocido"
        try:
            return str(next(self._modelo.parameters()).device)
        except (StopIteration, AttributeError):
            return "desconocido"

    def transcribir(
        self,
        ruta: Path,
        avisar: Callable[[str], None] | None = None,
    ) -> list[Segmento]:
        """Transcribe una pista y devuelve sus segmentos ya limpios."""
        # Whisper lanza ffmpeg por su cuenta; si no está, el error que da es
        # un "WinError 2" que no menciona ffmpeg. Mejor detectarlo aquí.
        estado_ffmpeg = dependencias.comprobar_ffmpeg()
        if not estado_ffmpeg.disponible:
            raise ErrorTranscripcion(estado_ffmpeg.ayuda)

        self.cargar(avisar)
        hablante = nombre_hablante(ruta)

        if avisar:
            avisar(f"Transcribiendo pista de {hablante}...")

        try:
            resultado = self._modelo.transcribe(
                str(ruta),
                language=self.idioma,
                verbose=False,
            )
        except FileNotFoundError as exc:
            # Casi siempre significa que ffmpeg desapareció del PATH.
            raise ErrorTranscripcion(
                f"No se pudo leer el audio de '{ruta.name}'. "
                "Comprueba que ffmpeg sigue instalado y accesible."
            ) from exc
        except Exception as exc:  # noqa: BLE001 - queremos el contexto de la pista
            raise ErrorTranscripcion(
                f"No se pudo transcribir '{ruta.name}': {exc}"
            ) from exc

        duracion = duracion_audio(ruta)
        return filtrar_segmentos(resultado.get("segments", []), duracion, hablante)


def guardar_transcripcion(segmentos: list[Segmento], destino: Path) -> None:
    """Archiva la transcripción de una pista en JSON (para poder reprocesar)."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    datos = [
        {
            "inicio": seg.inicio,
            "fin": seg.fin,
            "texto": seg.texto,
            "hablante": seg.hablante,
        }
        for seg in segmentos
    ]
    destino.write_text(
        json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def cargar_transcripcion(origen: Path) -> list[Segmento]:
    """Lee una transcripción archivada previamente."""
    datos = json.loads(origen.read_text(encoding="utf-8"))
    return [
        Segmento(
            inicio=d["inicio"], fin=d["fin"], texto=d["texto"], hablante=d["hablante"]
        )
        for d in datos
    ]
