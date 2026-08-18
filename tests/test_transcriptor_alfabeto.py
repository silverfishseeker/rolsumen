"""Tests del descarte de texto en un alfabeto que no es el del idioma.

Caso real observado: transcribiendo una pista en español, `large-v3` devolvió
"прирostal" sobre un tramo de ruido. Como el idioma se le indica de forma
explícita, cualquier salida en otro alfabeto es una alucinación.
"""

from app.pipeline.transcriptor import _alfabeto_ajeno, filtrar_segmentos


def crudo(texto, inicio=0.0):
    return {
        "start": inicio,
        "end": inicio + 2.0,
        "text": texto,
        "no_speech_prob": 0.1,
        "avg_logprob": -0.2,
    }


def test_espanol_normal_no_se_descarta():
    assert not _alfabeto_ajeno("Abro la puerta con cuidado")


def test_espanol_con_acentos_y_enes():
    assert not _alfabeto_ajeno("El niño atravesó la cordillera más árida")


def test_cirilico_se_descarta():
    assert _alfabeto_ajeno("прирostal")


def test_texto_integramente_cirilico():
    assert _alfabeto_ajeno("привет как дела")


def test_griego_se_descarta():
    assert _alfabeto_ajeno("μῆνιν ἄειδε θεά")


def test_texto_sin_letras_no_se_descarta():
    # Números y signos solos no permiten decidir; se conservan.
    assert not _alfabeto_ajeno("42 -- 17,5")


def test_una_palabra_suelta_ajena_no_tumba_la_frase():
    # Mayoría en alfabeto latino: se conserva.
    assert not _alfabeto_ajeno("el hechizo se llamaba привет segun el libro")


def test_se_filtra_dentro_del_pipeline():
    crudos = [crudo("Abro la puerta", 0), crudo("прирostal", 10)]

    resultado = filtrar_segmentos(crudos, duracion=60.0, hablante="ana")

    assert [s.texto for s in resultado] == ["Abro la puerta"]
