"""Los ajustes nuevos tienen que llegar al pipeline, no quedarse en config.ini.

Un ajuste que se lee pero no se usa es peor que no tenerlo: el usuario lo
cambia, no pasa nada, y no hay forma de saber por qué.
"""

import pytest

from app import config as cfg
from app.pipeline import orquestador, resumidor, troceador
from app.pipeline.tipos import Segmento


def configuracion(**modelos):
    return cfg.Config(modelos=cfg.Modelos(**modelos))


def test_los_valores_por_defecto_son_los_del_codigo():
    m = cfg.Modelos()

    assert m.url_ollama == cfg.URL_OLLAMA_POR_DEFECTO
    assert m.temperatura == cfg.TEMPERATURA_POR_DEFECTO
    assert m.tokens_por_bloque == cfg.TOKENS_POR_BLOQUE_POR_DEFECTO


def test_el_resumidor_y_el_troceador_parten_de_lo_mismo():
    # Si se desincronizan, el config.ini diría una cosa y el código haría otra.
    assert resumidor.URL_OLLAMA == cfg.URL_OLLAMA_POR_DEFECTO
    assert resumidor.TEMPERATURA == cfg.TEMPERATURA_POR_DEFECTO
    assert troceador.PRESUPUESTO_TOKENS_POR_BLOQUE == cfg.TOKENS_POR_BLOQUE_POR_DEFECTO


def test_una_temperatura_distinta_viaja_hasta_la_peticion():
    peticion = resumidor._peticion(
        "hola", "modelo", "http://x", 8192, False, temperatura=0.9
    )
    import json

    cuerpo = json.loads(peticion.data.decode("utf-8"))

    assert cuerpo["options"]["temperature"] == 0.9


def test_un_tramo_mas_pequeno_produce_mas_bloques():
    segmentos = [Segmento(i, i + 1, "palabra " * 40, "a") for i in range(20)]

    pocos = troceador.trocear(segmentos, presupuesto=4000)
    muchos = troceador.trocear(segmentos, presupuesto=500)

    assert len(muchos) > len(pocos)


def test_toda_la_cadena_acepta_la_temperatura():
    """Un doble con **kwargs se traga cualquier argumento.

    Por eso este test mira las firmas de verdad: la primera versión pasaba los
    tests y reventaba al ejecutarse, porque `resumir()` no aceptaba el
    parámetro que el orquestador le mandaba.
    """
    import inspect

    for funcion in (
        resumidor.generar,
        resumidor.resumir_bloques,
        resumidor.generar_cabecera,
        resumidor.resumir,
    ):
        parametros = inspect.signature(funcion).parameters
        assert "temperatura" in parametros, f"{funcion.__name__} no la acepta"


def test_el_orquestador_usa_los_tres_ajustes(monkeypatch, tmp_path):
    """La comprobación que importa: que no se queden sin conectar."""
    recibido = {}

    def falso_resumir(bloques, **kwargs):
        # El doble acepta cualquier cosa; que la firma real también lo haga se
        # comprueba aparte, en test_toda_la_cadena_acepta_la_temperatura.
        recibido.update(kwargs)
        recibido["bloques"] = len(bloques)
        return resumidor.ResultadoResumen(documento="x", tramos=["x"])

    presupuestos = []
    trocear_real = troceador.trocear

    def falso_trocear(segmentos, presupuesto=None, **kwargs):
        presupuestos.append(presupuesto)
        return trocear_real(segmentos, presupuesto=presupuesto or 4000)

    monkeypatch.setattr(orquestador.cfg, "DIR_TRANSCRIPCIONES", tmp_path)
    monkeypatch.setattr(orquestador.resumidor, "resumir", falso_resumir)
    monkeypatch.setattr(orquestador.troceador, "trocear", falso_trocear)
    monkeypatch.setattr(orquestador, "_mapa_hablantes", lambda *a, **k: {})
    monkeypatch.setattr(orquestador, "_guardar_resumen", lambda *a, **k: tmp_path / "x.md")

    (tmp_path / "2026-01-01_abc").mkdir()
    pistas = [[Segmento(0, 1, "hola", "1")]]

    orquestador._combinar_y_resumir(
        pistas,
        "2026-01-01_abc",
        configuracion(url_ollama="http://otra:1234", temperatura=0.75,
                      tokens_por_bloque=1234),
        lambda _m: None,
    )

    assert recibido["url"] == "http://otra:1234"
    assert recibido["temperatura"] == 0.75
    assert presupuestos == [1234]


@pytest.mark.parametrize("escrito,esperado", [("0.7", 0.7), ("0,7", 0.7), ("no", 0.3)])
def test_la_temperatura_se_lee_con_coma_o_punto(escrito, esperado, tmp_path):
    ruta = tmp_path / "c.ini"
    ruta.write_text(cfg.plantilla_config(), encoding="utf-8")
    cfg.guardar_valores({("modelos", "temperatura"): escrito}, ruta)

    assert cfg.cargar(ruta).modelos.temperatura == esperado
