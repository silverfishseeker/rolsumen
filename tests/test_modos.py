"""Tests de los modos de resumen (rol / conversación).

Cada modo tiene su propia carpeta de prompts en `prompts/<modo>/`, y se elige
con `modo` en la sección [general] de config.ini.
"""

from app import config as cfg
from app.pipeline import resumidor
from app.pipeline.resumidor import cargar_prompt
from app.pipeline.tipos import Bloque, Segmento


def escribir(tmp_path, contenido):
    ruta = tmp_path / "config.ini"
    ruta.write_text(contenido, encoding="utf-8")
    return ruta


def bloque():
    return Bloque(
        indice=1,
        total=1,
        segmentos=[Segmento(inicio=0, fin=5, texto="hola", hablante="ana")],
    )


# --- Configuración -----------------------------------------------------------


def test_el_modo_por_defecto_es_rol(tmp_path):
    assert cfg.cargar(tmp_path / "no_existe.ini").modo == "rol"


def test_se_puede_elegir_el_modo_conversacion(tmp_path):
    ruta = escribir(tmp_path, "[general]\nmodo = conversacion\n")

    assert cfg.cargar(ruta).modo == "conversacion"


def test_el_modo_no_distingue_mayusculas(tmp_path):
    ruta = escribir(tmp_path, "[general]\nmodo = CONVERSACION\n")

    assert cfg.cargar(ruta).modo == "conversacion"


def test_un_modo_desconocido_cae_al_de_por_defecto(tmp_path):
    # Preferible generar un resumen con el modo por defecto que no generar nada.
    ruta = escribir(tmp_path, "[general]\nmodo = inventado\n")

    assert cfg.cargar(ruta).modo == "rol"


def test_modo_vacio_cae_al_de_por_defecto(tmp_path):
    ruta = escribir(tmp_path, "[general]\nmodo =\n")

    assert cfg.cargar(ruta).modo == "rol"


# --- Carga de prompts por modo ----------------------------------------------


def test_carga_el_prompt_del_modo_indicado(tmp_path, monkeypatch):
    monkeypatch.setattr(resumidor, "DIR_PROMPTS", tmp_path)
    (tmp_path / "rol").mkdir()
    (tmp_path / "conversacion").mkdir()
    (tmp_path / "rol" / "cronologia.txt").write_text("PROMPT ROL", encoding="utf-8")
    (tmp_path / "conversacion" / "cronologia.txt").write_text(
        "PROMPT CHARLA", encoding="utf-8"
    )

    assert cargar_prompt("cronologia", "x", "rol") == "PROMPT ROL"
    assert cargar_prompt("cronologia", "x", "conversacion") == "PROMPT CHARLA"


def test_si_falta_el_prompt_del_modo_usa_el_de_rol(tmp_path, monkeypatch):
    # Un modo nuevo a medio hacer debe seguir funcionando.
    monkeypatch.setattr(resumidor, "DIR_PROMPTS", tmp_path)
    (tmp_path / "rol").mkdir()
    (tmp_path / "rol" / "cabecera.txt").write_text("CABECERA ROL", encoding="utf-8")

    assert cargar_prompt("cabecera", "x", "conversacion") == "CABECERA ROL"


def test_sin_ningun_archivo_usa_el_prompt_interno(tmp_path, monkeypatch):
    monkeypatch.setattr(resumidor, "DIR_PROMPTS", tmp_path)

    assert cargar_prompt("cronologia", "INTERNO", "conversacion") == "INTERNO"


def test_el_modo_llega_al_prompt_del_bloque(tmp_path, monkeypatch):
    monkeypatch.setattr(resumidor, "DIR_PROMPTS", tmp_path)
    (tmp_path / "conversacion").mkdir()
    (tmp_path / "conversacion" / "cronologia.txt").write_text(
        "SOY EL DE CHARLA", encoding="utf-8"
    )

    prompt = resumidor._prompt_bloque(bloque(), None, "conversacion")

    assert "SOY EL DE CHARLA" in prompt


# --- Los prompts reales del repositorio --------------------------------------


def test_existen_los_prompts_de_los_dos_modos():
    for modo in cfg.MODOS:
        assert (cfg.DIR_PROMPTS / modo / "cronologia.txt").exists(), modo
        assert (cfg.DIR_PROMPTS / modo / "cabecera.txt").exists(), modo


def test_el_modo_rol_filtra_lo_de_fuera_de_personaje():
    texto = (cfg.DIR_PROMPTS / "rol" / "cronologia.txt").read_text(encoding="utf-8")

    assert "IGNORA" in texto
    assert "tiradas de dados" in texto.lower()


def test_el_modo_conversacion_no_descarta_temas_por_informales():
    # La diferencia con el modo rol no es cuánto se condensa, sino QUÉ se
    # descarta: rol tira la charla de mesa; conversación la recoge, aunque
    # resumida.
    texto = (cfg.DIR_PROMPTS / "conversacion" / "cronologia.txt").read_text(
        encoding="utf-8"
    )

    assert "tiradas de dados" not in texto.lower()
    assert "fuera de personaje" not in texto.lower()


def test_los_dos_modos_piden_condensar_y_no_transcribir():
    # El primer intento devolvió un documento más largo que la transcripción
    # porque el modelo convertía cada intervención en una viñeta.
    texto = (cfg.DIR_PROMPTS / "conversacion" / "cronologia.txt").read_text(
        encoding="utf-8"
    )

    assert "resume, no transcribas" in texto.lower()
    assert "agrupa" in texto.lower()


def test_los_dos_modos_prohiben_inventar():
    for modo in cfg.MODOS:
        texto = (cfg.DIR_PROMPTS / modo / "cronologia.txt").read_text(encoding="utf-8")
        assert "No inventes" in texto, modo


def test_los_dos_modos_piden_secciones_del_mismo_nivel():
    # El documento final anida los tramos bajo '## Cronología'.
    for modo in cfg.MODOS:
        texto = (cfg.DIR_PROMPTS / modo / "cronologia.txt").read_text(encoding="utf-8")
        assert "`### `" in texto, modo
