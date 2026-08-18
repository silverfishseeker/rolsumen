"""Tests de las marcas de tiempo por tramo en el documento final.

Cada bloque se resume por separado, así que si la conversación vuelve a un
tema aparecen secciones con títulos casi idénticos ("Estrategia y movimientos",
"Estrategia y movilidad"...). La franja horaria las desambigua y además permite
saltar al punto exacto de la grabación.
"""

from app.pipeline.resumidor import _reloj, componer_documento
from app.pipeline.tipos import Bloque, Segmento


def bloque(indice, inicio, fin, total=2):
    return Bloque(
        indice=indice,
        total=total,
        segmentos=[
            Segmento(inicio=inicio, fin=fin, texto="algo", hablante="ana"),
        ],
    )


def test_reloj_en_minutos_para_sesiones_cortas():
    assert _reloj(0) == "0:00"
    assert _reloj(125) == "2:05"


def test_reloj_con_horas_para_sesiones_largas():
    assert _reloj(3661) == "1:01:01"
    assert _reloj(6300) == "1:45:00"


def test_el_documento_marca_la_franja_de_cada_tramo():
    bloques = [bloque(1, 0, 780), bloque(2, 780, 1560)]
    doc = componer_documento("S", "", ["tramo uno", "tramo dos"], bloques=bloques)

    assert "*Grabación 0:00 – 13:00*" in doc
    assert "*Grabación 13:00 – 26:00*" in doc


def test_cada_franja_precede_a_su_tramo():
    bloques = [bloque(1, 0, 60), bloque(2, 60, 120)]
    doc = componer_documento("S", "", ["PRIMERO", "SEGUNDO"], bloques=bloques)

    assert doc.index("0:00 – 1:00") < doc.index("PRIMERO")
    assert doc.index("PRIMERO") < doc.index("1:00 – 2:00")
    assert doc.index("1:00 – 2:00") < doc.index("SEGUNDO")


def test_sin_bloques_el_documento_sigue_montandose():
    # Compatibilidad: si no se pasan bloques, se concatenan los tramos sin más.
    doc = componer_documento("S", "", ["uno", "dos"])

    assert "uno" in doc and "dos" in doc
    assert "Grabación" not in doc


def test_si_no_cuadran_bloques_y_tramos_no_se_inventan_franjas():
    doc = componer_documento("S", "", ["uno", "dos"], bloques=[bloque(1, 0, 60)])

    assert "Grabación" not in doc
    assert "uno" in doc and "dos" in doc


def test_las_franjas_no_rompen_los_encabezados_del_modelo():
    # Las secciones que genera el modelo son '###'; la franja va en cursiva
    # para no competir con esa jerarquía.
    bloques = [bloque(1, 0, 60)]
    doc = componer_documento("S", "", ["### Un tema\n- algo"], bloques=bloques)

    assert "### Un tema" in doc
    assert "*Grabación" in doc
