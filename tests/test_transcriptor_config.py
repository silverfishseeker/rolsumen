"""Tests de cómo se configura el transcriptor a partir de config.ini.

No se carga ningún modelo: sólo se comprueba que los ajustes del usuario
llegan bien al motor de transcripción.
"""

from app import config as cfg
from app.pipeline.orquestador import _crear_transcriptor


def configuracion(**ajustes):
    modelos = cfg.Modelos(**ajustes)
    return cfg.Config(modelos=modelos, idioma="es")


def test_usa_el_modelo_configurado():
    transcriptor = _crear_transcriptor(configuracion(transcripcion="medium"))

    assert transcriptor.nombre_modelo == "medium"


def test_usa_el_idioma_configurado():
    conf = cfg.Config(idioma="en")

    assert _crear_transcriptor(conf).idioma == "en"


def test_el_idioma_va_en_codigo_iso():
    # faster-whisper espera 'es', no 'Spanish' como la biblioteca original.
    assert cfg.Config().idioma == "es"


def test_dispositivo_explicito_se_respeta():
    transcriptor = _crear_transcriptor(configuracion(dispositivo="cpu"))

    assert transcriptor.dispositivo() == "cpu"


def test_auto_resuelve_a_cuda_o_cpu():
    transcriptor = _crear_transcriptor(configuracion(dispositivo="auto"))

    assert transcriptor.dispositivo() in {"cuda", "cpu"}


def test_en_cpu_no_se_pide_float16():
    # float16 no existe en CPU: cargar el modelo fallaría.
    transcriptor = _crear_transcriptor(
        configuracion(dispositivo="cpu", precision="float16")
    )

    assert transcriptor._precision == "int8"


def test_en_gpu_se_respeta_la_precision():
    transcriptor = _crear_transcriptor(
        configuracion(dispositivo="cuda", precision="int8_float16")
    )

    assert transcriptor._precision == "int8_float16"


def test_el_modelo_no_se_carga_hasta_transcribir():
    # Cargar tarda y ocupa VRAM: sólo debe ocurrir al transcribir de verdad.
    transcriptor = _crear_transcriptor(configuracion())

    assert transcriptor._modelo is None
