"""Tests de las correcciones necesarias para levantar Craig en Docker.

Las tres salieron de intentar arrancarlo de verdad:

1. El `docker-compose.yml` de Craig pide `image: postgres` sin versión. Hoy eso
   resuelve a PostgreSQL 18, que cambió dónde espera los datos, y el contenedor
   entra en bucle de reinicio.
2. Los archivos de configuración los consume un contenedor Linux. Si Python los
   escribe con los saltos de línea de Windows, el shell falla con
   `line 4: $'\\r': command not found`.
3. Craig declara `restart: always` en db y redis, así que los contenedores
   resucitan al arrancar Docker Desktop. Rolsumen los levanta y los baja con
   la ventana, y no deben arrancar nunca por su cuenta.
"""

from app.config import Credenciales
from app.instalar_craig import (
    COMPOSE_OVERRIDE,
    NOMBRE_OVERRIDE,
    _escribir_para_linux,
    crear_config,
    crear_override,
    sincronizar_credenciales,
)

EJEMPLO = "DISCORD_BOT_TOKEN=\nCLIENT_SECRET=\nDISCORD_APP_ID=\nCLIENT_ID=\nREDIS_HOST=\n"


def preparar(tmp_path):
    (tmp_path / "install.config.example").write_text(EJEMPLO, encoding="utf-8")
    return tmp_path


def completas():
    return Credenciales(token_bot="t", secreto_cliente="s", id_aplicacion="1")


# --- Versión de PostgreSQL ---------------------------------------------------


def test_el_override_fija_la_version_de_postgres(tmp_path):
    ruta = crear_override(tmp_path)

    contenido = ruta.read_text(encoding="utf-8")
    assert "postgres:16" in contenido


def test_el_override_se_llama_como_espera_docker_compose():
    # Docker Compose sólo fusiona automáticamente este nombre exacto.
    assert NOMBRE_OVERRIDE == "docker-compose.override.yml"


def test_el_override_explica_por_que_existe():
    # Sin la explicación, el siguiente que lo lea lo borrará por parecer inútil.
    assert "18" in COMPOSE_OVERRIDE
    assert "/var/lib/postgresql/data" in COMPOSE_OVERRIDE


# --- Política de reinicio ----------------------------------------------------


def test_el_override_desactiva_el_reinicio_automatico(tmp_path):
    # Craig trae `restart: always` en db y redis. Sin anularlo, los contenedores
    # vuelven solos al arrancar Docker Desktop, con Rolsumen cerrado.
    contenido = crear_override(tmp_path).read_text(encoding="utf-8")

    for servicio in ("db", "redis", "craig"):
        assert f"  {servicio}:" in contenido
    # Entre comillas a propósito: en YAML `no` sin comillas es el booleano False.
    assert contenido.count('restart: "no"') == 3


def test_el_override_no_encadena_el_bot_al_reinicio_de_la_base_de_datos(tmp_path):
    contenido = crear_override(tmp_path).read_text(encoding="utf-8")

    assert "restart: false" in contenido
    assert "restart: true" not in contenido


def test_ningun_servicio_se_reinicia_siempre():
    # Solo las líneas efectivas: los comentarios citan `restart: always` para
    # explicar que es justo lo que se está anulando.
    efectivas = [
        l for l in COMPOSE_OVERRIDE.splitlines() if not l.strip().startswith("#")
    ]
    assert not [l for l in efectivas if "restart: always" in l]


def test_no_sobrescribe_un_override_existente(tmp_path):
    ruta = tmp_path / NOMBRE_OVERRIDE
    ruta.write_text("mio", encoding="utf-8")

    crear_override(tmp_path)

    assert ruta.read_text(encoding="utf-8") == "mio"


def test_forzar_regenera_el_override(tmp_path):
    ruta = tmp_path / NOMBRE_OVERRIDE
    ruta.write_text("mio", encoding="utf-8")

    crear_override(tmp_path, forzar=True)

    assert "postgres:16" in ruta.read_text(encoding="utf-8")


# --- Saltos de línea ---------------------------------------------------------


def _sin_crlf(ruta) -> bool:
    datos = ruta.read_bytes()
    return b"\r\n" not in datos


def test_escribe_con_saltos_unix(tmp_path):
    ruta = tmp_path / "archivo"

    _escribir_para_linux(ruta, "una\ndos\ntres\n")

    assert _sin_crlf(ruta)


def test_convierte_los_saltos_de_windows(tmp_path):
    ruta = tmp_path / "archivo"

    _escribir_para_linux(ruta, "una\r\ndos\r\n")

    assert _sin_crlf(ruta)


def test_install_config_se_escribe_sin_crlf(tmp_path):
    destino = preparar(tmp_path)

    config = crear_config(destino, app_id="123")

    assert _sin_crlf(config)


def test_el_override_se_escribe_sin_crlf(tmp_path):
    ruta = crear_override(tmp_path)

    assert _sin_crlf(ruta)


def test_sincronizar_no_reintroduce_crlf(tmp_path):
    destino = preparar(tmp_path)
    crear_config(destino, app_id="123")

    sincronizar_credenciales(completas(), destino)

    assert _sin_crlf(destino / "install.config")


def test_sincronizar_sobre_un_config_con_crlf_lo_arregla(tmp_path):
    destino = preparar(tmp_path)
    (destino / "install.config").write_bytes(b"DISCORD_BOT_TOKEN=\r\nCLIENT_SECRET=\r\n")

    sincronizar_credenciales(completas(), destino)

    assert _sin_crlf(destino / "install.config")
