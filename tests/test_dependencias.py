"""Tests de la localización de herramientas externas.

Estos tests cubren el fallo que apareció en la prueba de extremo a extremo:
Whisper lanza ffmpeg por su cuenta y, si no está en el PATH, el error que
devuelve es un "[WinError 2]" que no menciona ffmpeg por ninguna parte.
"""

import os
import shutil

from app import dependencias


def test_localiza_ffmpeg_si_esta_en_el_path():
    if shutil.which("ffmpeg") is None:
        # Si no está instalado, esta comprobación no aplica.
        return

    assert dependencias.localizar("ffmpeg") is not None


def test_lo_encuentra_aunque_el_path_este_vacio(monkeypatch):
    if shutil.which("ffmpeg") is None:
        return

    monkeypatch.setenv("PATH", "")

    # Con el PATH vacío ya no se ve, pero debe localizarse igualmente.
    assert shutil.which("ffmpeg") is None
    assert dependencias.localizar("ffmpeg") is not None


def test_asegurar_en_path_lo_deja_invocable(monkeypatch):
    if shutil.which("ffmpeg") is None:
        return

    monkeypatch.setenv("PATH", "")

    assert dependencias.asegurar_en_path("ffmpeg") is True
    assert shutil.which("ffmpeg") is not None


def test_un_ejecutable_inexistente_no_se_encuentra():
    assert dependencias.localizar("no_existe_este_programa_xyz") is None
    assert dependencias.asegurar_en_path("no_existe_este_programa_xyz") is False


def test_la_ayuda_explica_como_instalar_ffmpeg(monkeypatch):
    # Se simula que no está por ninguna parte.
    monkeypatch.setattr(dependencias, "asegurar_en_path", lambda _="ffmpeg": False)

    estado = dependencias.comprobar_ffmpeg()

    assert estado.disponible is False
    assert "ffmpeg" in estado.ayuda.lower()
    assert "winget" in estado.ayuda.lower()


def test_comprobar_todo_devuelve_ffmpeg_y_gpu():
    nombres = {d.nombre for d in dependencias.comprobar_todo()}

    assert "ffmpeg" in nombres
    assert nombres & {"GPU", "PyTorch"}


def test_preparar_entorno_no_rompe_si_falta_todo(monkeypatch):
    monkeypatch.setenv("PATH", "")

    # No debe lanzar excepción pase lo que pase.
    dependencias.preparar_entorno()


def test_no_duplica_la_carpeta_en_el_path(monkeypatch):
    if shutil.which("ffmpeg") is None:
        return

    monkeypatch.setenv("PATH", "")
    dependencias.asegurar_en_path("ffmpeg")
    path_tras_una = os.environ["PATH"]

    dependencias.asegurar_en_path("ffmpeg")

    # La segunda llamada ya lo encuentra y no vuelve a tocar el PATH.
    assert os.environ["PATH"] == path_tras_una
