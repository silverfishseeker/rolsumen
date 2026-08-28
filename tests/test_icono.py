"""Tests del icono y del acceso directo.

El icono no es decoración: sin él, la barra de tareas muestra el icono genérico
de Python y la aplicación queda agrupada bajo el intérprete.
"""

import struct
import sys

import pytest

from pathlib import Path

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


def test_se_prefiere_un_interprete_no_empaquetado(monkeypatch, tmp_path):
    """El de Microsoft Store arrastra la identidad MSIX del paquete.

    Windows le impone entonces el icono del paquete e ignora lo que declare el
    proceso, así que en la barra de tareas se ve el de Python. Un intérprete
    normal no tiene ese problema.
    """
    normal = tmp_path / "Python310" / "pythonw.exe"
    normal.parent.mkdir()
    normal.write_text("", encoding="utf-8")
    tienda = tmp_path / "WindowsApps" / "pythonw.exe"
    tienda.parent.mkdir()
    tienda.write_text("", encoding="utf-8")

    monkeypatch.setattr(acceso_directo, "candidatos", lambda: [tienda, normal])

    assert acceso_directo.interprete_sin_consola() == normal


def test_si_solo_hay_uno_empaquetado_se_usa_ese(monkeypatch, tmp_path):
    # Peor icono, pero la aplicación tiene que poder abrirse igualmente.
    tienda = tmp_path / "WindowsApps" / "pythonw.exe"
    tienda.parent.mkdir()
    tienda.write_text("", encoding="utf-8")
    monkeypatch.setattr(acceso_directo, "candidatos", lambda: [tienda])

    assert acceso_directo.interprete_sin_consola() == tienda


def test_se_reconoce_lo_empaquetado_por_su_carpeta():
    empaquetado = Path("C:/x/WindowsApps/pythonw.exe")
    normal = Path("C:/Users/x/Programs/Python310/pythonw.exe")

    assert acceso_directo._es_empaquetado(empaquetado)
    assert not acceso_directo._es_empaquetado(normal)


def test_no_se_prestan_paquetes_si_el_interprete_ya_los_tiene(monkeypatch, tmp_path):
    otro = tmp_path / "pythonw.exe"
    otro.write_text("", encoding="utf-8")
    monkeypatch.setattr(acceso_directo, "_tiene_las_dependencias", lambda _i: True)

    assert acceso_directo.paquetes_prestados(otro) == ""


def test_se_prestan_los_paquetes_del_interprete_actual(monkeypatch, tmp_path):
    """Evita duplicar varios gigas de torch para un intérprete distinto."""
    otro = tmp_path / "pythonw.exe"
    otro.write_text("", encoding="utf-8")
    monkeypatch.setattr(acceso_directo, "_tiene_las_dependencias", lambda _i: False)
    monkeypatch.setattr(
        acceso_directo.site, "getusersitepackages", lambda: "C:/paquetes"
    )

    assert acceso_directo.paquetes_prestados(otro) == "C:/paquetes"


@pytest.mark.skipif(sys.platform != "win32", reason="los .lnk son de Windows")
def test_se_crea_un_acceso_directo_utilizable(tmp_path):
    destino = acceso_directo.crear(tmp_path / "Rolsumen.lnk")

    assert destino.exists()
    assert destino.stat().st_size > 0


def test_fuera_de_windows_se_explica_la_alternativa(monkeypatch, tmp_path):
    monkeypatch.setattr(acceso_directo.sys, "platform", "linux")

    with pytest.raises(RuntimeError, match="python -m app.main"):
        acceso_directo.crear(tmp_path / "x.lnk")


# --- Sondeo de dependencias y menú Inicio ------------------------------------


def test_la_sonda_no_hereda_las_variables_de_python(monkeypatch):
    """El Python de Microsoft Store exporta PYTHONUSERBASE.

    Los hijos lo heredan y ven sus paquetes, así que sondear con esa variable
    puesta decía que el otro intérprete tenía las dependencias cuando no las
    tenía. Al abrir la aplicación con doble clic se quedaba sin torch, es decir,
    sin GPU.
    """
    monkeypatch.setenv("PYTHONUSERBASE", "C:/de-la-store")
    monkeypatch.setenv("PYTHONPATH", "C:/otra")
    monkeypatch.setenv("PATH", "C:/windows")

    limpio = acceso_directo._entorno_limpio()

    assert not [c for c in limpio if c.startswith("PYTHON")]
    assert limpio.get("PATH") == "C:/windows", "el resto del entorno se conserva"


def test_la_sonda_se_ejecuta_con_el_entorno_limpio(monkeypatch, tmp_path):
    recibido = {}

    def falso_run(argumentos, **kwargs):
        recibido.update(kwargs)

        class Falso:
            returncode = 0

        return Falso()

    monkeypatch.setattr(acceso_directo.subprocess, "run", falso_run)
    acceso_directo._tiene_las_dependencias(tmp_path / "pythonw.exe")

    assert "env" in recibido, "sin env explícito hereda el del padre"
    assert not [c for c in recibido["env"] if c.startswith("PYTHON")]


def test_el_menu_inicio_apunta_a_la_carpeta_de_programas(monkeypatch, tmp_path):
    """Sólo lo que vive ahí sale en la lista de aplicaciones de Windows.

    Y sólo desde esa lista se puede anclar a Inicio de forma fiable.
    """
    monkeypatch.setenv("APPDATA", str(tmp_path))

    ruta = acceso_directo.menu_inicio()

    assert ruta == tmp_path / "Microsoft" / "Windows" / "Start Menu" / "Programs"
