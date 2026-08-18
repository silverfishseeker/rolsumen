"""Tests del ajuste del contenido al contexto del modelo.

Motivo: con un contexto de 16384, qwen3:8b no cabía en una GPU de 8 GB y
Ollama descargaba un 20% a la CPU, hundiendo la velocidad. Medido: 4096 y 8192
van al 100% en GPU; 12288 y 16384 no.
"""

from app.pipeline import resumidor, troceador
from app.pipeline.resumidor import _cronica_para_cabecera


def test_el_contexto_por_defecto_cabe_en_una_gpu_de_8gb():
    assert resumidor.CONTEXTO_OLLAMA <= 8192


def test_el_bloque_deja_sitio_a_instrucciones_y_respuesta():
    # El bloque es solo una parte de la ventana: también entran las
    # instrucciones, el contexto encadenado y la respuesta generada.
    assert troceador.PRESUPUESTO_TOKENS_POR_BLOQUE < resumidor.CONTEXTO_OLLAMA / 1.5


def test_una_cronica_corta_no_se_recorta():
    tramos = ["uno", "dos", "tres"]

    assert _cronica_para_cabecera(tramos, 8192) == "uno\n\ndos\n\ntres"


def test_una_cronica_larga_se_recorta():
    tramos = ["x" * 20000 for _ in range(4)]

    resultado = _cronica_para_cabecera(tramos, 8192)

    assert len(resultado) < len("\n\n".join(tramos))


def test_el_recorte_reparte_entre_todos_los_tramos():
    # Cortar por el final dejaría la sinopsis cubriendo solo el principio de
    # la sesión; hay que conservar algo de cada tramo.
    tramos = [f"TRAMO{i} " + "x" * 20000 for i in range(4)]

    resultado = _cronica_para_cabecera(tramos, 8192)

    for i in range(4):
        assert f"TRAMO{i}" in resultado


def test_el_recorte_se_marca_visiblemente():
    tramos = ["x" * 20000 for _ in range(3)]

    assert "[...]" in _cronica_para_cabecera(tramos, 8192)


def test_muchos_tramos_conservan_un_minimo_cada_uno():
    tramos = [f"T{i} " + "x" * 5000 for i in range(50)]

    resultado = _cronica_para_cabecera(tramos, 4096)

    # Ninguno debe quedar reducido a nada.
    for i in range(50):
        assert f"T{i}" in resultado


def test_sin_tramos_no_revienta():
    assert _cronica_para_cabecera([], 8192) == ""


def test_un_contexto_mayor_permite_mas_cronica():
    tramos = ["x" * 20000 for _ in range(4)]

    corto = _cronica_para_cabecera(tramos, 4096)
    largo = _cronica_para_cabecera(tramos, 16384)

    assert len(largo) > len(corto)
