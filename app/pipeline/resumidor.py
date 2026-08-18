"""Generación de la cronología a partir de la transcripción, usando Ollama.

El documento final NO es un relato: es un acta consultable. Por eso el proceso
tiene dos fases y ninguna de ellas vuelve a comprimir los hechos ya extraídos:

  Fase 1 - Cada bloque produce su tramo de cronología, con secciones por escena.
           Se encadena el contexto: cada bloque recibe un resumen de lo anterior.
  Fase 2 - Se genera solo una cabecera (título, sinopsis y personajes) a partir
           de los tramos ya escritos, y se concatena todo.

La fase 2 deliberadamente no reescribe los tramos: en un documento pensado para
consultar hechos, perder detalle es peor que tener un texto algo más largo.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable

from .tipos import Bloque

URL_OLLAMA = "http://localhost:11434"

# Contexto pedido a Ollama. Por defecto Ollama usa 4096, muy por debajo de lo
# que necesitamos; qwen3:8b admite 40960, pero con 8 GB de VRAM el caché de
# atención no cabe, así que nos quedamos en un punto intermedio realista.
CONTEXTO_OLLAMA = 16384

TIMEOUT_SEGUNDOS = 900

# Baja para favorecer la fidelidad a los hechos frente a la creatividad.
TEMPERATURA = 0.3

_PATRON_PENSAMIENTO = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


class ErrorOllama(RuntimeError):
    """Fallo al comunicarse con Ollama."""


INSTRUCCIONES_BLOQUE = """\
Eres un cronista que documenta partidas de rol de mesa. Recibes la \
transcripción de un tramo de una sesión y escribes lo que ocurrió.

El documento que produces sirve para CONSULTAR HECHOS meses después ("¿a quién \
matamos en la torre?", "¿qué nos prometió el alcalde?"). No es un relato \
literario.

Reglas:
- Escribe solo hechos ocurridos DENTRO de la ficción.
- IGNORA por completo todo lo que pase en la mesa y no en la ficción: reglas \
del juego, tiradas de dados y sus resultados, puntos de vida, cálculos, \
preguntas de los jugadores al máster, bromas, pausas y temas ajenos a la \
partida.
- Traduce la mecánica a ficción: si un personaje tira percepción y ve algo, \
anota lo que el personaje vio, nunca la tirada ni el número obtenido. Escribe \
"Kaelen distinguió dos figuras junto al portón", no "Kaelen sacó un 20 en \
percepción".
- No inventes NADA. Si algo no queda claro en la transcripción, omítelo. No \
rellenes huecos ni especules sobre intenciones.
- Sé concreto: nombres propios, lugares, objetos, cantidades, decisiones \
tomadas y sus consecuencias.
- Habla siempre de los PERSONAJES, nunca de los jugadores ni de la mesa. \
Escribe "el grupo acampó", no "los jugadores acamparon".
- Nada de adornos literarios ni de valoraciones. Frases directas.
- Organiza el tramo en secciones con encabezado `### ` por escena o situación. \
Dentro de cada sección, viñetas con los hechos en orden cronológico.
- Escribe en español, en pasado.

Devuelve únicamente el texto en Markdown, sin explicaciones sobre tu trabajo.
"""

INSTRUCCIONES_CABECERA = """\
Eres un cronista que documenta partidas de rol de mesa. Recibes la crónica ya \
escrita de una sesión y debes redactar SOLO su cabecera.

Devuelve exactamente estas tres secciones en Markdown, y nada más:

## Sinopsis
Un párrafo breve (3-5 frases) con lo esencial de la sesión.

## Personajes y criaturas
Lista con viñetas de los personajes, criaturas y facciones que aparecen, cada \
uno con una descripción de una línea. Solo los que aparecen en la crónica.

## Lugares
Lista con viñetas de los lugares visitados o mencionados, cada uno con una \
línea. Solo los que aparecen en la crónica.

