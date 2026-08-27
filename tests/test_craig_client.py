"""Tests del cliente de Craig que no requieren Docker en marcha.

`extraer_pistas` se prueba contra un ZIP construido aquí mismo con la misma
estructura que produce el `cook` de Craig. Antes se usaban ZIP reales dejados
en una carpeta del proyecto, pero eso hacía que los tests se saltaran en
silencio si esos archivos desaparecían.
"""

import zipfile
from datetime import datetime
from pathlib import Path

import pytest

from app.craig_client import Grabacion, _fecha, extraer_pistas


def zip_de_craig(destino: Path, pistas=("1.flac", "2.flac", "3.flac")) -> Path:
    """Crea un ZIP con la estructura que devuelve `cook.sh`.

    Craig mete una pista de audio por participante más dos archivos que no son
    audio: `info.txt` (a veces vacío) y `raw.dat` (el volcado crudo).
    """
    ruta = destino / "grabacion.zip"
    with zipfile.ZipFile(ruta, "w") as zf:
        for nombre in pistas:
            zf.writestr(nombre, b"audio falso")
        zf.writestr("info.txt", b"")
        zf.writestr("raw.dat", b"volcado crudo")
    return ruta


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
        creada=datetime(2026, 8, 18, 22, 30),
        terminada=None,
    )

    assert grabacion.etiqueta_fecha == "2026-08-18"


def test_etiqueta_de_fecha_usa_el_final_si_no_hay_inicio():
    grabacion = Grabacion(
        id="abc", creada=None, terminada=datetime(2026, 1, 5)
    )

    assert grabacion.etiqueta_fecha == "2026-01-05"


def test_etiqueta_de_fecha_sin_fechas():
    grabacion = Grabacion(id="abc", creada=None, terminada=None)

    assert grabacion.etiqueta_fecha == "sin-fecha"


def test_extrae_las_pistas_de_audio(tmp_path):
    ruta = zip_de_craig(tmp_path)

    pistas = extraer_pistas(ruta, tmp_path / "salida")

    assert [p.name for p in pistas] == ["1.flac", "2.flac", "3.flac"]
    assert all(p.exists() for p in pistas)


def test_descarta_raw_dat_e_info(tmp_path):
    # No son audio: transcribirlos fallaría o daría basura.
    ruta = zip_de_craig(tmp_path)

    nombres = {p.name for p in extraer_pistas(ruta, tmp_path / "salida")}

    assert "raw.dat" not in nombres
    assert "info.txt" not in nombres


def test_las_pistas_vienen_ordenadas(tmp_path):
    # Craig las numera; el orden importa para emparejarlas con los usuarios.
    ruta = zip_de_craig(tmp_path, pistas=("3.flac", "1.flac", "2.flac"))

    pistas = extraer_pistas(ruta, tmp_path / "salida")

    assert [p.name for p in pistas] == ["1.flac", "2.flac", "3.flac"]


def test_admite_pistas_con_nombre_de_usuario(tmp_path):
    # Los ZIP de la web pública de Craig sí llevan el usuario en el nombre.
    ruta = zip_de_craig(tmp_path, pistas=("1-caliece.flac", "2-silverfishlord.flac"))

    pistas = extraer_pistas(ruta, tmp_path / "salida")

    assert [p.name for p in pistas] == ["1-caliece.flac", "2-silverfishlord.flac"]


def test_un_zip_solo_con_relleno_no_devuelve_pistas(tmp_path):
    ruta = zip_de_craig(tmp_path, pistas=())

    assert extraer_pistas(ruta, tmp_path / "salida") == []


def test_un_archivo_que_no_es_zip_da_error_claro(tmp_path):
    from app.craig_client import ErrorCraig

    falso = tmp_path / "roto.zip"
    falso.write_bytes(b"esto no es un zip")

    with pytest.raises(ErrorCraig, match="no es un ZIP"):
        extraer_pistas(falso, tmp_path / "salida")
