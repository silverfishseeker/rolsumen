"""Craig trae doce comandos y aquí sólo se usa uno.

`/join` empieza a grabar; para terminar se pulsa el botón «Stop» del mensaje
que publica el propio bot. Ese botón NO depende del comando `/stop`: lo atiende
`handleRecordingInteraction`, que llama directamente a `recording.stop()`.
"""

import pytest

from app.instalar_craig import (
    COMANDOS_QUE_SE_QUEDAN,
    DIR_COMANDOS,
    MARCA_FIN,
    MARCA_PENDIENTE,
    SONDA,
    simplificar_comandos,
)

TODOS = (
    "autorecord.ts", "bless.ts", "features.ts", "info.ts", "join.ts",
    "note.ts", "recordings.ts", "serversettings.ts", "stop.ts",
    "unbless.ts", "voice-test.ts", "webapp.ts",
)


@pytest.fixture
def clon(tmp_path):
    carpeta = tmp_path / DIR_COMANDOS
    carpeta.mkdir(parents=True)
    for nombre in TODOS:
        (carpeta / nombre).write_text("// comando", encoding="utf-8")
    return tmp_path


def nombres(carpeta):
    return sorted(p.name for p in carpeta.glob("*.ts"))


def test_solo_sobrevive_join(clon):
    simplificar_comandos(clon)

    assert nombres(clon / DIR_COMANDOS) == ["join.ts"]


def test_dice_cuales_ha_quitado(clon):
    borrados = simplificar_comandos(clon)

    assert "stop" in borrados and "bless" in borrados
    assert "join" not in borrados
    assert len(borrados) == len(TODOS) - 1


def test_es_idempotente(clon):
    simplificar_comandos(clon)

    assert simplificar_comandos(clon) == [], "la segunda vez no queda nada que borrar"


def test_sin_carpeta_de_comandos_no_revienta(tmp_path):
    # Craig todavía sin clonar, por ejemplo.
    assert simplificar_comandos(tmp_path) == []


def test_no_se_toca_nada_que_no_sea_un_comando(clon):
    carpeta = clon / DIR_COMANDOS
    (carpeta / "LEEME.md").write_text("no soy un comando", encoding="utf-8")

    simplificar_comandos(clon)

    assert (carpeta / "LEEME.md").exists()


def test_la_sonda_comprueba_las_dos_cosas():
    """Redis y los comandos: si sólo mirase una, la otra se colaría."""
    assert "redis" in SONDA
    assert DIR_COMANDOS in SONDA
    assert COMANDOS_QUE_SE_QUEDAN[0] in SONDA


def test_la_sonda_demuestra_que_se_ejecuto():
    # Sin marca final no se distingue «todo bien» de «el comando no corrió».
    assert SONDA.rstrip().endswith(MARCA_FIN)
    assert MARCA_PENDIENTE != MARCA_FIN
