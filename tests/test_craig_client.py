"""Tests del cliente de Craig que no requieren Docker en marcha.

`extraer_pistas` se prueba contra los ZIP reales de Craig guardados en
`pruebas/`, si están disponibles.
"""

from datetime import datetime
from pathlib import Path

import pytest

from app.craig_client import Grabacion, _fecha, extraer_pistas

RAIZ = Path(__file__).resolve().parent.parent
ZIPS_REALES = sorted((RAIZ / "pruebas").glob("craig-*.flac.zip"))


def test_fecha_de_postgres():
    momento = _fecha("2026-08-18 01:23:45.678+00")

    assert momento is not None
    assert momento.year == 2026
    assert momento.month == 8
    assert momento.day == 18


def test_fecha_vacia_es_none():
    assert _fecha("") is None
    assert _fecha("   ") is None


def test_fecha_ilegible_es_none():
    assert _fecha("no soy una fecha") is None


def test_etiqueta_de_fecha_para_nombrar_archivos():
    grabacion = Grabacion(
        id="abc",
        guild_id="123",
        creada=datetime(2026, 8, 18, 22, 30),
        terminada=None,
    )

    assert grabacion.etiqueta_fecha == "2026-08-18"


def test_etiqueta_de_fecha_usa_el_final_si_no_hay_inicio():
    grabacion = Grabacion(
        id="abc", guild_id="123", creada=None, terminada=datetime(2026, 1, 5)
    )

    assert grabacion.etiqueta_fecha == "2026-01-05"


def test_etiqueta_de_fecha_sin_fechas():
    grabacion = Grabacion(id="abc", guild_id="123", creada=None, terminada=None)

    assert grabacion.etiqueta_fecha == "sin-fecha"


@pytest.mark.skipif(not ZIPS_REALES, reason="no hay ZIP de Craig en pruebas/")
def test_extrae_pistas_de_un_zip_real(tmp_path):
    pistas = extraer_pistas(ZIPS_REALES[0], tmp_path)

    assert pistas, "el ZIP debería contener al menos una pista"
    assert all(p.exists() for p in pistas)


@pytest.mark.skipif(not ZIPS_REALES, reason="no hay ZIP de Craig en pruebas/")
def test_descarta_raw_dat_e_info(tmp_path):
    pistas = extraer_pistas(ZIPS_REALES[0], tmp_path)

    nombres = {p.name for p in pistas}
    assert "raw.dat" not in nombres
    assert "info.txt" not in nombres


@pytest.mark.skipif(not ZIPS_REALES, reason="no hay ZIP de Craig en pruebas/")
def test_las_pistas_extraidas_son_audio(tmp_path):
    pistas = extraer_pistas(ZIPS_REALES[0], tmp_path)

    assert all(p.suffix in {".flac", ".ogg", ".oga", ".wav"} for p in pistas)


@pytest.mark.skipif(not ZIPS_REALES, reason="no hay ZIP de Craig en pruebas/")
def test_las_pistas_vienen_ordenadas(tmp_path):
    pistas = extraer_pistas(ZIPS_REALES[0], tmp_path)

    assert [p.name for p in pistas] == sorted(p.name for p in pistas)
