"""Generación del documento a partir de la transcripción, usando Ollama.

El resultado no es un relato sino un acta consultable, y se construye en dos
fases:

  1. Cada bloque produce su tramo, encadenando el resumen del anterior como
     contexto para que la narración siga el hilo.
  2. Se redacta solo la cabecera (sinopsis y listas) a partir de los tramos ya
     escritos, y se concatena todo.

La fase 2 no reescribe los tramos a propósito: en un documento para consultar
hechos, perder detalle es peor que un texto algo más largo.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable

from ..config import CONTEXTO_POR_DEFECTO, DIR_PROMPTS, MODO_POR_DEFECTO
from .tipos import Bloque
from .troceador import CARACTERES_POR_TOKEN

URL_OLLAMA = "http://localhost:11434"

# El valor y su porqué están en config; aquí solo se reexporta el nombre que
# usan las funciones de este módulo.
CONTEXTO_OLLAMA = CONTEXTO_POR_DEFECTO

MODELO_POR_DEFECTO = "qwen3:8b"

TIMEOUT_SEGUNDOS = 1800

# Los modelos de razonamiento generan un bloque <think> que aquí se descarta,
# así que producirlo es tiempo tirado: medido, >300 s con él y 19 s sin él.
PENSAR = False

# Baja para favorecer la fidelidad a los hechos frente a la creatividad.
TEMPERATURA = 0.3

_PATRON_PENSAMIENTO = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


class ErrorOllama(RuntimeError):
    """Fallo al comunicarse con Ollama."""


@dataclass
class ResultadoResumen:
    documento: str
    tramos: list[str]


def cargar_prompt(nombre: str, modo: str = MODO_POR_DEFECTO) -> str:
    """Lee una plantilla de `prompts/<modo>/`.

    Se lee en cada llamada a propósito: permite afinar un prompt y volver a
    probar sin reiniciar. Un modo al que le falte un archivo usa el del modo
    por defecto, para que uno a medio hacer siga funcionando.
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

    raise FileNotFoundError(
        f"Falta el prompt '{nombre}' del modo '{modo}'. "
        f"Debería estar en {candidatas[0]}."
    )


def _limpiar(texto: str) -> str:
    return _PATRON_PENSAMIENTO.sub("", texto).strip()


def ollama_disponible(url: str = URL_OLLAMA, timeout: float = 3.0) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/api/tags", timeout=timeout) as respuesta:
            return respuesta.status == 200
    except (urllib.error.URLError, OSError):
        return False


def modelos_disponibles(url: str = URL_OLLAMA, timeout: float = 5.0) -> list[str]:
    try:
        with urllib.request.urlopen(f"{url}/api/tags", timeout=timeout) as respuesta:
            datos = json.loads(respuesta.read().decode("utf-8"))
        return [m["name"] for m in datos.get("models", [])]
    except (urllib.error.URLError, OSError, json.JSONDecodeError, KeyError):
        return []


def _peticion(
    prompt: str, modelo: str, url: str, contexto: int, pensar: bool | None
) -> urllib.request.Request:
    cuerpo: dict = {
        "model": modelo,
        "prompt": prompt,
        "stream": False,
        "options": {"num_ctx": contexto, "temperature": TEMPERATURA},
    }
    if pensar is not None:
        cuerpo["think"] = pensar

    return urllib.request.Request(
        url + "/api/generate",
        data=json.dumps(cuerpo).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )


def _es_timeout(exc: Exception) -> bool:
    """urllib envuelve los timeouts dentro de URLError, hay que desenvolverlos."""
    return isinstance(exc, TimeoutError) or isinstance(
        getattr(exc, "reason", None), TimeoutError
    ) or "timed out" in str(exc)


def _pedir(peticion: urllib.request.Request, timeout: int) -> str:
    with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
        return _limpiar(json.loads(respuesta.read().decode("utf-8")).get("response", ""))


