"""Tests del recorrido de grabaciones pendientes (modo consola).

Dos fallos que motivan estos tests:

1. `detener` solo se consultaba **entre** grabaciones, así que una transcripción
   larga era ininterrumpible: justo la parte que tarda.
2. Una cancelación se anotaba en el registro como si fuera un error.
"""

from datetime import datetime

import pytest

from app import config as cfg
from app.craig_client import ErrorCraig, Grabacion
from app.pipeline import orquestador
from app.pipeline.registro import Registro


def grabacion(id_grabacion: str) -> Grabacion:
    momento = datetime(2026, 8, 18, 10, 0)
    return Grabacion(id=id_grabacion, creada=momento, terminada=momento)


@pytest.fixture
def entorno(monkeypatch, tmp_path):
    """Aísla datos y evita cargar Whisper."""
    monkeypatch.setattr(orquestador.cfg, "DIR_TRANSCRIPCIONES", tmp_path / "t")
    monkeypatch.setattr(orquestador.cfg, "RUTA_PROCESADAS", tmp_path / "p.json")
    monkeypatch.setattr(orquestador.cfg, "asegurar_carpetas", lambda: None)
    monkeypatch.setattr(orquestador, "_crear_transcriptor", lambda _c: object())
    return tmp_path


def con_grabaciones(monkeypatch, *ids):
    monkeypatch.setattr(
        orquestador.craig_client,
        "grabaciones_terminadas",
        lambda *a, **k: [grabacion(i) for i in ids],
    )


def test_sin_grabaciones_no_hace_nada(monkeypatch, entorno):
    con_grabaciones(monkeypatch)

    assert orquestador.procesar_pendientes(cfg.Config()) == []


def test_si_craig_no_responde_no_revienta(monkeypatch, entorno):
    def explota(*a, **k):
        raise ErrorCraig("sin docker")

    monkeypatch.setattr(orquestador.craig_client, "grabaciones_terminadas", explota)
    avisos = []

    assert orquestador.procesar_pendientes(cfg.Config(), avisos.append) == []
    assert any("no se pudo consultar" in a.lower() for a in avisos)


def test_la_cancelacion_llega_dentro_de_la_grabacion(monkeypatch, entorno):
    """El fallo 1: `detener` debe alcanzar a la propia transcripción."""
    recibidos = []

    def falso_procesar(grab, config, transcriptor=None, avisar=None, cancelado=None):
        recibidos.append(cancelado)
        return orquestador.ResultadoProceso(grab.id, ok=True, resumen=entorno / "x.md")

    con_grabaciones(monkeypatch, "a")
    monkeypatch.setattr(orquestador, "procesar_grabacion", falso_procesar)

    orquestador.procesar_pendientes(cfg.Config(), detener=lambda: False)

    assert recibidos and callable(recibidos[0]), "hay que pasar el cancelado"


def test_una_cancelacion_no_se_anota_como_error(monkeypatch, entorno):
    """El fallo 2: cancelar no es fallar."""

    def falso_procesar(grab, config, transcriptor=None, avisar=None, cancelado=None):
        return orquestador.ResultadoProceso(
            grab.id, ok=False, error="cancelada", cancelada=True
        )

    con_grabaciones(monkeypatch, "a")
    monkeypatch.setattr(orquestador, "procesar_grabacion", falso_procesar)

    orquestador.procesar_pendientes(cfg.Config())

    assert Registro.cargar(orquestador.cfg.RUTA_PROCESADAS).entradas == {}


def test_una_cancelacion_detiene_el_resto_de_la_cola(monkeypatch, entorno):
    procesadas = []

    def falso_procesar(grab, config, transcriptor=None, avisar=None, cancelado=None):
        procesadas.append(grab.id)
        return orquestador.ResultadoProceso(
            grab.id, ok=False, error="cancelada", cancelada=True
        )

    con_grabaciones(monkeypatch, "a", "b", "c")
    monkeypatch.setattr(orquestador, "procesar_grabacion", falso_procesar)

    orquestador.procesar_pendientes(cfg.Config())

    assert procesadas == ["a"], "cancelar debe parar, no seguir con las siguientes"


def test_un_fallo_real_si_se_anota(monkeypatch, entorno):
    def falso_procesar(grab, config, transcriptor=None, avisar=None, cancelado=None):
        return orquestador.ResultadoProceso(grab.id, ok=False, error="reventó")

    con_grabaciones(monkeypatch, "a")
    monkeypatch.setattr(orquestador, "procesar_grabacion", falso_procesar)

    orquestador.procesar_pendientes(cfg.Config())

    entradas = Registro.cargar(orquestador.cfg.RUTA_PROCESADAS).entradas
    assert entradas["a"].ok is False
    assert "reventó" in entradas["a"].error


def test_lo_ya_procesado_no_se_repite(monkeypatch, entorno):
    registro = Registro.cargar(orquestador.cfg.RUTA_PROCESADAS)
    registro.marcar_ok("a", entorno / "a.md")

    procesadas = []

    def falso_procesar(grab, config, transcriptor=None, avisar=None, cancelado=None):
        procesadas.append(grab.id)
        return orquestador.ResultadoProceso(grab.id, ok=True, resumen=entorno / "b.md")

    con_grabaciones(monkeypatch, "a", "b")
    monkeypatch.setattr(orquestador, "procesar_grabacion", falso_procesar)

    orquestador.procesar_pendientes(cfg.Config())

    assert procesadas == ["b"]


def test_un_fallo_anterior_si_se_reintenta(monkeypatch, entorno):
    registro = Registro.cargar(orquestador.cfg.RUTA_PROCESADAS)
    registro.marcar_error("a", "lo que fuera")

    procesadas = []

    def falso_procesar(grab, config, transcriptor=None, avisar=None, cancelado=None):
        procesadas.append(grab.id)
        return orquestador.ResultadoProceso(grab.id, ok=True, resumen=entorno / "a.md")

    con_grabaciones(monkeypatch, "a")
    monkeypatch.setattr(orquestador, "procesar_grabacion", falso_procesar)

    orquestador.procesar_pendientes(cfg.Config())

    assert procesadas == ["a"], "los fallos se reintentan a propósito"
