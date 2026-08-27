"""Transcripción de pistas de audio con faster-whisper.

Cada pista es de un único jugador, así que el hablante se deduce del nombre del
archivo y no hace falta diarización. La mayor parte de este módulo es filtrado:
sobre silencio —que es casi toda la pista de cualquier jugador— Whisper inventa
texto con aplomo, y hay que descartarlo.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Callable

from .. import dependencias
from .tipos import Segmento

PATRON_PISTA = re.compile(r"^(\d+)[-_](.+)$")

# Un tramo se da por inventado cuando fallan las dos señales que da Whisper a la
# vez: probabilidad de que no haya voz, y confianza en lo escrito. Son sus
# propios umbrales internos.
UMBRAL_SIN_VOZ = 0.6
UMBRAL_CONFIANZA = -1.0

# Una frase corta repetida por toda la pista es una muletilla inventada: se han
# visto 'Gracias.' en los segundos 0, 30 y 60 exactos, múltiplos de la ventana
# de análisis. Las frases largas repetidas sí pueden ser reales.
MINIMO_REPETICIONES = 3
PALABRAS_MAXIMAS_MULETILLA = 4

# Fin del bloque Unicode "Latin Extended-A". Por encima empiezan griego,
# cirílico, etc., que sobre una pista en español sólo pueden ser alucinación.
# El umbral es bajo porque suelen mezclar alfabetos dentro de la misma palabra
# ("прирostal": 4 caracteres ajenos de 9).
LIMITE_LATINO = 0x024F
PROPORCION_ALFABETO_AJENO = 0.3

# Pausa mínima para que el detector de voz corte ahí. En una conversación la
# gente calla a menudo; un valor bajo trocea de más sin ganar nada.
MIN_SILENCIO_MS = 1000

# Créditos de subtítulos que Whisper aprendió de su corpus y suelta al final.
ALUCINACIONES_HABITUALES = {
    "subtítulos realizados por la comunidad de amara.org",
    "subtitulos realizados por la comunidad de amara.org",
    "subtítulos por la comunidad de amara.org",
    "más videos en www.youtube.com",
    "gracias por ver el video",
    "gracias por ver el vídeo",
    "¡suscríbete al canal!",
}


class ErrorTranscripcion(RuntimeError):
    """Fallo al transcribir una pista."""


def nombre_hablante(ruta: Path) -> str:
    """'2-silverfishlord.flac' -> 'silverfishlord'."""
    coincidencia = PATRON_PISTA.match(ruta.stem)
    return coincidencia.group(2) if coincidencia else ruta.stem


def duracion_audio(ruta: Path) -> float | None:
    """Duración real en segundos, o None si ffprobe no puede decirlo."""
    try:
        salida = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(ruta)],
            capture_output=True, text=True, timeout=30, check=True,
        )
        return float(salida.stdout.strip())
    except (subprocess.SubprocessError, ValueError, OSError):
        return None


def _normalizar(texto: str) -> str:
    """Forma canónica para comparar frases; en español los signos abren y cierran."""
    return texto.strip().lower().strip(".!?¡¿,… ")


def _es_alucinacion(texto: str) -> bool:
    return _normalizar(texto) in ALUCINACIONES_HABITUALES or not texto.strip()


def _es_silencio(crudo: dict) -> bool:
    return (
        float(crudo.get("no_speech_prob", 0.0)) > UMBRAL_SIN_VOZ
        and float(crudo.get("avg_logprob", 0.0)) < UMBRAL_CONFIANZA
    )


def _alfabeto_ajeno(texto: str, minimo_ajeno: float = PROPORCION_ALFABETO_AJENO) -> bool:
    letras = [c for c in texto if c.isalpha()]
    if not letras:
        return False
    ajenas = sum(1 for c in letras if ord(c) > LIMITE_LATINO)
    return ajenas / len(letras) >= minimo_ajeno


def _frases_repetidas(
    segmentos_crudos: list[dict],
    minimo: int = MINIMO_REPETICIONES,
    palabras_maximas: int = PALABRAS_MAXIMAS_MULETILLA,
) -> set[str]:
    cuenta: dict[str, int] = {}
    for crudo in segmentos_crudos:
        texto = str(crudo.get("text", "")).strip()
        if texto and len(texto.split()) <= palabras_maximas:
            clave = _normalizar(texto)
            cuenta[clave] = cuenta.get(clave, 0) + 1
    return {clave for clave, veces in cuenta.items() if veces >= minimo}


def filtrar_segmentos(
    segmentos_crudos: list[dict],
    duracion: float | None,
    hablante: str,
    margen: float = 0.5,
) -> list[Segmento]:
    """Convierte la salida de Whisper en Segmentos, descartando lo inventado."""
    repetidas = _frases_repetidas(segmentos_crudos)
    segmentos: list[Segmento] = []
    anterior: str | None = None
    vistas: set[str] = set()

    for crudo in segmentos_crudos:
        inicio = float(crudo.get("start", 0.0))
        fin = float(crudo.get("end", inicio))
        texto = str(crudo.get("text", "")).strip()

        fuera_del_audio = duracion is not None and inicio >= duracion + margen
        if (
            fuera_del_audio
            or _es_alucinacion(texto)
            or _es_silencio(crudo)
            or _alfabeto_ajeno(texto)
            or texto == anterior
        ):
            continue

        # De una muletilla repetida se conserva la primera aparición, por si
        # aquella fuera real.
        clave = _normalizar(texto)
        if clave in repetidas:
            if clave in vistas:
                continue
            vistas.add(clave)

        if duracion is not None:
            fin = max(inicio, min(fin, duracion))

        segmentos.append(Segmento(inicio, fin, texto, hablante))
        anterior = texto

    return segmentos


class Transcriptor:
    """Whisper con el modelo cargado una sola vez para toda la sesión."""

    def __init__(
        self,
        modelo: str = "large-v3",
        idioma: str = "es",
        dispositivo: str = "auto",
        precision: str = "float16",
    ) -> None:
        self.nombre_modelo = modelo
        self.idioma = idioma
        self._dispositivo = dispositivo
        self._precision = precision
        self._modelo = None

    def dispositivo(self) -> str:
        return self._dispositivo

    def cargar(self, avisar: Callable[[str], None] | None = None) -> None:
        if self._modelo is not None:
            return
        if avisar:
            avisar(
                f"Cargando modelo '{self.nombre_modelo}' "
                f"({self._dispositivo}, {self._precision})..."
            )

        from faster_whisper import WhisperModel  # tarda: sólo al transcribir

        try:
            self._modelo = WhisperModel(
                self.nombre_modelo,
                device=self._dispositivo,
                compute_type=self._precision,
            )
        except Exception as exc:  # noqa: BLE001 - el error original es críptico
            raise ErrorTranscripcion(
                f"No se pudo cargar el modelo '{self.nombre_modelo}' en "
                f"{self._dispositivo} con precisión {self._precision}: {exc}"
            ) from exc

    def transcribir(
        self, ruta: Path, avisar: Callable[[str], None] | None = None
    ) -> list[Segmento]:
        # Whisper lanza ffmpeg por su cuenta y, si falta, el error que da es un
        # WinError 2 que no lo menciona.
        estado = dependencias.comprobar_ffmpeg()
        if not estado.disponible:
            raise ErrorTranscripcion(estado.ayuda)

        self.cargar(avisar)
        hablante = nombre_hablante(ruta)
        if avisar:
            avisar(f"Transcribiendo pista de {hablante}...")

        try:
            segmentos, _ = self._modelo.transcribe(
                str(ruta),
                language=self.idioma,
                # Sin detección de voz, el silencio (casi toda la pista) se
                # transcribe como texto inventado.
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": MIN_SILENCIO_MS},
            )
            # transcribe() devuelve un generador perezoso: aquí es donde
            # ocurre de verdad la transcripción.
            crudos = [
                {
                    "start": s.start,
                    "end": s.end,
                    "text": s.text,
                    "no_speech_prob": s.no_speech_prob,
                    "avg_logprob": s.avg_logprob,
                }
                for s in segmentos
            ]
        except FileNotFoundError as exc:
            raise ErrorTranscripcion(
                f"No se pudo leer el audio de '{ruta.name}'. "
                "Comprueba que ffmpeg sigue instalado y accesible."
            ) from exc
        except Exception as exc:  # noqa: BLE001 - queremos saber qué pista falló
            raise ErrorTranscripcion(
                f"No se pudo transcribir '{ruta.name}': {exc}"
            ) from exc

        return filtrar_segmentos(crudos, duracion_audio(ruta), hablante)


def guardar_transcripcion(segmentos: list[Segmento], destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    datos = [
        {"inicio": s.inicio, "fin": s.fin, "texto": s.texto, "hablante": s.hablante}
        for s in segmentos
    ]
    destino.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")


def cargar_transcripcion(origen: Path) -> list[Segmento]:
    datos = json.loads(origen.read_text(encoding="utf-8"))
    return [
        Segmento(d["inicio"], d["fin"], d["texto"], d["hablante"]) for d in datos
    ]