def generar(
    prompt: str,
    modelo: str = MODELO_POR_DEFECTO,
    url: str = URL_OLLAMA,
    contexto: int = CONTEXTO_OLLAMA,
    timeout: int = TIMEOUT_SEGUNDOS,
) -> str:
    try:
        return _pedir(_peticion(prompt, modelo, url, contexto, PENSAR), timeout)
    except urllib.error.HTTPError as exc:
        detalle = exc.read().decode("utf-8", errors="replace")
        if exc.code == 400 and "think" in detalle.lower():
            # Ollama o modelo antiguo que no conoce el parámetro.
            try:
                return _pedir(_peticion(prompt, modelo, url, contexto, None), timeout)
            except (urllib.error.URLError, OSError, json.JSONDecodeError) as fallo:
                raise ErrorOllama(f"Ollama falló al generar: {fallo}") from fallo
        raise ErrorOllama(f"Ollama respondió {exc.code}: {detalle}") from exc
    except (TimeoutError, urllib.error.URLError, OSError) as exc:
        if _es_timeout(exc):
            raise ErrorOllama(
                f"Ollama tardó más de {timeout // 60} minutos en responder. "
                "El modelo puede ser demasiado grande para esta GPU, o el bloque "
                "demasiado largo: prueba a bajar 'contexto_resumen' en config.ini "
                "o a usar un modelo más pequeño."
            ) from exc
        raise ErrorOllama(
            f"No se pudo contactar con Ollama en {url}. ¿Está en marcha? ({exc})"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ErrorOllama(f"Respuesta ilegible de Ollama: {exc}") from exc


def _prompt_bloque(
    bloque: Bloque, contexto_previo: str | None, modo: str = MODO_POR_DEFECTO
) -> str:
    partes = [cargar_prompt("cronologia", modo)]

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
    return tramo if len(tramo) <= limite else "..." + tramo[-limite:]


def _cronica_para_cabecera(tramos: list[str], contexto: int) -> str:
    """Junta los tramos sin desbordar el contexto.

    Cuando no caben se recorta cada uno **por igual** en vez de cortar por el
    final: así la sinopsis sigue cubriendo toda la sesión y no solo su principio.
    """
    cronica = "\n\n".join(tramos)
    presupuesto = int(contexto * CARACTERES_POR_TOKEN * 0.5)

    if len(cronica) <= presupuesto or not tramos:
        return cronica

    por_tramo = max(200, presupuesto // len(tramos))
    return "\n\n".join(
        t if len(t) <= por_tramo else t[:por_tramo] + "\n[...]" for t in tramos
    )


def resumir_bloques(
    bloques: list[Bloque],
    modelo: str = MODELO_POR_DEFECTO,
    url: str = URL_OLLAMA,
    contexto_modelo: int = CONTEXTO_OLLAMA,
    modo: str = MODO_POR_DEFECTO,
    avisar: Callable[[str], None] | None = None,
) -> list[str]:
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


def generar_cabecera(
    tramos: list[str],
    modelo: str = MODELO_POR_DEFECTO,
    url: str = URL_OLLAMA,
    contexto: int = CONTEXTO_OLLAMA,
    modo: str = MODO_POR_DEFECTO,
    avisar: Callable[[str], None] | None = None,
) -> str:
    if avisar:
        avisar("Redactando sinopsis y elenco...")

    prompt = (
        f"{cargar_prompt('cabecera', modo)}\n"
        "--- CRÓNICA DE LA SESIÓN ---\n"
        f"{_cronica_para_cabecera(tramos, contexto)}\n"
        "--- FIN DE LA CRÓNICA ---\n"
    )
    return generar(prompt, modelo=modelo, url=url, contexto=contexto)


def _reloj(segundos: float) -> str:
    horas, resto = divmod(int(segundos), 3600)
    minutos, segs = divmod(resto, 60)
    return f"{horas}:{minutos:02d}:{segs:02d}" if horas else f"{minutos}:{segs:02d}"


def componer_documento(
    titulo: str,
    cabecera: str,
    tramos: list[str],
    metadatos: dict[str, str] | None = None,
    bloques: list[Bloque] | None = None,
) -> str:
    """Monta el documento final.

    Cada tramo lleva su franja horaria: permite saltar al punto exacto de la
    grabación, y desambigua los encabezados parecidos que salen al resumir cada
    bloque por separado.
    """
    partes = [f"# {titulo}", ""]

    if metadatos:
        partes += [f"**{clave}:** {valor}  " for clave, valor in metadatos.items()]
        partes.append("")

    if cabecera:
        partes += [cabecera, ""]

    partes += ["---", "", "## Cronología", ""]

    if bloques and len(bloques) == len(tramos):
        for bloque, tramo in zip(bloques, tramos):
            franja = f"{_reloj(bloque.inicio)} – {_reloj(bloque.fin)}"
            partes += [f"*Grabación {franja}*", "", tramo, ""]
    else:
        partes.append("\n\n".join(tramos))

    return "\n".join(partes).strip() + "\n"


def resumir(
    bloques: list[Bloque],
    titulo: str,
    metadatos: dict[str, str] | None = None,
    modelo: str = MODELO_POR_DEFECTO,
    url: str = URL_OLLAMA,
    contexto: int = CONTEXTO_OLLAMA,
    modo: str = MODO_POR_DEFECTO,
    avisar: Callable[[str], None] | None = None,
) -> ResultadoResumen:
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
    cabecera = generar_cabecera(
        tramos, modelo=modelo, url=url, contexto=contexto, modo=modo, avisar=avisar
    )

    return ResultadoResumen(
        documento=componer_documento(titulo, cabecera, tramos, metadatos, bloques),
        tramos=tramos,
    )

