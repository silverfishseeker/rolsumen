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

from ..config import DIR_PROMPTS, MODO_POR_DEFECTO
from .tipos import Bloque
from .troceador import CARACTERES_POR_TOKEN

URL_OLLAMA = "http://localhost:11434"

# Contexto pedido a Ollama. Por defecto Ollama usa 4096, muy por debajo de lo
# que necesitamos. El techo no lo marca el modelo (qwen3:8b admite 40960) sino
# la memoria de vídeo: si el modelo más su caché de atención no caben, Ollama
# descarga parte a la CPU y la generación se desploma.
#
# Medido con qwen3:8b en una GPU de 8 GB:
#     4096 -> 100% GPU     8192 -> 100% GPU
#    12288 -> 13% en CPU  16384 -> 20% en CPU
#
# Con más memoria de vídeo se puede subir; comprobar con `ollama ps` que sigue
# marcando 100% GPU.
CONTEXTO_OLLAMA = 8192

# Los modelos de razonamiento (qwen3 y similares) generan un bloque <think>
# antes de responder. Aquí se descarta siempre, así que generarlo es tiempo
# tirado: en una prueba, el mismo prompt tardó más de 300 s con razonamiento y
# 19 s sin él. Se desactiva salvo que el modelo no lo admita.
PENSAR = False

# Generoso a propósito: un bloque grande en una GPU modesta puede tardar
# bastante, y quedarse a medias obliga a repetir toda la sesión.
TIMEOUT_SEGUNDOS = 1800

# Baja para favorecer la fidelidad a los hechos frente a la creatividad.
TEMPERATURA = 0.3

_PATRON_PENSAMIENTO = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


class ErrorOllama(RuntimeError):
    """Fallo al comunicarse con Ollama."""


def cargar_prompt(nombre: str, por_defecto: str, modo: str = MODO_POR_DEFECTO) -> str:
    """Lee una plantilla de `prompts/<modo>/`, o usa la interna si no está.

    Se lee en cada llamada a propósito: así se puede afinar el prompt y probar
    el resultado sin reiniciar la aplicación.

    Si el modo no tiene su archivo, se cae al del modo por defecto antes que a
    la plantilla interna, para que un modo nuevo a medias siga funcionando.
    """
    candidatas = [DIR_PROMPTS / modo / f"{nombre}.txt"]
    if modo != MODO_POR_DEFECTO:
        candidatas.append(DIR_PROMPTS / MODO_POR_DEFECTO / f"{nombre}.txt")

    for ruta in candidatas:
        try:
            contenido = ruta.read_text(encoding="utf-8").strip()
            if contenido:
                return contenido
        except (OSError, UnicodeDecodeError):
            continue

    return por_defecto


