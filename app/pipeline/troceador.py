"""Troceado de la línea de tiempo en bloques que quepan en el modelo.

Tres decisiones, todas por la misma razón —que la crónica salga continua y sin
huecos raros—:

  1. El número de bloques se calcula por sesión y se reparte equitativamente,
     para que el último no quede en dos minutos sueltos.
  2. Se corta en el silencio más cercano al punto ideal, no a mitad de frase.
  3. Sin solape: la continuidad la aporta el contexto encadenado del resumidor,
     y solapar duplicaría hechos en el documento final.
"""

from __future__ import annotations

import math

from ..config import TOKENS_POR_BLOQUE_POR_DEFECTO
from .tipos import Bloque, Segmento

# Estimación para español con tokenizadores tipo Qwen. Conservadora a propósito:
# pasarse del contexto es mucho peor que hacer un bloque de más.
CARACTERES_POR_TOKEN = 3.0

# En la ventana del modelo entran además las instrucciones (~400 tokens), el
# resumen encadenado (~500) y la respuesta a generar (~1500).
PRESUPUESTO_TOKENS_POR_BLOQUE = TOKENS_POR_BLOQUE_POR_DEFECTO

# Cuántos segmentos alrededor del corte ideal se exploran buscando una pausa.
VENTANA_BUSQUEDA_PAUSA = 12


def estimar_tokens(texto: str) -> int:
    return math.ceil(len(texto) / CARACTERES_POR_TOKEN)


def _tokens_por_segmento(segmentos: list[Segmento]) -> list[int]:
    return [estimar_tokens(seg.linea()) for seg in segmentos]


def calcular_numero_bloques(
    segmentos: list[Segmento], presupuesto: int = PRESUPUESTO_TOKENS_POR_BLOQUE
) -> int:
    if not segmentos:
        return 0
    return max(1, math.ceil(sum(_tokens_por_segmento(segmentos)) / presupuesto))


def _mejor_corte(
    segmentos: list[Segmento], indice_ideal: int, ventana: int, minimo: int
) -> int:
    """Índice del segmento que abrirá el bloque siguiente: la pausa más larga
    cerca del corte ideal, y a igualdad de pausa la más cercana a él."""
    inicio = max(minimo, indice_ideal - ventana, 1)
    fin = min(len(segmentos) - 1, indice_ideal + ventana)

    if inicio > fin:
        return max(minimo, min(indice_ideal, len(segmentos) - 1))

    def prioridad(i: int) -> tuple[float, int]:
        hueco = segmentos[i].inicio - segmentos[i - 1].fin
        return (hueco, -abs(i - indice_ideal))

    return max(range(inicio, fin + 1), key=prioridad)


def trocear(
    segmentos: list[Segmento],
    presupuesto: int = PRESUPUESTO_TOKENS_POR_BLOQUE,
    ventana: int = VENTANA_BUSQUEDA_PAUSA,
) -> list[Bloque]:
    if not segmentos:
        return []

    numero = calcular_numero_bloques(segmentos, presupuesto)
    if numero <= 1:
        return [Bloque(indice=1, total=1, segmentos=list(segmentos))]

    numero = min(numero, len(segmentos))  # no hay más bloques que segmentos

    tokens = _tokens_por_segmento(segmentos)
    objetivo = sum(tokens) / numero

    acumulado: list[int] = []
    suma = 0
    for t in tokens:
        suma += t
        acumulado.append(suma)

    cortes: list[int] = []
    for i in range(1, numero):
        indice_ideal = next(
            (idx for idx, acc in enumerate(acumulado) if acc >= objetivo * i),
            len(segmentos) - 1,
        )
        minimo = cortes[-1] + 1 if cortes else 1
        # El máximo deja un segmento como mínimo para cada bloque que falta.
        maximo = len(segmentos) - (numero - i)
        cortes.append(
            max(minimo, min(_mejor_corte(segmentos, indice_ideal, ventana, minimo), maximo))
        )

    limites = [0, *cortes, len(segmentos)]
    trozos = [
        segmentos[limites[i] : limites[i + 1]] for i in range(len(limites) - 1)
    ]
    trozos = [t for t in trozos if t]

    return [
        Bloque(indice=i + 1, total=len(trozos), segmentos=trozo)
        for i, trozo in enumerate(trozos)
    ]
