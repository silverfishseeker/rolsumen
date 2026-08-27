"""Combinación de las pistas en una única línea de tiempo.

Cada jugador tiene su pista, así que basta con ordenar todos los segmentos por
marca de tiempo para reconstruir la conversación. Los solapamientos no son
problema: cada pista contiene una sola voz, hablen a la vez o no.
"""

from __future__ import annotations

import dataclasses

from .tipos import Segmento

# Whisper trocea en fragmentos de pocos segundos. Unir los seguidos del mismo
# hablante da un diálogo más legible y ahorra tokens: en una sesión real, 1394
# segmentos quedaron en 572 intervenciones.
HUECO_MAXIMO_FUSION = 2.0


def aplicar_personajes(
    segmentos: list[Segmento], mapa_personajes: dict[str, str]
) -> list[Segmento]:
    """Sustituye el identificador de la pista por el nombre del personaje."""
    if not mapa_personajes:
        return segmentos

    return [
        dataclasses.replace(seg, hablante=personaje)
        if (personaje := mapa_personajes.get(seg.hablante.lower()))
        else seg
        for seg in segmentos
    ]


def fusionar_consecutivos(
    segmentos: list[Segmento], hueco_maximo: float = HUECO_MAXIMO_FUSION
) -> list[Segmento]:
    """Une intervenciones seguidas del mismo hablante. Asume orden temporal."""
    if not segmentos:
        return []

    fusionados: list[Segmento] = []
    actual = segmentos[0]

    for siguiente in segmentos[1:]:
        if (
            siguiente.hablante == actual.hablante
            and siguiente.inicio - actual.fin <= hueco_maximo
        ):
            actual = Segmento(
                inicio=actual.inicio,
                fin=max(actual.fin, siguiente.fin),
                texto=f"{actual.texto} {siguiente.texto}".strip(),
                hablante=actual.hablante,
            )
        else:
            fusionados.append(actual)
            actual = siguiente

    fusionados.append(actual)
    return fusionados


def combinar(
    pistas: list[list[Segmento]],
    mapa_personajes: dict[str, str] | None = None,
    fusionar: bool = True,
) -> list[Segmento]:
    """Entrelaza las pistas de todos los jugadores por marca de tiempo."""
    todos = [seg for pista in pistas for seg in pista]

    if mapa_personajes:
        todos = aplicar_personajes(todos, mapa_personajes)

    # A igualdad de instante, por hablante: así el orden es determinista.
    todos.sort(key=lambda s: (s.inicio, s.hablante))

    return fusionar_consecutivos(todos) if fusionar else todos


def a_texto(segmentos: list[Segmento]) -> str:
    return "\n".join(seg.linea() for seg in segmentos)
