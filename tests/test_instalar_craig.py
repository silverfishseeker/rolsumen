"""Tests del instalador de Craig (sin descargar nada de la red)."""

from app.instalar_craig import AJUSTES_DOCKER, _sustituir, crear_config, valores_pendientes

EJEMPLO = """\
DISCORD_BOT_TOKEN=
DISCORD_APP_ID=
CLIENT_ID=
CLIENT_SECRET=
REDIS_HOST=
REDIS_PORT=
DATABASE_URL=\\"postgresql://$U:$P@localhost:5432/$D?schema=public\\"
"""


def preparar(tmp_path):
    (tmp_path / "install.config.example").write_text(EJEMPLO, encoding="utf-8")
    return tmp_path


def test_sustituye_una_clave_existente():
    resultado = _sustituir("A=1\nB=2\n", "B", "nuevo")

    assert "B=nuevo" in resultado
    assert "A=1" in resultado


def test_anade_la_clave_si_no_existe():
    resultado = _sustituir("A=1\n", "NUEVA", "valor")

    assert "NUEVA=valor" in resultado


def test_no_toca_claves_de_nombre_parecido():
    resultado = _sustituir("REDIS_HOST=\nREDIS_HOST_EXTRA=x\n", "REDIS_HOST", "redis")

    assert "REDIS_HOST=redis" in resultado
    assert "REDIS_HOST_EXTRA=x" in resultado


def test_apunta_la_base_de_datos_al_servicio_de_docker(tmp_path):
    destino = preparar(tmp_path)

    config = crear_config(destino, app_id="123")
    contenido = config.read_text(encoding="utf-8")

    # El ejemplo de Craig apunta a localhost, que no funciona dentro de Docker.
    assert "@db:5432" in contenido
    assert "@localhost:5432" not in contenido


def test_apunta_redis_al_servicio_de_docker(tmp_path):
    destino = preparar(tmp_path)

    config = crear_config(destino, app_id="123")
    contenido = config.read_text(encoding="utf-8")

    assert "REDIS_HOST=redis" in contenido
    assert "REDIS_PORT=6379" in contenido


def test_rellena_el_identificador_publico_de_la_aplicacion(tmp_path):
    destino = preparar(tmp_path)

    config = crear_config(destino, app_id="999888777")
    contenido = config.read_text(encoding="utf-8")

    assert "DISCORD_APP_ID=999888777" in contenido
    assert "CLIENT_ID=999888777" in contenido


def test_no_inventa_los_secretos(tmp_path):
    destino = preparar(tmp_path)

    config = crear_config(destino, app_id="123")
    contenido = config.read_text(encoding="utf-8")

    assert "DISCORD_BOT_TOKEN=\n" in contenido
    assert "CLIENT_SECRET=\n" in contenido


def test_detecta_que_faltan_los_secretos(tmp_path):
    destino = preparar(tmp_path)
    config = crear_config(destino, app_id="123")

    pendientes = valores_pendientes(config)

    assert set(pendientes) == {"DISCORD_BOT_TOKEN", "CLIENT_SECRET"}


def test_sin_pendientes_cuando_esta_todo_relleno(tmp_path):
    destino = preparar(tmp_path)
    config = crear_config(destino, app_id="123")
    contenido = config.read_text(encoding="utf-8")
    contenido = contenido.replace("DISCORD_BOT_TOKEN=", "DISCORD_BOT_TOKEN=abc")
    contenido = contenido.replace("CLIENT_SECRET=", "CLIENT_SECRET=xyz")
    config.write_text(contenido, encoding="utf-8")

    assert valores_pendientes(config) == []


def test_no_sobrescribe_una_config_existente(tmp_path):
    destino = preparar(tmp_path)
    (destino / "install.config").write_text("MIO=1\n", encoding="utf-8")

    config = crear_config(destino, app_id="123")

    assert config.read_text(encoding="utf-8") == "MIO=1\n"


def test_forzar_sobrescribe(tmp_path):
    destino = preparar(tmp_path)
    (destino / "install.config").write_text("MIO=1\n", encoding="utf-8")

    config = crear_config(destino, app_id="123", forzar=True)

    assert "DISCORD_APP_ID=123" in config.read_text(encoding="utf-8")


def test_todos_los_ajustes_de_docker_se_aplican(tmp_path):
    destino = preparar(tmp_path)

    config = crear_config(destino, app_id="123")
    contenido = config.read_text(encoding="utf-8")

    for clave in AJUSTES_DOCKER:
        assert f"{clave}=" in contenido
