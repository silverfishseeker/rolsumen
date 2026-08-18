"""Tests de las credenciales de Discord en config.ini y su sincronización.

El usuario mantiene un único archivo de configuración (`app/config.ini`); el
`install.config` de Craig se genera a partir de él.
"""

from app import config as cfg
from app.config import Credenciales
from app.instalar_craig import sincronizar_credenciales

EJEMPLO = """\
DISCORD_BOT_TOKEN=
DISCORD_APP_ID=
CLIENT_ID=
CLIENT_SECRET=
REDIS_HOST=
DATABASE_URL=\\"postgresql://$U:$P@localhost:5432/$D?schema=public\\"
"""


def preparar(tmp_path):
    (tmp_path / "install.config.example").write_text(EJEMPLO, encoding="utf-8")
    return tmp_path


def completas():
    return Credenciales(
        token_bot="tok_secreto",
        secreto_cliente="sec_secreto",
        id_aplicacion="1539028879342047263",
    )


def test_credenciales_vacias_no_estan_completas():
    assert Credenciales().completas is False


def test_credenciales_completas():
    assert completas().completas is True


def test_indica_exactamente_lo_que_falta():
    parciales = Credenciales(id_aplicacion="123")

    assert parciales.faltantes() == ["token_bot", "secreto_cliente"]


def test_se_leen_del_config_ini(tmp_path):
    ruta = tmp_path / "config.ini"
    ruta.write_text(
        "[discord]\n"
        "token_bot = abc\n"
        "secreto_cliente = xyz\n"
        "id_aplicacion = 999\n",
        encoding="utf-8",
    )

    configuracion = cfg.cargar(ruta)

    assert configuracion.discord.token_bot == "abc"
    assert configuracion.discord.secreto_cliente == "xyz"
    assert configuracion.discord.id_aplicacion == "999"


def test_sin_seccion_discord_quedan_vacias(tmp_path):
    ruta = tmp_path / "config.ini"
    ruta.write_text("[general]\n", encoding="utf-8")

    assert cfg.cargar(ruta).discord.completas is False


def test_sincroniza_las_credenciales_en_el_config_de_craig(tmp_path):
    destino = preparar(tmp_path)

    ok, _ = sincronizar_credenciales(completas(), destino)
    contenido = (destino / "install.config").read_text(encoding="utf-8")

    assert ok is True
    assert "DISCORD_BOT_TOKEN=tok_secreto" in contenido
    assert "CLIENT_SECRET=sec_secreto" in contenido
    assert "DISCORD_APP_ID=1539028879342047263" in contenido
    assert "CLIENT_ID=1539028879342047263" in contenido


def test_al_sincronizar_tambien_aplica_los_ajustes_de_docker(tmp_path):
    destino = preparar(tmp_path)

    sincronizar_credenciales(completas(), destino)
    contenido = (destino / "install.config").read_text(encoding="utf-8")

    assert "@db:5432" in contenido
    assert "@localhost:5432" not in contenido


def test_no_sincroniza_si_faltan_credenciales(tmp_path):
    destino = preparar(tmp_path)

    ok, mensaje = sincronizar_credenciales(Credenciales(), destino)

    assert ok is False
    assert "config.ini" in mensaje
    assert not (destino / "install.config").exists()


def test_actualiza_un_install_config_existente(tmp_path):
    destino = preparar(tmp_path)
    (destino / "install.config").write_text(
        "DISCORD_BOT_TOKEN=viejo\nCLIENT_SECRET=viejo\nOTRA_COSA=conservar\n",
        encoding="utf-8",
    )

    sincronizar_credenciales(completas(), destino)
    contenido = (destino / "install.config").read_text(encoding="utf-8")

    assert "DISCORD_BOT_TOKEN=tok_secreto" in contenido
    assert "viejo" not in contenido
    # Lo que no gestionamos nosotros no se toca.
    assert "OTRA_COSA=conservar" in contenido


def test_sin_craig_instalado_avisa_de_como_instalarlo(tmp_path):
    ok, mensaje = sincronizar_credenciales(completas(), tmp_path / "no_existe")

    assert ok is False
    assert "instalar_craig" in mensaje


def test_cambiar_el_id_de_aplicacion_se_propaga(tmp_path):
    destino = preparar(tmp_path)
    otras = Credenciales(
        token_bot="t", secreto_cliente="s", id_aplicacion="111222333"
    )

    sincronizar_credenciales(otras, destino)
    contenido = (destino / "install.config").read_text(encoding="utf-8")

    assert "DISCORD_APP_ID=111222333" in contenido
    assert "CLIENT_ID=111222333" in contenido


def test_el_config_de_ejemplo_trae_la_seccion_discord(tmp_path):
    ruta = tmp_path / "config.ini"
    cfg.crear_config_si_falta(ruta)

    configuracion = cfg.cargar(ruta)

    # El identificador viene puesto; los secretos no (los pone el usuario).
    assert configuracion.discord.id_aplicacion
    assert not configuracion.discord.token_bot
    assert not configuracion.discord.secreto_cliente