INSTRUCCIONES_BLOQUE_DEFECTO = """\
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

INSTRUCCIONES_CABECERA_DEFECTO = """\
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
    peticion = _peticion(prompt, modelo, url, contexto, pensar=PENSAR)

    try:
        with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
            datos = json.loads(respuesta.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detalle = exc.read().decode("utf-8", errors="replace")
        # Las versiones antiguas de Ollama no conocen el parámetro `think`.
        if exc.code == 400 and "think" in detalle.lower():
            return _generar_sin_pensar_desactivado(
                prompt, modelo, url, contexto, timeout
            )
        raise ErrorOllama(f"Ollama respondió {exc.code}: {detalle}") from exc
    except TimeoutError as exc:
        raise ErrorOllama(
            f"Ollama tardó más de {timeout // 60} minutos en responder. "
            "El modelo puede ser demasiado grande para esta GPU, o el bloque "
            "demasiado largo: prueba a bajar 'contexto_resumen' en config.ini "
            "o a usar un modelo más pequeño."
        ) from exc
    except (urllib.error.URLError, OSError) as exc:
        # urllib envuelve el timeout dentro de URLError, así que hay que
        # distinguirlo aquí para no mandar al usuario a comprobar si Ollama
        # está arrancado cuando el problema es que va lento.
        if isinstance(getattr(exc, "reason", None), TimeoutError) or "timed out" in str(
            exc
        ):
            raise ErrorOllama(
                f"Ollama tardó más de {timeout // 60} minutos en responder. "
                "Prueba a bajar 'contexto_resumen' en config.ini o a usar un "
                "modelo más pequeño."
            ) from exc
        raise ErrorOllama(
            f"No se pudo contactar con Ollama en {url}. ¿Está en marcha? ({exc})"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ErrorOllama(f"Respuesta ilegible de Ollama: {exc}") from exc

    return _limpiar(datos.get("response", ""))


def _peticion(
    prompt: str, modelo: str, url: str, contexto: int, pensar: bool | None
) -> urllib.request.Request:
    """Construye la petición a Ollama."""
    cuerpo: dict = {
        "model": modelo,
        "prompt": prompt,
        "stream": False,
        "options": {
            "num_ctx": contexto,
            "temperature": TEMPERATURA,
        },
    }
    if pensar is not None:
        cuerpo["think"] = pensar

    return urllib.request.Request(
        url + "/api/generate",
        data=json.dumps(cuerpo).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )


def _generar_sin_pensar_desactivado(
    prompt: str, modelo: str, url: str, contexto: int, timeout: int
) -> str:
    """Reintenta sin el parámetro `think`, para Ollama o modelos que no lo admiten."""
    peticion = _peticion(prompt, modelo, url, contexto, pensar=None)
    try:
        with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
            datos = json.loads(respuesta.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        raise ErrorOllama(f"Ollama falló al generar: {exc}") from exc
    return _limpiar(datos.get("response", ""))


def _prompt_bloque(
    bloque: Bloque, contexto_previo: str | None, modo: str = MODO_POR_DEFECTO
) -> str:
    partes = [cargar_prompt("cronologia", INSTRUCCIONES_BLOQUE_DEFECTO, modo)]

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
    contexto_modelo: int = CONTEXTO_OLLAMA,
    modo: str = MODO_POR_DEFECTO,
    avisar: Callable[[str], None] | None = None,
) -> list[str]:
    """Fase 1: genera el tramo de cronología de cada bloque, en cadena."""
    tramos: list[str] = []
    anterior: str | None = None

    for bloque in bloques:
        if avisar:
            avisar(f"Resumiendo tramo {bloque.indice} de {bloque.total}...")

        tramo = generar(
            _prompt_bloque(bloque, anterior, modo),
            modelo=modelo,
            url=url,
            contexto=contexto_modelo,
        )
        tramos.append(tramo)
        anterior = _resumir_contexto(tramo)

    return tramos


def _cronica_para_cabecera(tramos: list[str], contexto: int) -> str:
    """Junta los tramos para la cabecera sin desbordar el contexto del modelo.

    La cabecera recibe la crónica entera, así que en una sesión larga puede no
    caber. Cuando pasa, se recorta cada tramo **por igual** en lugar de cortar
    por el final: así la sinopsis sigue cubriendo toda la sesión y no solo su
    principio.
    """
    cronica = "\n\n".join(tramos)

    # Sitio para las instrucciones y para la cabecera que se va a generar.
    presupuesto_caracteres = int(contexto * CARACTERES_POR_TOKEN * 0.5)

    if len(cronica) <= presupuesto_caracteres or not tramos:
        return cronica

    por_tramo = max(200, presupuesto_caracteres // len(tramos))
    recortados = [
        tramo if len(tramo) <= por_tramo else tramo[:por_tramo] + "\n[...]"
        for tramo in tramos
    ]
    return "\n\n".join(recortados)


def generar_cabecera(
    tramos: list[str],
    modelo: str = "qwen3:8b",
    url: str = URL_OLLAMA,
    contexto: int = CONTEXTO_OLLAMA,
    modo: str = MODO_POR_DEFECTO,
    avisar: Callable[[str], None] | None = None,
) -> str:
    """Fase 2: sinopsis, personajes y lugares, a partir de los tramos escritos."""
    if avisar:
        avisar("Redactando sinopsis y elenco...")

    cronica = _cronica_para_cabecera(tramos, contexto)
    prompt = (
        f"{cargar_prompt('cabecera', INSTRUCCIONES_CABECERA_DEFECTO, modo)}\n"
        "--- CRÓNICA DE LA SESIÓN ---\n"
        f"{cronica}\n"
        "--- FIN DE LA CRÓNICA ---\n"
    )
    return generar(prompt, modelo=modelo, url=url, contexto=contexto)


def _reloj(segundos: float) -> str:
    """Segundos -> 'h:mm' o 'mm:ss' si la sesión dura menos de una hora."""
    total = int(segundos)
    horas, resto = divmod(total, 3600)
    minutos, segs = divmod(resto, 60)
    if horas:
        return f"{horas}:{minutos:02d}:{segs:02d}"
    return f"{minutos}:{segs:02d}"


def componer_documento(
    titulo: str,
    cabecera: str,
    tramos: list[str],
    metadatos: dict[str, str] | None = None,
    bloques: list[Bloque] | None = None,
) -> str:
    """Monta el documento final en Markdown.

    Cada tramo se precede de su franja horaria. Sirve para dos cosas: permite
    saltar directamente al punto de la grabación donde se dijo algo, y desambigua
    los encabezados repetidos —cada bloque se resume por separado, así que si la
    conversación vuelve a un tema, aparecen secciones con títulos parecidos.
    """
    partes = [f"# {titulo}", ""]

    if metadatos:
        for clave, valor in metadatos.items():
            partes.append(f"**{clave}:** {valor}  ")
        partes.append("")

    if cabecera:
        partes.extend([cabecera, ""])

    partes.extend(["---", "", "## Cronología", ""])

    if bloques and len(bloques) == len(tramos):
        for bloque, tramo in zip(bloques, tramos):
            franja = f"{_reloj(bloque.inicio)} – {_reloj(bloque.fin)}"
            partes.append(f"*Grabación {franja}*")
            partes.append("")
            partes.append(tramo)
            partes.append("")
    else:
        partes.append("\n\n".join(tramos))

    return "\n".join(partes).strip() + "\n"


def resumir(
    bloques: list[Bloque],
    titulo: str,
    metadatos: dict[str, str] | None = None,
    modelo: str = "qwen3:8b",
    url: str = URL_OLLAMA,
    contexto: int = CONTEXTO_OLLAMA,
    modo: str = MODO_POR_DEFECTO,
    avisar: Callable[[str], None] | None = None,
) -> ResultadoResumen:
    """Ejecuta las dos fases y devuelve el documento final."""
    if not bloques:
        raise ErrorOllama("No hay nada que resumir: la transcripción está vacía.")

    tramos = resumir_bloques(
        bloques,
        modelo=modelo,
        url=url,
        contexto_modelo=contexto,
        modo=modo,
        avisar=avisar,
    )

    # Con un solo tramo la cabecera aporta poco, pero mantiene el formato
    # uniforme entre sesiones cortas y largas.
    cabecera = generar_cabecera(
        tramos, modelo=modelo, url=url, contexto=contexto, modo=modo, avisar=avisar
    )

    documento = componer_documento(titulo, cabecera, tramos, metadatos, bloques)
    return ResultadoResumen(documento=documento, tramos=tramos)
