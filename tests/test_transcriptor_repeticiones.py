"""Tests del descarte de muletillas repetidas por toda la pista.

Basado en datos reales: sobre una pista casi muda, `large-v3` produjo
'Gracias.' en los segundos 0, 30 y 60 exactos (múltiplos de su ventana de
análisis), y con `avg_logprob` alto — es decir, el modelo estaba *seguro*, así
que los umbrales de silencio no la detectan.
"""

from app.pipeline.transcriptor import _frases_repetidas, _normalizar, filtrar_segmentos


def crudo(texto, inicio, sin_voz=0.3, confianza=-0.2):
    return {
        "start": inicio,
        "end": inicio + 1.0,
        "text": texto,
        "no_speech_prob": sin_voz,
        "avg_logprob": confianza,
    }


def test_normaliza_para_comparar():
    assert _normalizar("  Gracias. ") == _normalizar("¡Gracias!")


def test_detecta_la_muletilla_repetida():
    crudos = [crudo("Gracias.", 0), crudo("Gracias.", 30), crudo("Gracias.", 60)]

    assert "gracias" in _frases_repetidas(crudos)


def test_dos_apariciones_no_bastan():
    crudos = [crudo("Gracias.", 0), crudo("Gracias.", 30)]

    assert _frases_repetidas(crudos) == set()


def test_una_frase_larga_repetida_no_se_marca():
    # Podría ser una coletilla real del jugador.
    larga = "esto es una frase bastante larga que alguien podría repetir"
    crudos = [crudo(larga, 0), crudo(larga, 30), crudo(larga, 60)]

    assert _frases_repetidas(crudos) == set()


def test_conserva_la_primera_aparicion():
    # Por si la muletilla fuera real la primera vez.
    crudos = [
        crudo("Gracias.", 0),
        crudo("Abro la puerta y entro despacio", 10),
        crudo("Gracias.", 30),
        crudo("Gracias.", 60),
    ]

    resultado = filtrar_segmentos(crudos, duracion=120.0, hablante="ana")

    textos = [s.texto for s in resultado]
    assert textos.count("Gracias.") == 1
    assert "Abro la puerta y entro despacio" in textos


def test_el_caso_real_de_la_pista_casi_muda():
    # Valores tomados de una ejecución real de large-v3.
    crudos = [
        crudo("Gracias.", 0.0, sin_voz=0.5259, confianza=-0.2096),
        crudo("Gracias.", 30.0, sin_voz=0.4821, confianza=-0.0486),
        crudo("Gracias.", 60.0, sin_voz=0.0241, confianza=-0.1270),
    ]

    resultado = filtrar_segmentos(crudos, duracion=90.0, hablante="ana")

    # De tres alucinaciones sólo debe sobrevivir una.
    assert len(resultado) == 1


def test_no_afecta_a_una_transcripcion_normal():
    crudos = [
        crudo("Abro la puerta", 0),
        crudo("Entro en la sala", 10),
        crudo("Hay una mesa al fondo", 20),
    ]

    resultado = filtrar_segmentos(crudos, duracion=60.0, hablante="ana")

    assert len(resultado) == 3


def test_palabras_sueltas_distintas_no_se_tocan():
    crudos = [crudo("Sí", 0), crudo("No", 10), crudo("Vale", 20)]

    resultado = filtrar_segmentos(crudos, duracion=60.0, hablante="ana")

    assert len(resultado) == 3
