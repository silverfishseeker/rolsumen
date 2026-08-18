"""Tests del proceso de extracción de audio (`cook`) de Craig.

El bug que motiva estos tests: `cook.sh` usa `at` para programar el borrado de
sus temporales dentro de dos horas. Si el demonio `atd` no está corriendo —y la
imagen de Craig no lo arranca—, `at` falla, el script aborta y el ZIP sale
**vacío**, sin ningún mensaje que explique la causa.
"""

from pathlib import Path

import pytest

from app import craig_client
from app.craig_client import ErrorCraig, cocinar


class ProcesoFalso:
    def __init__(self, returncode=0, stderr=b""):
        self.returncode = returncode
        self.stderr = stderr


def test_se_asegura_atd_antes_de_cocinar(tmp_path, monkeypatch):
    llamadas = []

    monkeypatch.setattr(
        craig_client, "asegurar_atd", lambda *a, **k: llamadas.append("atd") or True
    )

    def falso_run(argumentos, **kwargs):
        # Simula un cook que escribe algo en el archivo de salida.
        kwargs["stdout"].write(b"contenido")
        return ProcesoFalso()

    monkeypatch.setattr(craig_client.subprocess, "run", falso_run)

    cocinar("abc", tmp_path / "salida.zip")

    assert llamadas == ["atd"], "hay que arrancar atd antes de cada cook"


def test_un_zip_vacio_se_detecta_como_error(tmp_path, monkeypatch):
    # Es exactamente lo que ocurría sin atd: código de salida 0 pero 0 bytes.
    monkeypatch.setattr(craig_client, "asegurar_atd", lambda *a, **k: True)
    monkeypatch.setattr(
        craig_client.subprocess, "run", lambda *a, **k: ProcesoFalso()
    )

    with pytest.raises(ErrorCraig, match="no produjo audio"):
        cocinar("abc", tmp_path / "salida.zip")


def test_un_zip_vacio_no_se_deja_en_disco(tmp_path, monkeypatch):
    monkeypatch.setattr(craig_client, "asegurar_atd", lambda *a, **k: True)
    monkeypatch.setattr(
        craig_client.subprocess, "run", lambda *a, **k: ProcesoFalso()
    )

    destino = tmp_path / "salida.zip"
    with pytest.raises(ErrorCraig):
        cocinar("abc", destino)

    assert not destino.exists(), "un ZIP inservible no debe quedarse ahí"


def test_el_error_del_cook_llega_al_usuario(tmp_path, monkeypatch):
    monkeypatch.setattr(craig_client, "asegurar_atd", lambda *a, **k: True)
    monkeypatch.setattr(
        craig_client.subprocess,
        "run",
        lambda *a, **k: ProcesoFalso(returncode=1, stderr=b"algo fallo dentro"),
    )

    with pytest.raises(ErrorCraig, match="algo fallo dentro"):
        cocinar("abc", tmp_path / "salida.zip")


def test_cocinar_crea_la_carpeta_de_destino(tmp_path, monkeypatch):
    monkeypatch.setattr(craig_client, "asegurar_atd", lambda *a, **k: True)

    def falso_run(argumentos, **kwargs):
        kwargs["stdout"].write(b"x" * 100)
        return ProcesoFalso()

    monkeypatch.setattr(craig_client.subprocess, "run", falso_run)

    destino = tmp_path / "no" / "existe" / "salida.zip"
    resultado = cocinar("abc", destino)

    assert resultado.exists()


def test_asegurar_atd_no_revienta_sin_docker(monkeypatch):
    def explota(*a, **k):
        raise FileNotFoundError("no hay docker")

    monkeypatch.setattr(craig_client.subprocess, "run", explota)

    # Debe devolver False, no lanzar: el error real lo dará el cook después.
    assert craig_client.asegurar_atd(Path(".")) is False