No inventes nada que no esté en la crónica. No repitas la cronología completa. \
Escribe en español.
"""


@dataclass
class ResultadoResumen:
    """Cronología final y sus tramos intermedios."""

    documento: str
    tramos: list[str]


def _limpiar(texto: str) -> str:
    """Quita los bloques de razonamiento que emiten los modelos tipo Qwen3."""
    return _PATRON_PENSAMIENTO.sub("", texto).strip()


def ollama_disponible(url: str = URL_OLLAMA, timeout: float = 3.0) -> bool:
    """Comprueba si el servicio de Ollama responde."""
    try:
        with urllib.request.urlopen(f"{url}/api/tags", timeout=timeout) as respuesta:
            return respuesta.status == 200
    except (urllib.error.URLError, OSError):
        return False


def modelos_disponibles(url: str = URL_OLLAMA, timeout: float = 5.0) -> list[str]:
    """Lista los modelos instalados en Ollama."""
    try:
        with urllib.request.urlopen(f"{url}/api/tags", timeout=timeout) as respuesta:
            datos = json.loads(respuesta.read().decode("utf-8"))
        return [m["name"] for m in datos.get("models", [])]
    except (urllib.error.URLError, OSError, json.JSONDecodeError, KeyError):
        return []


def generar(
    prompt: str,
    modelo: str = "qwen3:8b",
    url: str = URL_OLLAMA,
    contexto: int = CONTEXTO_OLLAMA,
    timeout: int = TIMEOUT_SEGUNDOS,
) -> str:
    """Llama a Ollama y devuelve la respuesta generada, ya limpia."""
    cuerpo = json.dumps(
        {
            "model": modelo,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_ctx": contexto,
                "temperature": TEMPERATURA,
            },
        }
    ).encode("utf-8")

    peticion = urllib.request.Request(
        f"{url}/api/generate",
        data=cuerpo,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
            datos = json.loads(respuesta.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detalle = exc.read().decode("utf-8", errors="replace")
        raise ErrorOllama(f"Ollama respondió {exc.code}: {detalle}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise ErrorOllama(
            f"No se pudo contactar con Ollama en {url}. ¿Está en marcha? ({exc})"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ErrorOllama(f"Respuesta ilegible de Ollama: {exc}") from exc

    return _limpiar(datos.get("response", ""))


def _prompt_bloque(bloque: Bloque, contexto_previo: str | None) -> str:
    partes = [INSTRUCCIONES_BLOQUE]

    if contexto_previo:
        partes.append(
            "\n--- LO OCURRIDO HASTA AHORA (contexto, no lo repitas) ---\n"
            f"{contexto_previo}\n"
            "--- FIN DEL CONTEXTO ---\n\n"
            "Continúa la crónica a partir de aquí. Narra ÚNICAMENTE los hechos "
            "nuevos del tramo siguiente; no repitas lo que ya está contado."
        )

    partes.append(
        f"\n--- TRANSCRIPCIÓN DEL TRAMO {bloque.indice} DE {bloque.total} ---\n"
        f"{bloque.texto()}\n"
        "--- FIN DE LA TRANSCRIPCIÓN ---\n"
    )

    return "\n".join(partes)


def _resumir_contexto(tramo: str, limite: int = 1500) -> str:
    """Recorta un tramo para usarlo como contexto del bloque siguiente."""
    if len(tramo) <= limite:
        return tramo
    return "..." + tramo[-limite:]


def resumir_bloques(
    bloques: list[Bloque],
    modelo: str = "qwen3:8b",
    url: str = URL_OLLAMA,
    avisar: Callable[[str], None] | None = None,
) -> list[str]:
    """Fase 1: genera el tramo de cronología de cada bloque, en cadena."""
    tramos: list[str] = []
    contexto: str | None = None

    for bloque in bloques:
        if avisar:
            avisar(f"Resumiendo tramo {bloque.indice} de {bloque.total}...")

        tramo = generar(_prompt_bloque(bloque, contexto), modelo=modelo, url=url)
        tramos.append(tramo)
        contexto = _resumir_contexto(tramo)

    return tramos


def generar_cabecera(
    tramos: list[str],
    modelo: str = "qwen3:8b",
    url: str = URL_OLLAMA,
    avisar: Callable[[str], None] | None = None,
) -> str:
    """Fase 2: sinopsis, personajes y lugares, a partir de los tramos escritos."""
    if avisar:
        avisar("Redactando sinopsis y elenco...")

    cronica = "\n\n".join(tramos)
    prompt = (
        f"{INSTRUCCIONES_CABECERA}\n"
        "--- CRÓNICA DE LA SESIÓN ---\n"
        f"{cronica}\n"
        "--- FIN DE LA CRÓNICA ---\n"
    )
    return generar(prompt, modelo=modelo, url=url)


def componer_documento(
    titulo: str,
    cabecera: str,
    tramos: list[str],
    metadatos: dict[str, str] | None = None,
) -> str:
    """Monta el documento final en Markdown."""
    partes = [f"# {titulo}", ""]

    if metadatos:
        for clave, valor in metadatos.items():
            partes.append(f"**{clave}:** {valor}  ")
        partes.append("")

    if cabecera:
        partes.extend([cabecera, ""])

    partes.extend(["---", "", "## Cronología", ""])
    partes.append("\n\n".join(tramos))

    return "\n".join(partes).strip() + "\n"


def resumir(
    bloques: list[Bloque],
    titulo: str,
    metadatos: dict[str, str] | None = None,
    modelo: str = "qwen3:8b",
    url: str = URL_OLLAMA,
    avisar: Callable[[str], None] | None = None,
) -> ResultadoResumen:
    """Ejecuta las dos fases y devuelve el documento final."""
    if not bloques:
        raise ErrorOllama("No hay nada que resumir: la transcripción está vacía.")

    tramos = resumir_bloques(bloques, modelo=modelo, url=url, avisar=avisar)

    # Con un solo tramo la cabecera aporta poco, pero mantiene el formato
    # uniforme entre sesiones cortas y largas.
    cabecera = generar_cabecera(tramos, modelo=modelo, url=url, avisar=avisar)

    documento = componer_documento(titulo, cabecera, tramos, metadatos)
    return ResultadoResumen(documento=documento, tramos=tramos)
