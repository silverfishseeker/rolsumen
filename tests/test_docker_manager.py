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
        "docker_abriendose",
        "craig_instalado",
        "craig_configurado",
        "craig_levantado",
        "craig_en_marcha",
        "servicios_activos",
    }
    banderas = {c: v for c, v in diag.items() if c != "servicios_activos"}
    assert all(isinstance(v, bool) for v in banderas.values())
    assert isinstance(diag["servicios_activos"], list)


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


# --- Detener sin destruir ----------------------------------------------------


def test_bajar_usa_stop_y_no_down(monkeypatch, tmp_path):
    """`down` borra el contenedor, y con el el marcador /app/.installed.

    Craig hace su instalacion completa al arrancar el contenedor (yarn, prisma,
    compilar los binarios del cook) y la marca ahi. Destruir el contenedor al
    cerrar la aplicacion obliga a repetirla entera: quince minutos en cada
    arranque, medido.
    """
    (tmp_path / "docker-compose.yml").write_text("services: {}", encoding="utf-8")
    ejecutados = []

    monkeypatch.setattr(
        docker_manager,
        "_ejecutar",
        lambda args, cwd=None: ejecutados.append(args)
        or docker_manager.ResultadoComando(True, "", ""),
    )

    docker_manager.bajar(tmp_path)

    assert ejecutados == [["docker", "compose", "stop"]]
    assert not any("down" in a for a in ejecutados[0])


# --- Quién está en pie y quién no -------------------------------------------


def test_craig_en_marcha_mira_su_contenedor_y_no_otro(monkeypatch):
    """`db` y `redis` en pie con craig muerto no es «grabando disponible».

    Era el fallo de la pestaña Estado: con cualquier servicio activo salía en
    verde, aunque el contenedor que graba estuviera caído.
    """
    monkeypatch.setattr(
        docker_manager, "servicios_activos", lambda *a, **k: ["db", "redis"]
    )

    assert docker_manager.esta_levantado() is True, "algo hay en pie"
    assert docker_manager.craig_en_marcha() is False, "pero no se puede grabar"


def test_craig_en_marcha_cuando_su_contenedor_corre(monkeypatch):
    monkeypatch.setattr(
        docker_manager, "servicios_activos", lambda *a, **k: ["db", "redis", "craig"]
    )

    assert docker_manager.craig_en_marcha() is True


def test_con_el_motor_caido_no_se_pregunta_por_los_contenedores(monkeypatch, tmp_path):
    """Cada comando tardaría lo suyo en rendirse, y la respuesta ya se sabe."""
    preguntado = []
    monkeypatch.setattr(docker_manager, "docker_instalado", lambda: True)
    monkeypatch.setattr(docker_manager, "docker_en_marcha", lambda: False)
    monkeypatch.setattr(docker_manager, "docker_abriendose", lambda: True)
    monkeypatch.setattr(
        docker_manager, "servicios_activos",
        lambda *a, **k: preguntado.append(1) or [],
    )

    diag = docker_manager.diagnostico(tmp_path)

    assert preguntado == [], "no se consulta a un motor que no responde"
    assert diag["craig_en_marcha"] is False
    assert diag["docker_abriendose"] is True


def test_abriendose_solo_se_mira_si_el_motor_no_responde(monkeypatch, tmp_path):
    mirado = []
    monkeypatch.setattr(docker_manager, "docker_instalado", lambda: True)
    monkeypatch.setattr(docker_manager, "docker_en_marcha", lambda: True)
    monkeypatch.setattr(docker_manager, "servicios_activos", lambda *a, **k: ["craig"])
    monkeypatch.setattr(
        docker_manager, "docker_abriendose", lambda: mirado.append(1) or True
    )

    diag = docker_manager.diagnostico(tmp_path)

    assert mirado == [], "si responde, está arrancado y no arrancando"
    assert diag["docker_abriendose"] is False


def test_se_reconoce_docker_desktop_abierto(monkeypatch):
    """`tasklist` avisa en el idioma del sistema cuando no hay nada."""
    salidas = {
        "Docker Desktop.exe": "Docker Desktop.exe   26116 Console   1   12.452 KB",
    }

    def falso(argumentos, cwd=None):
        imagen = argumentos[2].partition("eq ")[2]
        return docker_manager.ResultadoComando(True, salidas.get(imagen, ""), "")

    monkeypatch.setattr(docker_manager.sys, "platform", "win32")
    monkeypatch.setattr(docker_manager, "_ejecutar", falso)

    assert docker_manager.docker_abriendose() is True


def test_sin_procesos_de_docker_no_se_esta_abriendo(monkeypatch):
    aviso = "INFORMACION: no hay tareas en ejecucion que coincidan."

    monkeypatch.setattr(docker_manager.sys, "platform", "win32")
    monkeypatch.setattr(
        docker_manager, "_ejecutar",
        lambda *a, **k: docker_manager.ResultadoComando(True, aviso, ""),
    )

    assert docker_manager.docker_abriendose() is False
