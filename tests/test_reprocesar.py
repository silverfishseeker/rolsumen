"""Tests de la regeneración de crónicas desde transcripciones guardadas.

Permite afinar los prompts o el mapeo de personajes sin volver a transcribir,
que es la fase lenta (horas de audio).
"""

import json

from app import config as cfg
from app.pipeline import orquestador
from app.pipeline.orquestador import reprocesar, sesiones_transcritas


def crear_transcripcion(carpeta, nombre, segmentos):
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / f"{nombre}.json").write_text(
        json.dumps(segmentos, ensure_ascii=False), encoding="utf-8"
    )


def segmento(inicio, texto, hablante):
    return {
        "inicio": inicio,
        "fin": inicio + 5.0,
        "texto": texto,
        "hablante": hablante,
    }


def preparar_sesion(tmp_path, monkeypatch, etiqueta="2026-08-18_abc"):
    transcripciones = tmp_path / "transcripciones"
    monkeypatch.setattr(cfg, "DIR_TRANSCRIPCIONES", transcripciones)
    monkeypatch.setattr(orquestador.cfg, "DIR_TRANSCRIPCIONES", transcripciones)

    carpeta = transcripciones / etiqueta
    crear_transcripcion(carpeta, "1", [segmento(0, "Abro la puerta", "1")])
    crear_transcripcion(carpeta, "2", [segmento(10, "Yo te sigo", "2")])
    return carpeta


def test_lista_las_sesiones_transcritas(tmp_path, monkeypatch):
    preparar_sesion(tmp_path, monkeypatch)

    assert sesiones_transcritas() == ["2026-08-18_abc"]


def test_ignora_carpetas_sin_transcripciones(tmp_path, monkeypatch):
    preparar_sesion(tmp_path, monkeypatch)
    (cfg.DIR_TRANSCRIPCIONES / "vacia").mkdir()

    assert "vacia" not in sesiones_transcritas()


def test_sin_transcripciones_no_hay_sesiones(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "DIR_TRANSCRIPCIONES", tmp_path / "no_existe")
    monkeypatch.setattr(orquestador.cfg, "DIR_TRANSCRIPCIONES", tmp_path / "no_existe")

    assert sesiones_transcritas() == []


def test_falla_con_mensaje_claro_si_la_sesion_no_existe(tmp_path, monkeypatch):
    preparar_sesion(tmp_path, monkeypatch)

    resultado = reprocesar("no_existe", cfg.Config())

    assert resultado.ok is False
    assert "No hay transcripciones" in resultado.error


def test_no_vuelve_a_transcribir(tmp_path, monkeypatch):
    """Lo importante: nunca debe tocar Whisper ni el audio."""
    preparar_sesion(tmp_path, monkeypatch)
    monkeypatch.setattr(orquestador.craig_client, "usuarios", lambda *a, **k: {})

    def no_deberia_llamarse(*a, **k):
        raise AssertionError("reprocesar no debe transcribir de nuevo")

    monkeypatch.setattr(orquestador, "_crear_transcriptor", no_deberia_llamarse)
    monkeypatch.setattr(
        orquestador.resumidor,
        "resumir",
        lambda *a, **k: orquestador.resumidor.ResultadoResumen(
            documento="# doc", tramos=["t"]
        ),
    )
    monkeypatch.setattr(
        orquestador, "_guardar_resumen", lambda *a, **k: tmp_path / "s.md"
    )

    assert reprocesar("2026-08-18_abc", cfg.Config()).ok is True


def test_aplica_el_mapeo_de_personajes_al_regenerar(tmp_path, monkeypatch):
    preparar_sesion(tmp_path, monkeypatch)
    monkeypatch.setattr(
        orquestador.craig_client,
        "usuarios",
        lambda *a, **k: {"1": "silverfishlord", "2": "frangc99"},
    )

    capturado = {}

    def falso_resumir(bloques, **kwargs):
        capturado["participantes"] = kwargs["metadatos"]["Participantes"]
        return orquestador.resumidor.ResultadoResumen(documento="# d", tramos=["t"])

    monkeypatch.setattr(orquestador.resumidor, "resumir", falso_resumir)
    monkeypatch.setattr(
        orquestador, "_guardar_resumen", lambda *a, **k: tmp_path / "s.md"
    )

    configuracion = cfg.Config(jugadores={"silverfishlord": "Kaelen"})
    reprocesar("2026-08-18_abc", configuracion)

    # El personaje configurado y el usuario sin mapear, ambos legibles.
    assert "Kaelen" in capturado["participantes"]
    assert "frangc99" in capturado["participantes"]


def test_extrae_la_fecha_de_la_etiqueta(tmp_path, monkeypatch):
    preparar_sesion(tmp_path, monkeypatch)
    monkeypatch.setattr(orquestador.craig_client, "usuarios", lambda *a, **k: {})

    capturado = {}

    def falso_resumir(bloques, **kwargs):
        capturado["titulo"] = kwargs["titulo"]
        capturado["fecha"] = kwargs["metadatos"]["Fecha"]
        return orquestador.resumidor.ResultadoResumen(documento="# d", tramos=["t"])

    monkeypatch.setattr(orquestador.resumidor, "resumir", falso_resumir)
    monkeypatch.setattr(
        orquestador, "_guardar_resumen", lambda *a, **k: tmp_path / "s.md"
    )

    reprocesar("2026-08-18_abc", cfg.Config())

    assert capturado["fecha"] == "2026-08-18"
    assert "2026-08-18" in capturado["titulo"]
