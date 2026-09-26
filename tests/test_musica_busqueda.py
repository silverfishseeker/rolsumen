"""Tests de cómo se resuelve lo que escribe el usuario en `/play`.

El orden importa: **primero la carpeta local**. Un archivo propio suena
siempre, mientras que YouTube depende de la red y de que yt-dlp siga
funcionando esta semana.
"""

import pytest

from app.musica import busqueda
from app.musica.busqueda import ErrorBusqueda, buscar_local, resolver


@pytest.fixture
def carpeta(tmp_path):
    for nombre in (
        "Lluvia en el bosque.mp3",
        "Taberna animada.ogg",
        "Combate épico.flac",
        "notas.txt",
    ):
        (tmp_path / nombre).write_bytes(b"audio")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "Mazmorra.opus").write_bytes(b"audio")
    return str(tmp_path)


def test_encuentra_por_parte_del_nombre(carpeta):
    pista = buscar_local("lluvia", carpeta)

    assert pista is not None
    assert pista.titulo == "Lluvia en el bosque"
    assert pista.local


def test_no_distingue_mayusculas(carpeta):
    assert buscar_local("TABERNA", carpeta) is not None


def test_busca_tambien_en_subcarpetas(carpeta):
    assert buscar_local("mazmorra", carpeta).titulo == "Mazmorra"


def test_ignora_lo_que_no_es_audio(carpeta):
    assert buscar_local("notas", carpeta) is None


def test_el_nombre_exacto_gana_al_que_solo_contiene(tmp_path):
    """Si pides «Combate» y existe ese archivo, no vale darte «Combate 2»."""
    (tmp_path / "Combate 2.mp3").write_bytes(b"audio")
    (tmp_path / "Combate.mp3").write_bytes(b"audio")

    assert buscar_local("Combate", str(tmp_path)).titulo == "Combate"


def test_sin_carpeta_configurada_no_busca(carpeta):
    assert buscar_local("lluvia", "") is None


def test_una_carpeta_que_no_existe_no_revienta():
    assert buscar_local("lluvia", "C:/no/existe/de/nada") is None


def test_lo_local_gana_a_youtube(carpeta, monkeypatch):
    def no_llamar(_c):
        raise AssertionError("no debería preguntar a YouTube teniendo el archivo")

    monkeypatch.setattr(busqueda, "buscar_en_youtube", no_llamar)

    pista = resolver("taberna", carpeta, "ana")

    assert pista.local and pista.pedida_por == "ana"


def test_si_no_esta_en_local_se_busca_fuera(carpeta, monkeypatch):
    from app.musica.lista import Pista

    monkeypatch.setattr(
        busqueda, "buscar_en_youtube",
        lambda c: Pista("lo de fuera", "http://a", "", duracion=60),
    )

    pista = resolver("algo que no tengo", carpeta, "ana")

    assert pista.titulo == "lo de fuera"
    assert not pista.local
    assert pista.pedida_por == "ana", "quien la pide se rellena al resolver"


def test_una_consulta_vacia_se_rechaza(carpeta):
    with pytest.raises(ErrorBusqueda, match="qué quieres escuchar"):
        resolver("   ", carpeta, "ana")


def test_una_url_no_se_busca_en_local(carpeta, monkeypatch):
    pedido = {}

    def falso_extraer(consulta):
        pedido["consulta"] = consulta
        return {"url": "http://audio", "title": "Un vídeo", "duration": 10}

    monkeypatch.setattr(busqueda, "_extraer", falso_extraer)

    pista = resolver("https://youtu.be/xyz", carpeta, "ana")

    assert pista.titulo == "Un vídeo"
    assert pedido["consulta"] == "https://youtu.be/xyz", "la URL va tal cual"


def test_lo_que_no_es_url_se_busca_en_youtube(monkeypatch):
    pedido = {}

    def falso_ydl(opciones):
        class Falso:
            def __enter__(self_): return self_
            def __exit__(self_, *a): return False
            def extract_info(self_, objetivo, download=False):
                pedido["objetivo"] = objetivo
                return {"entries": [{"url": "http://a", "title": "t", "duration": 1}]}
        return Falso()

    import yt_dlp

    monkeypatch.setattr(yt_dlp, "YoutubeDL", falso_ydl)

    busqueda.buscar_en_youtube("musica de taberna")

    assert pedido["objetivo"] == "ytsearch1:musica de taberna"


def test_una_busqueda_sin_resultados_se_explica(monkeypatch):
    monkeypatch.setattr(busqueda, "_extraer", lambda c: {"url": None})

    with pytest.raises(ErrorBusqueda, match="no se pudo obtener|No se pudo obtener"):
        busqueda.buscar_en_youtube("nada")


def test_si_yt_dlp_revienta_se_traduce(monkeypatch):
    import yt_dlp

    def explota(opciones):
        raise RuntimeError("YouTube cambió algo")

    monkeypatch.setattr(yt_dlp, "YoutubeDL", explota)

    with pytest.raises(ErrorBusqueda, match="YouTube no devolvió nada"):
        busqueda.buscar_en_youtube("lo que sea")


def test_no_se_descarga_nada():
    """Se reproduce en streaming: descargar sería lento y llenaría el disco."""
    assert busqueda.OPCIONES_YTDLP["skip_download"] is True
    assert busqueda.OPCIONES_YTDLP["noplaylist"] is True
