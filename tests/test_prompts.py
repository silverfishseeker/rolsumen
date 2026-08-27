"""Tests de la carga de prompts desde archivos de texto editables.

Los prompts viven en `app/prompts/<modo>/<nombre>.txt`. Lo específico de cada
modo se prueba en `test_modos.py`; aquí se cubre el mecanismo de carga.
"""

import pytest

from app import config as cfg
from app.pipeline import resumidor
from app.pipeline.resumidor import cargar_prompt

MODO = cfg.MODO_POR_DEFECTO


def preparar(tmp_path, monkeypatch):
    monkeypatch.setattr(resumidor, "DIR_PROMPTS", tmp_path)
    carpeta = tmp_path / MODO
    carpeta.mkdir()
    return carpeta


def test_lee_el_prompt_del_archivo(tmp_path, monkeypatch):
    carpeta = preparar(tmp_path, monkeypatch)
    (carpeta / "prueba.txt").write_text("instrucciones a medida", encoding="utf-8")

    assert cargar_prompt("prueba", MODO) == "instrucciones a medida"


def test_si_falta_el_prompt_se_dice_cual(tmp_path, monkeypatch):
    # Mejor un error que señale el archivo que una copia interna que puede
    # divergir de los prompts reales sin que nadie se entere.
    preparar(tmp_path, monkeypatch)

    with pytest.raises(FileNotFoundError, match="no_existe"):
        cargar_prompt("no_existe", MODO)


def test_un_prompt_vacio_cuenta_como_ausente(tmp_path, monkeypatch):
    carpeta = preparar(tmp_path, monkeypatch)
    (carpeta / "vacio.txt").write_text("   \n\n", encoding="utf-8")

    with pytest.raises(FileNotFoundError):
        cargar_prompt("vacio", MODO)


def test_se_relee_en_cada_llamada(tmp_path, monkeypatch):
    # Permite afinar el prompt sin reiniciar la aplicación.
    carpeta = preparar(tmp_path, monkeypatch)
    archivo = carpeta / "p.txt"

    archivo.write_text("primera versión", encoding="utf-8")
    assert cargar_prompt("p", MODO) == "primera versión"

    archivo.write_text("segunda versión", encoding="utf-8")
    assert cargar_prompt("p", MODO) == "segunda versión"


def test_el_prompt_del_bloque_usa_el_archivo(tmp_path, monkeypatch):
    from app.pipeline.tipos import Bloque, Segmento

    carpeta = preparar(tmp_path, monkeypatch)
    (carpeta / "cronologia.txt").write_text("MI PROMPT", encoding="utf-8")

    bloque = Bloque(
        indice=1,
        total=1,
        segmentos=[Segmento(inicio=0, fin=1, texto="hola", hablante="ana")],
    )

    assert "MI PROMPT" in resumidor._prompt_bloque(bloque, None, MODO)


def test_los_prompts_reales_existen():
    assert (cfg.DIR_PROMPTS / MODO / "cronologia.txt").exists()
    assert (cfg.DIR_PROMPTS / MODO / "cabecera.txt").exists()


def test_el_prompt_real_de_cronologia_conserva_las_reglas_clave():
    texto = (
        (cfg.DIR_PROMPTS / MODO / "cronologia.txt").read_text(encoding="utf-8").lower()
    )

    assert "no inventes" in texto
    assert "tiradas de dados" in texto
    assert "###" in texto  # el nivel de encabezado que espera el documento


def test_el_prompt_de_cabecera_pide_las_tres_secciones():
    texto = (
        (cfg.DIR_PROMPTS / MODO / "cabecera.txt").read_text(encoding="utf-8").lower()
    )

    assert "sinopsis" in texto
    assert "personajes" in texto
    assert "lugares" in texto
