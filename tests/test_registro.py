"""Tests del registro de grabaciones procesadas (idempotencia)."""

from pathlib import Path

from app.pipeline.registro import Registro


def test_registro_vacio_si_no_existe_el_archivo(tmp_path):
    registro = Registro.cargar(tmp_path / "no_existe.json")

    assert registro.entradas == {}
    assert not registro.ya_procesada("cualquiera")


def test_marcar_ok_persiste_entre_cargas(tmp_path):
    ruta = tmp_path / "procesadas.json"

    Registro.cargar(ruta).marcar_ok("abc123", Path("/resumenes/abc.md"))

    assert Registro.cargar(ruta).ya_procesada("abc123")


def test_una_grabacion_con_error_se_reintenta(tmp_path):
    ruta = tmp_path / "procesadas.json"
    registro = Registro.cargar(ruta)

    registro.marcar_error("abc123", "Ollama no responde")

    # No cuenta como procesada: debe volver a intentarse en el próximo arranque.
    assert not Registro.cargar(ruta).ya_procesada("abc123")


def test_un_error_puede_pasar_a_ok_despues(tmp_path):
    ruta = tmp_path / "procesadas.json"
    registro = Registro.cargar(ruta)

    registro.marcar_error("abc", "fallo temporal")
    registro.marcar_ok("abc", Path("/resumenes/abc.md"))

    assert Registro.cargar(ruta).ya_procesada("abc")


def test_guarda_la_ruta_del_resumen(tmp_path):
    ruta = tmp_path / "procesadas.json"

    Registro.cargar(ruta).marcar_ok("abc", Path("/resumenes/sesion.md"))

    entrada = Registro.cargar(ruta).entradas["abc"]
    assert "sesion.md" in entrada.resumen
    assert entrada.fecha_proceso


def test_registro_corrupto_no_impide_arrancar(tmp_path):
    ruta = tmp_path / "procesadas.json"
    ruta.write_text("{esto no es json valido", encoding="utf-8")

    registro = Registro.cargar(ruta)

    assert registro.entradas == {}


def test_varias_grabaciones_conviven(tmp_path):
    ruta = tmp_path / "procesadas.json"
    registro = Registro.cargar(ruta)

    registro.marcar_ok("a", Path("/a.md"))
    registro.marcar_ok("b", Path("/b.md"))
    registro.marcar_error("c", "fallo")

    recargado = Registro.cargar(ruta)
    assert recargado.ya_procesada("a")
    assert recargado.ya_procesada("b")
    assert not recargado.ya_procesada("c")
    assert len(recargado.entradas) == 3
