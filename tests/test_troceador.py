"""Tests del troceado adaptativo con corte en pausas naturales."""

from app.pipeline.tipos import Segmento
from app.pipeline.troceador import (
    calcular_numero_bloques,
    estimar_tokens,
    trocear,
)


def seg(inicio, fin, texto="palabra " * 10, hablante="ana"):
    return Segmento(inicio=inicio, fin=fin, texto=texto.strip(), hablante=hablante)


def linea_temporal(n, texto="palabra " * 10, hueco=1.0, duracion=5.0):
    """n segmentos consecutivos separados por un hueco constante."""
    segmentos = []
    t = 0.0
    for _ in range(n):
        segmentos.append(seg(t, t + duracion, texto))
        t += duracion + hueco
    return segmentos


def test_estimacion_de_tokens_crece_con_el_texto():
    assert estimar_tokens("corto") < estimar_tokens("un texto bastante más largo")


def test_transcripcion_corta_cabe_en_un_solo_bloque():
    segmentos = linea_temporal(5)

    bloques = trocear(segmentos, presupuesto=10_000)

    assert len(bloques) == 1
    assert bloques[0].total == 1
    assert len(bloques[0].segmentos) == 5


def test_numero_de_bloques_se_adapta_al_tamano():
    cortos = linea_temporal(10)
    largos = linea_temporal(200)

    assert calcular_numero_bloques(cortos, presupuesto=500) < calcular_numero_bloques(
        largos, presupuesto=500
    )


def test_todos_los_segmentos_acaban_en_algun_bloque():
    segmentos = linea_temporal(100)

    bloques = trocear(segmentos, presupuesto=500)

    recuperados = [s for b in bloques for s in b.segmentos]
    assert recuperados == segmentos


def test_no_se_repite_ningun_segmento_entre_bloques():
    # Confirmación explícita de la decisión de diseño: sin solape.
    segmentos = linea_temporal(100)

    bloques = trocear(segmentos, presupuesto=500)

    inicios = [s.inicio for b in bloques for s in b.segmentos]
    assert len(inicios) == len(set(inicios))


def test_los_bloques_van_numerados_y_conocen_el_total():
    segmentos = linea_temporal(100)

    bloques = trocear(segmentos, presupuesto=500)

    assert [b.indice for b in bloques] == list(range(1, len(bloques) + 1))
    assert all(b.total == len(bloques) for b in bloques)


def test_reparto_equitativo_sin_bloque_residual_diminuto():
    segmentos = linea_temporal(100)

    bloques = trocear(segmentos, presupuesto=500)
    tamanos = [len(b.segmentos) for b in bloques]

    # Ningún bloque debe ser ridículamente pequeño comparado con la media.
    media = sum(tamanos) / len(tamanos)
    assert min(tamanos) > media * 0.4


def test_corta_en_la_pausa_mas_larga_cercana():
    # Huecos de 1s salvo un silencio de 30s a mitad: el corte debe caer ahí.
    segmentos = []
    t = 0.0
    for i in range(40):
        segmentos.append(seg(t, t + 5.0))
        t += 5.0 + (30.0 if i == 19 else 1.0)

    bloques = trocear(segmentos, presupuesto=sum(
        estimar_tokens(s.linea()) for s in segmentos
    ) // 2 + 1)

    assert len(bloques) == 2
    # El segundo bloque debe empezar justo después del silencio largo.
    assert bloques[1].segmentos[0].inicio == segmentos[20].inicio


def test_no_genera_mas_bloques_que_segmentos():
    segmentos = linea_temporal(3)

    bloques = trocear(segmentos, presupuesto=1)

    assert len(bloques) <= 3
    assert all(b.segmentos for b in bloques)


def test_lista_vacia_devuelve_cero_bloques():
    assert trocear([]) == []
    assert calcular_numero_bloques([]) == 0


def test_bloque_conoce_su_rango_temporal():
    segmentos = linea_temporal(10)

    bloque = trocear(segmentos, presupuesto=10_000)[0]

    assert bloque.inicio == segmentos[0].inicio
    assert bloque.fin == segmentos[-1].fin


def test_texto_del_bloque_incluye_todas_sus_lineas():
    segmentos = linea_temporal(4)

    bloque = trocear(segmentos, presupuesto=10_000)[0]

    assert bloque.texto().count("\n") == 3
