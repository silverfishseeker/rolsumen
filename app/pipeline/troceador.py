"""Troceado de la línea de tiempo en bloques que quepan en el modelo.

Estrategia acordada:
  1. Número de bloques adaptativo, calculado por sesión y repartido de forma
     equitativa (para que el último bloque no quede en dos minutos sueltos).
  2. Corte en pausas naturales: se busca el silencio más cercano al punto de
     corte ideal, en vez de partir una intervención por la mitad.
  3. Sin solape: la continuidad la aporta el contexto en cadena del resumidor.
"""

from __future__ import annotations

import math

from .tipos import Bloque, Segmento

# Estimación de tokens por carácter para texto en español con tokenizadores
# tipo Qwen/GPT. Es conservadora a propósito (sobreestima), porque pasarse del
# contexto es mucho peor que hacer un bloque de más.
CARACTERES_POR_TOKEN = 3.0

# Presupuesto de transcripción por bloque. Es solo una parte del contexto del
# modelo: en la misma ventana entran además las instrucciones (~400 tokens), el
# resumen del bloque anterior encadenado (~500) y, sobre todo, la respuesta que
# se va a generar (~1500). Con un contexto de 8192 hay que dejarles sitio.
PRESUPUESTO_TOKENS_POR_BLOQUE = 4000

# Cuántos segmentos alrededor del corte ideal se exploran buscando una pausa.
VENTANA_BUSQUEDA_PAUSA = 12


def estimar_tokens(texto: str) -> int:
    """Estimación rápida del número de tokens de un texto."""
    return math.ceil(len(texto) / CARACTERES_POR_TOKEN)


def _tokens_por_segmento(segmentos: list[Segmento]) -> list[int]:
    return [estimar_tokens(seg.linea()) for seg in segmentos]


def calcular_numero_bloques(
    segmentos: list[Segmento],
    presupuesto: int = PRESUPUESTO_TOKENS_POR_BLOQUE,
) -> int:
    """Número mínimo de bloques para que la transcripción quepa."""
    if not segmentos:
        return 0
    total = sum(_tokens_por_segmento(segmentos))
    return max(1, math.ceil(total / presupuesto))


def _mejor_corte(
    segmentos: list[Segmento], indice_ideal: int, ventana: int, minimo: int
) -> int:
    """Busca la pausa más larga cerca del corte ideal.

    Devuelve el índice del segmento que abrirá el siguiente bloque.
    """
    inicio = max(minimo, indice_ideal - ventana)
    fin = min(len(segmentos) - 1, indice_ideal + ventana)

    if inicio > fin:
        return max(minimo, min(indice_ideal, len(segmentos) - 1))

    mejor_indice = indice_ideal
    mejor_hueco = -1.0

    for i in range(inicio, fin + 1):
        if i == 0:
            continue
        hueco = segmentos[i].inicio - segmentos[i - 1].fin
        # A igualdad de hueco, preferimos el corte más cercano al ideal.
        if hueco > mejor_hueco or (
            hueco == mejor_hueco
            and abs(i - indice_ideal) < abs(mejor_indice - indice_ideal)
        ):
            mejor_hueco = hueco
            mejor_indice = i

    return mejor_indice


def trocear(
    segmentos: list[Segmento],
    presupuesto: int = PRESUPUESTO_TOKENS_POR_BLOQUE,
    ventana: int = VENTANA_BUSQUEDA_PAUSA,
) -> list[Bloque]:
    """Divide la línea de tiempo en bloques equitativos cortados en pausas."""
    if not segmentos:
        return []

    numero = calcular_numero_bloques(segmentos, presupuesto)
    if numero <= 1:
        return [Bloque(indice=1, total=1, segmentos=list(segmentos))]

    # No podemos hacer más bloques que segmentos hay.
    numero = min(numero, len(segmentos))

    tokens = _tokens_por_segmento(segmentos)
    total_tokens = sum(tokens)
    objetivo = total_tokens / numero

    # Tokens acumulados hasta cada segmento (inclusive).
    acumulado: list[int] = []
    suma = 0
    for t in tokens:
        suma += t
        acumulado.append(suma)

    cortes: list[int] = []
    for i in range(1, numero):
        objetivo_tokens = objetivo * i

        # Primer segmento que supera el objetivo de tokens.
        indice_ideal = next(
            (idx for idx, acc in enumerate(acumulado) if acc >= objetivo_tokens),
            len(segmentos) - 1,
        )

        minimo = (cortes[-1] + 1) if cortes else 1
        corte = _mejor_corte(segmentos, indice_ideal, ventana, minimo)

        # Garantizar cortes estrictamente crecientes y dejar sitio a los que faltan.
        maximo = len(segmentos) - (numero - i)
        corte = max(minimo, min(corte, maximo))

        if cortes and corte <= cortes[-1]:
            corte = cortes[-1] + 1
        cortes.append(corte)

    limites = [0, *cortes, len(segmentos)]
    bloques: list[Bloque] = []
    for i in range(len(limites) - 1):
        trozo = segmentos[limites[i] : limites[i + 1]]
        if trozo:
            bloques.append(
                Bloque(indice=len(bloques) + 1, total=numero, segmentos=trozo)
            )

    # Renumerar por si algún trozo quedó vacío y se descartó.
    total_real = len(bloques)
    return [
        Bloque(indice=i + 1, total=total_real, segmentos=b.segmentos)
        for i, b in enumerate(bloques)
    ]
