"""Tests del filtrado de la salida de Whisper y del nombrado de pistas."""

from pathlib import Path

from app.pipeline.transcriptor import filtrar_segmentos, nombre_hablante


def crudo(inicio, fin, texto):
    return {"start": inicio, "end": fin, "text": texto}


def test_nombre_hablante_de_pista_de_craig():
    assert nombre_hablante(Path("rec/2-silverfishlord.flac")) == "silverfishlord"
    assert nombre_hablante(Path("1-caliece.ogg")) == "caliece"


def test_nombre_hablante_admite_guion_bajo():
    assert nombre_hablante(Path("3_ana.flac")) == "ana"


def test_nombre_hablante_sin_prefijo_numerico():
    assert nombre_hablante(Path("ana.flac")) == "ana"


def test_nombre_hablante_conserva_guiones_internos():
    assert nombre_hablante(Path("1-nombre-con-guiones.flac")) == "nombre-con-guiones"


def test_descarta_segmentos_mas_alla_del_audio_real():
    # El caso que vimos con large-v3: inventa texto pasado el final del archivo.
    crudos = [
        crudo(0.0, 40.0, "Contenido real"),
        crudo(74.1, 83.1, "¡Vamos a ver!"),
    ]

    resultado = filtrar_segmentos(crudos, duracion=76.68, hablante="ana")

    assert len(resultado) == 2  # 74.1 < 76.68, todavía dentro del audio

    resultado_estricto = filtrar_segmentos(crudos, duracion=70.0, hablante="ana")
    assert [s.texto for s in resultado_estricto] == ["Contenido real"]


def test_recorta_el_final_a_la_duracion_real():
    crudos = [crudo(0.0, 120.0, "Se pasa de largo")]

    resultado = filtrar_segmentos(crudos, duracion=76.68, hablante="ana")

    assert resultado[0].fin == 76.68


def test_descarta_repeticiones_consecutivas():
    crudos = [
        crudo(0.0, 2.0, "¡Vamos a ver!"),
        crudo(2.0, 4.0, "¡Vamos a ver!"),
        crudo(4.0, 6.0, "¡Vamos a ver!"),
    ]

    resultado = filtrar_segmentos(crudos, duracion=10.0, hablante="ana")

    assert len(resultado) == 1


def test_permite_repeticion_no_consecutiva():
    crudos = [
        crudo(0.0, 2.0, "Sí"),
        crudo(2.0, 4.0, "No"),
        crudo(4.0, 6.0, "Sí"),
    ]

    resultado = filtrar_segmentos(crudos, duracion=10.0, hablante="ana")

    assert len(resultado) == 3


def test_descarta_creditos_de_subtitulos_alucinados():
    crudos = [
        crudo(0.0, 2.0, "Contenido real"),
        crudo(2.0, 5.0, "Subtítulos realizados por la comunidad de Amara.org"),
    ]

    resultado = filtrar_segmentos(crudos, duracion=10.0, hablante="ana")

    assert [s.texto for s in resultado] == ["Contenido real"]


def test_descarta_segmentos_vacios():
    crudos = [crudo(0.0, 2.0, "   "), crudo(2.0, 4.0, "Algo")]

    resultado = filtrar_segmentos(crudos, duracion=10.0, hablante="ana")

    assert len(resultado) == 1


def test_sin_duracion_conocida_no_filtra_por_tiempo():
    # Si ffprobe falla, preferimos conservar todo antes que perder contenido.
    crudos = [crudo(0.0, 2.0, "Uno"), crudo(9999.0, 10000.0, "Dos")]

    resultado = filtrar_segmentos(crudos, duracion=None, hablante="ana")

    assert len(resultado) == 2


def test_asigna_el_hablante_a_todos_los_segmentos():
    crudos = [crudo(0.0, 2.0, "Uno"), crudo(3.0, 4.0, "Dos")]

    resultado = filtrar_segmentos(crudos, duracion=10.0, hablante="kaelen")

    assert all(s.hablante == "kaelen" for s in resultado)
