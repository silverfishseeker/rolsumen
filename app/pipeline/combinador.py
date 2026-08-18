"""Combinación de las pistas individuales en una única línea de tiempo.

Cada jugador tiene su propia pista, así que basta con ordenar todos los
segmentos por marca de tiempo para reconstruir la conversación.
"""

from __future__ import annotations

from .tipos import Segmento

# Si el mismo hablante encadena segmentos con menos de este hueco entre ellos,
# se fusionan en una sola intervención. Whisper trocea en fragmentos de pocos
# segundos; fusionarlos produce un diálogo más legible y ahorra tokens.
HUECO_MAXIMO_FUSION = 2.0


def aplicar_personajes(
    segmentos: list[Segmento], mapa_personajes: dict[str, str]
) -> list[Segmento]:
    """Sustituye el nick de Discord por el nombre del personaje, si lo hay."""
    if not mapa_personajes:
        return segmentos

    resultado = []
    for seg in segmentos:
        personaje = mapa_personajes.get(seg.hablante.lower())
        if personaje:
            resultado.append(
                Segmento(
                    inicio=seg.inicio,
                    fin=seg.fin,
                    texto=seg.texto,
                    hablante=personaje,
                )
            )
        else:
            resultado.append(seg)
    return resultado


def fusionar_consecutivos(
    segmentos: list[Segmento], hueco_maximo: float = HUECO_MAXIMO_FUSION
) -> list[Segmento]:
    """Une segmentos seguidos del mismo hablante separados por un hueco pequeño.

    Se asume que la lista ya viene ordenada por tiempo de inicio.
    """
    if not segmentos:
        return []

    fusionados: list[Segmento] = []
    actual = segmentos[0]

    for siguiente in segmentos[1:]:
        mismo_hablante = siguiente.hablante == actual.hablante
        hueco = siguiente.inicio - actual.fin

        if mismo_hablante and hueco <= hueco_maximo:
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
    """Combina las pistas de todos los jugadores en una línea de tiempo única.

    Args:
        pistas: una lista de segmentos por cada jugador.
        mapa_personajes: nick de Discord -> nombre del personaje.
        fusionar: si unir intervenciones consecutivas del mismo hablante.
    """
    todos: list[Segmento] = []
    for pista in pistas:
        todos.extend(pista)

    if mapa_personajes:
        todos = aplicar_personajes(todos, mapa_personajes)

    # Ordenar por inicio; a igualdad, por hablante para que sea determinista.
    todos.sort(key=lambda s: (s.inicio, s.hablante))

    if fusionar:
        todos = fusionar_consecutivos(todos)

    return todos


def a_texto(segmentos: list[Segmento]) -> str:
    """Renderiza la línea de tiempo completa como texto plano."""
    return "\n".join(seg.linea() for seg in segmentos)
