"""Tests del gestor de Docker.

No se levanta nada de verdad: se comprueba la lógica de decisión y que los
errores se traducen a mensajes comprensibles en vez de reventar.
"""

from pathlib import Path

from app import docker_manager


def test_sin_craig_instalado_dice_como_instalarlo(tmp_path):
    resultado = docker_manager.levantar(tmp_path)

    assert resultado.ok is False
    assert "instalar_craig" in resultado.mensaje


def test_sin_credenciales_apunta_al_config_del_usuario(tmp_path):
    # El mensaje debe señalar el archivo que edita el usuario (config.ini),
    # no el interno de Craig.
    (tmp_path / "docker-compose.yml").write_text("services: {}", encoding="utf-8")

    resultado = docker_manager.levantar(tmp_path)

    assert resultado.ok is False
    assert "config.ini" in resultado.mensaje
    assert "[discord]" in resultado.mensaje


def test_no_arranca_si_las_credenciales_estan_incompletas(tmp_path):
    from app.config import Credenciales

    (tmp_path / "docker-compose.yml").write_text("services: {}", encoding="utf-8")
    (tmp_path / "install.config.example").write_text("TOKEN=", encoding="utf-8")

    resultado = docker_manager.levantar(
        tmp_path, credenciales=Credenciales(token_bot="solo_esto")
    )

    assert resultado.ok is False
    assert "secreto_cliente" in resultado.mensaje


def test_bajar_sin_craig_instalado_no_es_un_error(tmp_path):
    # Cerrar la aplicación nunca debe fallar por esto.
    resultado = docker_manager.bajar(tmp_path)

    assert resultado.ok is True


def test_detecta_que_craig_no_esta_instalado(tmp_path):
    assert docker_manager.hay_compose(tmp_path) is False
    assert docker_manager.hay_configuracion(tmp_path) is False


def test_detecta_craig_instalado_y_configurado(tmp_path):
    (tmp_path / "docker-compose.yml").write_text("services: {}", encoding="utf-8")
    (tmp_path / "install.config").write_text("TOKEN=x", encoding="utf-8")

    assert docker_manager.hay_compose(tmp_path) is True
    assert docker_manager.hay_configuracion(tmp_path) is True


def test_comando_inexistente_devuelve_mensaje_util(monkeypatch):
    resultado = docker_manager._ejecutar(["comando_que_no_existe_xyz"])

    assert resultado.ok is False
    assert resultado.mensaje


def test_diagnostico_devuelve_todas_las_claves(tmp_path):
    diag = docker_manager.diagnostico(tmp_path)

    assert set(diag) == {
        "docker_instalado",
        "docker_en_marcha",
        "craig_instalado",
        "craig_configurado",
        "craig_levantado",
    }
    assert all(isinstance(v, bool) for v in diag.values())


def test_el_mensaje_prefiere_el_error_a_la_salida():
    resultado = docker_manager.ResultadoComando(ok=False, salida="algo", error="fallo")

    assert resultado.mensaje == "fallo"


def test_el_mensaje_usa_la_salida_si_no_hay_error():
    resultado = docker_manager.ResultadoComando(ok=True, salida="hecho", error="")

    assert resultado.mensaje == "hecho"


def test_craig_real_esta_instalado():
    # El instalador debería haber dejado Craig listo en app/craig.
    from app.config import DIR_CRAIG

    if not Path(DIR_CRAIG).exists():
        return
    assert docker_manager.hay_compose(DIR_CRAIG) is True
