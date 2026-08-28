"""Tests de la traducción de pistas a nombres legibles.

El `cook` self-hosted nombra las pistas sólo con su número (`1.flac`), a
diferencia de la web pública de Craig, que les añade el usuario. La
correspondencia vive en el archivo `.ogg.users` de la grabación.
"""

import pytest

from app import config as cfg
from app.pipeline import orquestador
from app.pipeline.orquestador import _mapa_hablantes


@pytest.fixture
def sesion(monkeypatch, tmp_path):
    """Una sesion transcrita de mentira, fuera de los datos del usuario."""
    monkeypatch.setattr(orquestador.cfg, "DIR_TRANSCRIPCIONES", tmp_path)
    etiqueta = "2026-01-01_abc"
    (tmp_path / etiqueta).mkdir()
    return etiqueta


def configuracion(jugadores=None):
    return cfg.Config(jugadores=jugadores or {})


def con_usuarios(monkeypatch, usuarios):
    monkeypatch.setattr(
        orquestador.craig_client, "usuarios", lambda *a, **k: usuarios
    )


def test_traduce_el_numero_de_pista_al_usuario(monkeypatch, sesion):
    con_usuarios(monkeypatch, {"1": "silverfishlord", "2": "frangc99"})

    mapa = _mapa_hablantes(sesion, configuracion())

    assert mapa["1"] == "silverfishlord"
    assert mapa["2"] == "frangc99"


def test_encadena_hasta_el_nombre_del_personaje(monkeypatch, sesion):
    con_usuarios(monkeypatch, {"1": "silverfishlord"})

    mapa = _mapa_hablantes(sesion, configuracion({"silverfishlord": "Kaelen"}))

    # numero de pista -> usuario -> personaje
    assert mapa["1"] == "Kaelen"


def test_sin_personaje_configurado_se_queda_en_el_usuario(monkeypatch, sesion):
    con_usuarios(monkeypatch, {"1": "silverfishlord"})

    mapa = _mapa_hablantes(sesion, configuracion({"otro": "Marina"}))

    assert mapa["1"] == "silverfishlord"


def test_sin_archivo_de_usuarios_no_revienta(monkeypatch, sesion):
    con_usuarios(monkeypatch, {})

    mapa = _mapa_hablantes(sesion, configuracion({"silverfishlord": "Kaelen"}))

    # Se conserva el mapeo por nombre, por si las pistas ya vienen nombradas.
    assert mapa.get("silverfishlord") == "Kaelen"


def test_avisa_si_no_puede_identificar_a_nadie(monkeypatch, sesion):
    con_usuarios(monkeypatch, {})
    avisos = []

    _mapa_hablantes(sesion, configuracion(), avisos.append)

    assert any("no se pudo identificar" in a.lower() for a in avisos)


def test_anuncia_los_participantes(monkeypatch, sesion):
    con_usuarios(monkeypatch, {"1": "ana", "2": "bea"})
    avisos = []

    _mapa_hablantes(sesion, configuracion(), avisos.append)

    assert any("ana" in a and "bea" in a for a in avisos)


def test_funciona_con_pistas_ya_nombradas(monkeypatch):
    # ZIP descargado de la web pública: las pistas traen el usuario en el nombre.
    con_usuarios(monkeypatch, {})

    mapa = _mapa_hablantes(
        "abc", configuracion({"silverfishlord": "Kaelen", "caliece": "Marina"})
    )

    assert mapa["silverfishlord"] == "Kaelen"
    assert mapa["caliece"] == "Marina"


def test_el_mapeo_por_numero_tiene_prioridad(monkeypatch, sesion):
    # Si un usuario se llamara como un número, manda la pista.
    con_usuarios(monkeypatch, {"1": "ana"})

    mapa = _mapa_hablantes(sesion, configuracion({"1": "NoDeberiaGanar"}))

    assert mapa["1"] == "ana"

# --- Copia local del mapeo ---------------------------------------------------


def test_los_hablantes_se_guardan_junto_a_la_transcripcion(monkeypatch, sesion):
    con_usuarios(monkeypatch, {"1": "silverfishlord"})

    _mapa_hablantes(sesion, configuracion())

    assert orquestador.hablantes_guardados(sesion) == {"1": "silverfishlord"}


