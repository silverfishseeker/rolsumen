"""Tests de las piezas del orquestador que no necesitan Docker ni Whisper."""

from pathlib import Path

import pytest

from app.pipeline.orquestador import _formatear_duracion, _guardar_resumen


def test_duracion_en_minutos():
    assert _formatear_duracion(125) == "2 min"


def test_duracion_con_horas():
    assert _formatear_duracion(3 * 3600 + 25 * 60) == "3 h 25 min"


def test_duracion_de_una_sesion_larga():
    assert _formatear_duracion(4 * 3600 + 5 * 60) == "4 h 5 min"


def test_duracion_cero():
    assert _formatear_duracion(0) == "0 min"


def test_guarda_el_resumen_en_la_carpeta_principal(tmp_path):
    destino = tmp_path / "resumenes"

    ruta = _guardar_resumen("contenido", "sesion.md", [destino], lambda _: None)

    assert ruta == destino / "sesion.md"
    assert ruta.read_text(encoding="utf-8") == "contenido"


def test_duplica_el_resumen_en_la_carpeta_extra(tmp_path):
    principal = tmp_path / "datos"
    extra = tmp_path / "mi_carpeta"

    ruta = _guardar_resumen("crónica", "s.md", [principal, extra], lambda _: None)

    # Ambas copias deben existir y ser idénticas.
    assert (principal / "s.md").read_text(encoding="utf-8") == "crónica"
    assert (extra / "s.md").read_text(encoding="utf-8") == "crónica"
    # La ruta devuelta es la principal.
    assert ruta == principal / "s.md"


def test_crea_las_carpetas_si_no_existen(tmp_path):
    destino = tmp_path / "no" / "existe" / "todavia"

    _guardar_resumen("x", "s.md", [destino], lambda _: None)

    assert (destino / "s.md").exists()


def test_si_falla_la_carpeta_extra_el_resumen_no_se_pierde(tmp_path):
    principal = tmp_path / "datos"
    # Una ruta inválida en Windows: el carácter '?' no se admite.
    invalida = Path("Z:\\ruta?invalida\\no")

    avisos = []
    ruta = _guardar_resumen("crónica", "s.md", [principal, invalida], avisos.append)

    assert ruta == principal / "s.md"
    assert ruta.exists()
    assert any("no se pudo escribir" in a.lower() for a in avisos)


def test_si_fallan_todos_los_destinos_se_lanza_error(tmp_path):
    invalida = Path("Z:\\ruta?invalida\\no")

    with pytest.raises(OSError):
        _guardar_resumen("x", "s.md", [invalida], lambda _: None)
