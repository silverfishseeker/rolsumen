"""Tests del descarte de tramos sin voz.

Motivado por lo observado en la prueba de extremo a extremo: sobre audio casi
mudo, `large-v3` produce muletillas inventadas ("Gracias.") que ninguna lista
de frases conocidas puede cubrir. La señal fiable es la que da el propio
Whisper en cada segmento.
"""

from app.pipeline.transcriptor import (
    UMBRAL_CONFIANZA,
    UMBRAL_SIN_VOZ,
    _es_silencio,
    filtrar_segmentos,
)


def crudo(texto="algo", sin_voz=0.0, confianza=0.0, inicio=0.0, fin=2.0):
    return {
        "start": inicio,
        "end": fin,
        "text": texto,
        "no_speech_prob": sin_voz,
        "avg_logprob": confianza,
    }


def test_voz_clara_no_es_silencio():
    assert not _es_silencio(crudo(sin_voz=0.01, confianza=-0.2))


def test_sin_voz_y_sin_confianza_es_silencio():
    assert _es_silencio(crudo(sin_voz=0.95, confianza=-2.0))


def test_sin_voz_pero_con_confianza_no_se_descarta():
    # Hace falta que fallen las DOS señales, como hace el propio Whisper.
    assert not _es_silencio(crudo(sin_voz=0.95, confianza=-0.3))


def test_con_voz_pero_sin_confianza_no_se_descarta():
    assert not _es_silencio(crudo(sin_voz=0.1, confianza=-2.0))


def test_justo_en_los_umbrales_no_se_descarta():
    assert not _es_silencio(
        crudo(sin_voz=UMBRAL_SIN_VOZ, confianza=UMBRAL_CONFIANZA)
    )


def test_segmento_sin_esos_campos_no_se_descarta():
    # Si Whisper cambiara el formato, preferimos conservar el texto.
    assert not _es_silencio({"start": 0, "end": 1, "text": "hola"})


def test_filtra_la_muletilla_sobre_silencio():
    # El caso real: 'Gracias.' inventado sobre un tramo mudo.
    crudos = [
        crudo("Gracias.", sin_voz=0.92, confianza=-1.8),
        crudo("Abro la puerta con cuidado", sin_voz=0.02, confianza=-0.3),
    ]

    resultado = filtrar_segmentos(crudos, duracion=60.0, hablante="ana")

    assert [s.texto for s in resultado] == ["Abro la puerta con cuidado"]


def test_no_se_carga_frases_cortas_legitimas():
    # 'Gracias' dicho de verdad, con buena señal, debe conservarse.
    crudos = [crudo("Gracias.", sin_voz=0.01, confianza=-0.2)]

    resultado = filtrar_segmentos(crudos, duracion=60.0, hablante="ana")

    assert len(resultado) == 1
