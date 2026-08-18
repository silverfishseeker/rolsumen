"""Tests de la desactivación del razonamiento y del manejo de timeouts.

Motivo: `qwen3` genera un bloque <think> antes de responder que aquí se
descarta siempre. Con él activado, el mismo prompt trivial superó los 300 s;
sin él tardó 19 s. Con bloques reales de una sesión larga, eso hacía que el
resumen fallara por timeout.
"""

import json
import urllib.error

import pytest

from app.pipeline import resumidor
from app.pipeline.resumidor import ErrorOllama, _peticion, generar


class RespuestaFalsa:
    def __init__(self, texto="resultado"):
        self._datos = json.dumps({"response": texto}).encode("utf-8")

    def read(self):
        return self._datos

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def cuerpo_de(peticion):
    return json.loads(peticion.data.decode("utf-8"))


# --- Desactivación del razonamiento -----------------------------------------


def test_la_peticion_desactiva_el_razonamiento():
    cuerpo = cuerpo_de(_peticion("hola", "qwen3:8b", "http://x", 4096, pensar=False))

    assert cuerpo["think"] is False


def test_se_puede_omitir_el_parametro():
    cuerpo = cuerpo_de(_peticion("hola", "qwen3:8b", "http://x", 4096, pensar=None))

    assert "think" not in cuerpo


def test_por_defecto_no_se_piensa():
    assert resumidor.PENSAR is False


def test_la_peticion_lleva_el_contexto_y_la_temperatura():
    cuerpo = cuerpo_de(_peticion("hola", "m", "http://x", 12345, pensar=False))

    assert cuerpo["options"]["num_ctx"] == 12345
    assert cuerpo["options"]["temperature"] == resumidor.TEMPERATURA
    assert cuerpo["stream"] is False


def test_si_ollama_no_conoce_think_se_reintenta_sin_el(monkeypatch):
    intentos = []

    def falso_urlopen(peticion, timeout=None):
        cuerpo = cuerpo_de(peticion)
        intentos.append("think" in cuerpo)
        if "think" in cuerpo:
            raise urllib.error.HTTPError(
                "u", 400, "unknown parameter 'think'", {}, _Cuerpo()
            )
        return RespuestaFalsa("ok sin think")

    class _Cuerpo:
        def read(self):
            return b"unknown parameter 'think'"

    monkeypatch.setattr(resumidor.urllib.request, "urlopen", falso_urlopen)

    assert generar("hola") == "ok sin think"
    assert intentos == [True, False], "primero con think, luego sin él"


# --- Timeouts ----------------------------------------------------------------


def test_un_timeout_no_dice_que_ollama_este_parado(monkeypatch):
    # El mensaje anterior mandaba a comprobar si Ollama estaba arrancado,
    # cuando el problema real era que iba lento.
    def falso_urlopen(*a, **k):
        raise urllib.error.URLError(TimeoutError("timed out"))

    monkeypatch.setattr(resumidor.urllib.request, "urlopen", falso_urlopen)

    with pytest.raises(ErrorOllama) as excinfo:
        generar("hola", timeout=1800)

    mensaje = str(excinfo.value)
    assert "tardó más de" in mensaje
    assert "¿Está en marcha?" not in mensaje


def test_el_mensaje_de_timeout_sugiere_como_arreglarlo(monkeypatch):
    def falso_urlopen(*a, **k):
        raise TimeoutError("timed out")

    monkeypatch.setattr(resumidor.urllib.request, "urlopen", falso_urlopen)

    with pytest.raises(ErrorOllama) as excinfo:
        generar("hola")

    assert "contexto_resumen" in str(excinfo.value)


def test_ollama_apagado_sigue_diciendo_que_no_esta_en_marcha(monkeypatch):
    def falso_urlopen(*a, **k):
        raise urllib.error.URLError(ConnectionRefusedError("refused"))

    monkeypatch.setattr(resumidor.urllib.request, "urlopen", falso_urlopen)

    with pytest.raises(ErrorOllama, match="¿Está en marcha?"):
        generar("hola")


def test_el_timeout_por_defecto_es_generoso():
    # Un bloque grande en una GPU modesta puede tardar bastante.
    assert resumidor.TIMEOUT_SEGUNDOS >= 1800
