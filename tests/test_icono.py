"""Tests del icono y del acceso directo.

El icono no es decoración: sin él, la barra de tareas muestra el icono genérico
de Python y la aplicación queda agrupada bajo el intérprete.
"""

import struct
import sys

import pytest

from app import acceso_directo
from app import config as cfg
from app import gui


def test_el_icono_esta_en_el_repositorio():
    assert cfg.RUTA_ICONO.exists(), (
        f"Falta {cfg.RUTA_ICONO}. Se regenera con: "
        "python -m app.recursos.generar_icono"
    )


def _tamanos_del_ico(ruta):
    """Lee la cabecera del .ico sin depender de Pillow."""
    datos = ruta.read_bytes()
    reserva, tipo, cuantos = struct.unpack("<HHH", datos[:6])
    assert reserva == 0 and tipo == 1, "no parece un .ico"
    tamanos = []
    for i in range(cuantos):
        ancho, alto = datos[6 + i * 16], datos[7 + i * 16]
        # En el formato ICO, 0 significa 256.
        tamanos.append((ancho or 256, alto or 256))
    return tamanos


def test_el_icono_trae_los_tamanos_que_windows_pide():
    tamanos = _tamanos_del_ico(cfg.RUTA_ICONO)

    # 16 es el de la barra de tareas y 256 el del explorador en vista grande.
    assert (16, 16) in tamanos
    assert (32, 32) in tamanos
    assert (256, 256) in tamanos


def test_todas_las_imagenes_son_cuadradas():
    for ancho, alto in _tamanos_del_ico(cfg.RUTA_ICONO):
        assert ancho == alto


@pytest.mark.skipif(sys.platform != "win32", reason="sólo aplica a Windows")
def test_el_identificador_de_aplicacion_se_fija():
    """Sin esto la barra de tareas usa el icono de Python, no el nuestro."""
    import ctypes

    gui._identificar_aplicacion()

    buffer = ctypes.c_wchar_p()
    resultado = ctypes.windll.shell32.GetCurrentProcessExplicitAppUserModelID(
        ctypes.byref(buffer)
    )

    assert resultado == 0, "no se pudo leer el identificador"
    assert buffer.value == gui.ID_APLICACION


def test_el_acceso_directo_apunta_al_interprete_sin_consola(monkeypatch, tmp_path):
    """`pythonw.exe` evita la ventana de consola negra detrás de la aplicación."""
    falso = tmp_path / "pythonw.exe"
    falso.write_text("", encoding="utf-8")
    monkeypatch.setattr(acceso_directo.sys, "executable", str(tmp_path / "python.exe"))

    assert acceso_directo.interprete_sin_consola() == falso


def test_si_no_hay_pythonw_se_usa_el_interprete_normal(monkeypatch, tmp_path):
    normal = tmp_path / "python.exe"
    normal.write_text("", encoding="utf-8")
    monkeypatch.setattr(acceso_directo.sys, "executable", str(normal))

    assert acceso_directo.interprete_sin_consola() == normal


@pytest.mark.skipif(sys.platform != "win32", reason="los .lnk son de Windows")
def test_se_crea_un_acceso_directo_utilizable(tmp_path):
    destino = acceso_directo.crear(tmp_path / "Rolsumen.lnk")

    assert destino.exists()
    assert destino.stat().st_size > 0


def test_fuera_de_windows_se_explica_la_alternativa(monkeypatch, tmp_path):
    monkeypatch.setattr(acceso_directo.sys, "platform", "linux")

    with pytest.raises(RuntimeError, match="python -m app.main"):
        acceso_directo.crear(tmp_path / "x.lnk")
