"""Tests del combinado de pistas en una línea de tiempo única."""

from app.pipeline.combinador import (
    a_texto,
    aplicar_personajes,
    combinar,
    fusionar_consecutivos,
)
from app.pipeline.tipos import Segmento


def seg(inicio, fin, texto, hablante="ana"):
    return Segmento(inicio=inicio, fin=fin, texto=texto, hablante=hablante)


def test_ordena_por_tiempo_entre_pistas():
    pista_ana = [seg(10.0, 12.0, "Segundo", "ana")]
    pista_bea = [seg(0.0, 5.0, "Primero", "bea")]

    resultado = combinar([pista_ana, pista_bea])

    assert [s.texto for s in resultado] == ["Primero", "Segundo"]


def test_fusiona_intervenciones_seguidas_del_mismo_hablante():
    segmentos = [
        seg(0.0, 3.0, "Abro la puerta", "ana"),
        seg(3.5, 6.0, "y entro con cuidado", "ana"),
    ]

    resultado = fusionar_consecutivos(segmentos)

    assert len(resultado) == 1
    assert resultado[0].texto == "Abro la puerta y entro con cuidado"
    assert resultado[0].inicio == 0.0
    assert resultado[0].fin == 6.0


def test_no_fusiona_si_el_hueco_es_grande():
    segmentos = [
        seg(0.0, 3.0, "Abro la puerta", "ana"),
        seg(30.0, 33.0, "Sigo andando", "ana"),
    ]

    assert len(fusionar_consecutivos(segmentos)) == 2


def test_no_fusiona_hablantes_distintos():
    segmentos = [
        seg(0.0, 3.0, "¿Vamos?", "ana"),
        seg(3.1, 5.0, "Vamos", "bea"),
    ]

    assert len(fusionar_consecutivos(segmentos)) == 2


def test_intercala_hablantes_que_se_pisan():
    # Multipista: los solapamientos no son un problema, cada uno en su pista.
    pista_ana = [seg(0.0, 10.0, "Estoy hablando largo", "ana")]
    pista_bea = [seg(5.0, 7.0, "Te interrumpo", "bea")]

    resultado = combinar([pista_ana, pista_bea])

    assert [s.hablante for s in resultado] == ["ana", "bea"]


def test_aplica_nombres_de_personaje():
    segmentos = [seg(0.0, 1.0, "Hola", "silverfishlord")]

    resultado = aplicar_personajes(segmentos, {"silverfishlord": "Kaelen"})

    assert resultado[0].hablante == "Kaelen"


def test_usa_el_nick_si_no_hay_mapeo():
    segmentos = [seg(0.0, 1.0, "Hola", "desconocido")]

    resultado = aplicar_personajes(segmentos, {"otro": "Kaelen"})

    assert resultado[0].hablante == "desconocido"


def test_formato_de_linea_incluye_marca_de_tiempo():
    linea = seg(3661.0, 3665.0, "Llegamos", "Kaelen").linea()

    assert linea == "[1:01:01] Kaelen: Llegamos"


def test_texto_completo_una_linea_por_intervencion():
    resultado = combinar([[seg(0.0, 1.0, "Uno", "ana"), seg(20.0, 21.0, "Dos", "ana")]])

    assert a_texto(resultado).count("\n") == 1


def test_lista_vacia_no_rompe():
    assert combinar([]) == []
    assert fusionar_consecutivos([]) == []
