"""Tests de la traducción de pistas a nombres legibles.

El `cook` self-hosted nombra las pistas sólo con su número (`1.flac`), a
diferencia de la web pública de Craig, que les añade el usuario. La
correspondencia vive en el archivo `.ogg.users` de la grabación.
"""

from app import config as cfg
from app.pipeline import orquestador
from app.pipeline.orquestador import _mapa_hablantes


def configuracion(jugadores=None):
    return cfg.Config(jugadores=jugadores or {})


def con_usuarios(monkeypatch, usuarios):
    monkeypatch.setattr(
        orquestador.craig_client, "usuarios", lambda *a, **k: usuarios
    )


def test_traduce_el_numero_de_pista_al_usuario(monkeypatch):
    con_usuarios(monkeypatch, {"1": "silverfishlord", "2": "frangc99"})

    mapa = _mapa_hablantes("abc", configuracion())

    assert mapa["1"] == "silverfishlord"
    assert mapa["2"] == "frangc99"


def test_encadena_hasta_el_nombre_del_personaje(monkeypatch):
    con_usuarios(monkeypatch, {"1": "silverfishlord"})

    mapa = _mapa_hablantes("abc", configuracion({"silverfishlord": "Kaelen"}))

    # numero de pista -> usuario -> personaje
    assert mapa["1"] == "Kaelen"


def test_sin_personaje_configurado_se_queda_en_el_usuario(monkeypatch):
    con_usuarios(monkeypatch, {"1": "silverfishlord"})

    mapa = _mapa_hablantes("abc", configuracion({"otro": "Marina"}))

    assert mapa["1"] == "silverfishlord"


def test_sin_archivo_de_usuarios_no_revienta(monkeypatch):
    con_usuarios(monkeypatch, {})

    mapa = _mapa_hablantes("abc", configuracion({"silverfishlord": "Kaelen"}))

    # Se conserva el mapeo por nombre, por si las pistas ya vienen nombradas.
    assert mapa.get("silverfishlord") == "Kaelen"


def test_avisa_si_no_puede_identificar_a_nadie(monkeypatch):
    con_usuarios(monkeypatch, {})
    avisos = []

    _mapa_hablantes("abc", configuracion(), avisos.append)

    assert any("no se pudo identificar" in a.lower() for a in avisos)


def test_anuncia_los_participantes(monkeypatch):
    con_usuarios(monkeypatch, {"1": "ana", "2": "bea"})
    avisos = []

    _mapa_hablantes("abc", configuracion(), avisos.append)

    assert any("ana" in a and "bea" in a for a in avisos)


def test_funciona_con_pistas_ya_nombradas(monkeypatch):
    # ZIP descargado de la web pública: las pistas traen el usuario en el nombre.
    con_usuarios(monkeypatch, {})

    mapa = _mapa_hablantes(
        "abc", configuracion({"silverfishlord": "Kaelen", "caliece": "Marina"})
    )

    assert mapa["silverfishlord"] == "Kaelen"
    assert mapa["caliece"] == "Marina"


def test_el_mapeo_por_numero_tiene_prioridad(monkeypatch):
    # Si un usuario se llamara como un número, manda la pista.
    con_usuarios(monkeypatch, {"1": "ana"})

    mapa = _mapa_hablantes("abc", configuracion({"1": "NoDeberiaGanar"}))

    assert mapa["1"] == "ana"