def test_si_craig_ya_no_la_tiene_se_usa_la_copia(monkeypatch, sesion):
    """Craig borra las grabaciones pasado su plazo de retencion.

    Sin copia local, regenerar una cronica antigua daria hablantes «1» y «2».
    """
    con_usuarios(monkeypatch, {"1": "silverfishlord", "2": "frangc99"})
    _mapa_hablantes(sesion, configuracion())

    con_usuarios(monkeypatch, {})  # la grabacion ya no esta en Craig
    avisos = []
    mapa = _mapa_hablantes(sesion, configuracion(), avisos.append)

    assert mapa == {"1": "silverfishlord", "2": "frangc99"}
    assert not any("no se pudo identificar" in a.lower() for a in avisos)


def test_la_copia_no_pisa_lo_que_craig_sigue_sabiendo(monkeypatch, sesion):
    con_usuarios(monkeypatch, {"1": "viejo"})
    _mapa_hablantes(sesion, configuracion())

    con_usuarios(monkeypatch, {"1": "nuevo"})
    assert _mapa_hablantes(sesion, configuracion())["1"] == "nuevo"
    assert orquestador.hablantes_guardados(sesion) == {"1": "nuevo"}


def test_no_se_crea_carpeta_para_una_sesion_inexistente(monkeypatch, tmp_path):
    monkeypatch.setattr(orquestador.cfg, "DIR_TRANSCRIPCIONES", tmp_path)
    con_usuarios(monkeypatch, {"1": "alguien"})

    _mapa_hablantes("sesion_que_no_existe", configuracion())

    assert list(tmp_path.iterdir()) == [], "no debe sembrar carpetas fantasma"


def test_sin_craig_y_sin_copia_avisa(monkeypatch, sesion):
    con_usuarios(monkeypatch, {})
    avisos = []

    _mapa_hablantes(sesion, configuracion(), avisos.append)

    assert any("no se pudo identificar" in a.lower() for a in avisos)


def test_una_copia_corrupta_no_revienta(monkeypatch, sesion):
    con_usuarios(monkeypatch, {})
    (orquestador.cfg.DIR_TRANSCRIPCIONES / sesion / "hablantes.json").write_text(
        "{roto", encoding="utf-8"
    )

    assert _mapa_hablantes(sesion, configuracion()) == {}


# --- hablantes.json no es una pista ------------------------------------------


def test_el_archivo_de_hablantes_no_cuenta_como_pista(monkeypatch, sesion):
    """Se guarda junto a las pistas, pero cargarlo como una revienta.

    `cargar_transcripcion` espera una lista de segmentos; con el diccionario de
    hablantes lanza TypeError, que ademas no esta entre los errores previstos.
    """
    carpeta = orquestador.cfg.DIR_TRANSCRIPCIONES / sesion
    (carpeta / "1.json").write_text("[]", encoding="utf-8")
    (carpeta / "2.json").write_text("[]", encoding="utf-8")
    con_usuarios(monkeypatch, {"1": "alguien"})
    _mapa_hablantes(sesion, configuracion())

    pistas = orquestador.pistas_transcritas(sesion)

    assert [p.name for p in pistas] == ["1.json", "2.json"]


def test_el_listado_cuenta_solo_las_pistas(monkeypatch, sesion):
    carpeta = orquestador.cfg.DIR_TRANSCRIPCIONES / sesion
    for numero in "123":
        (carpeta / f"{numero}.json").write_text("[]", encoding="utf-8")
    con_usuarios(monkeypatch, {"1": "alguien"})
    _mapa_hablantes(sesion, configuracion())

    monkeypatch.setattr(orquestador.cfg, "DIR_RESUMENES", carpeta / "no_hay")
    fila = next(f for f in orquestador.transcripciones_disponibles() if f.clave == sesion)

    assert fila.detalle.startswith("3 pistas")


def test_una_sesion_con_solo_hablantes_no_cuenta_como_transcrita(monkeypatch, sesion):
    con_usuarios(monkeypatch, {"1": "alguien"})
    _mapa_hablantes(sesion, configuracion())

    assert orquestador.sesiones_transcritas() == []
