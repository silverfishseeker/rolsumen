"""Transcripción por lotes: varios fragmentos a la vez en la GPU.

Medido en una 3070 Ti de 8 GB sobre 8,3 minutos de audio real:

    secuencial                    75,4 s   95 segmentos (uno cada 5,2 s)
    lotes de 8, trozos de 5 s     26,3 s  100 segmentos (uno cada 5,0 s)
    lotes de 8, por defecto       11,2 s   18 segmentos (uno cada 27,7 s)

El de 28 s es más rápido pero inservible aquí: con varias personas hablando,
esa granularidad junta intervenciones distintas en un mismo bloque y la línea
de tiempo combinada deja de parecer una conversación.

Sobre la calidad: el modelo **no es determinista**. Dos pasadas secuenciales
sobre el mismo audio se parecen un 91,2%; los lotes con trozos de 5 s se
parecen un 89,0% a la secuencial. La diferencia queda dentro de ese ruido.
"""

import pytest

from app.pipeline import transcriptor as tr


def test_el_tamano_de_lote_es_el_medido():
    # Con 16 no cabe en 8 GB y empeora: 47 s frente a 11 s.
    assert tr.TAMANO_LOTE == 8


def test_los_trozos_dan_la_granularidad_del_modo_secuencial():
    # 5 s por trozo -> ~5 s por segmento, como la transcripción secuencial.
    assert tr.SEGUNDOS_POR_TROZO == 5


def test_se_usa_el_pipeline_por_lotes_si_esta(monkeypatch):
    usado = {}

    class LotesFalso:
        def transcribe(self, ruta, **kwargs):
            usado.update(kwargs)
            return iter([]), None

    t = tr.Transcriptor()
    t._modelo = object()
    t._lotes = LotesFalso()
    monkeypatch.setattr(tr.dependencias, "comprobar_ffmpeg",
                        lambda: tr.dependencias.Dependencia("ffmpeg", True))
    monkeypatch.setattr(tr, "duracion_audio", lambda _r: 60.0)

    t.transcribir(tr.Path("1.flac"))

    assert usado["batch_size"] == tr.TAMANO_LOTE
    assert usado["chunk_length"] == tr.SEGUNDOS_POR_TROZO
    assert usado["vad_filter"] is True, "el silencio sigue habiendo que filtrarlo"


def test_sin_pipeline_por_lotes_se_usa_el_de_siempre(monkeypatch):
    """Una versión antigua de faster-whisper no debe romper la aplicación."""
    usado = {}

    class ModeloFalso:
        def transcribe(self, ruta, **kwargs):
            usado.update(kwargs)
            return iter([]), None

    t = tr.Transcriptor()
    t._modelo = ModeloFalso()
    t._lotes = None
    monkeypatch.setattr(tr.dependencias, "comprobar_ffmpeg",
                        lambda: tr.dependencias.Dependencia("ffmpeg", True))
    monkeypatch.setattr(tr, "duracion_audio", lambda _r: 60.0)

    t.transcribir(tr.Path("1.flac"))

    assert "batch_size" not in usado
    assert usado["vad_filter"] is True


def test_preparar_lotes_no_revienta_sin_soporte(monkeypatch):
    t = tr.Transcriptor()
    t._modelo = object()

    def sin_soporte(*a, **k):
        raise ImportError("versión antigua")

    import faster_whisper

    monkeypatch.setattr(faster_whisper, "BatchedInferencePipeline", sin_soporte)

    assert t._preparar_lotes() is None
