"""Cuándo se intenta levantar Craig solo.

El caso que lo motiva: abrir la aplicación antes que Docker. Docker Desktop
tarda casi un minuto en responder y Craig se intentaba una sola vez, así que
quedaba parado el resto de la sesión sin que nadie lo volviera a intentar.

Todo esto es lógica pura a propósito: aquí no se habla con Docker.
"""

from app.supervisor_craig import (
    ESPERANDO,
    LEVANTANDO,
    LEVANTAR,
    NADA,
    OCIOSO,
    RENDIDO,
    Situacion,
    Supervisor,
)


def situacion(docker=True, craig=False, configurado=True) -> Situacion:
    return Situacion(
        docker_en_marcha=docker, craig_en_marcha=craig, craig_configurado=configurado
    )


# --- Lo básico ---------------------------------------------------------------


def test_con_docker_listo_y_craig_parado_se_levanta():
    assert Supervisor().decidir(situacion(), ahora=0) == LEVANTAR


def test_sin_docker_no_se_intenta_nada():
    """Nunca a ciegas: `compose up` con el motor caído sólo tarda en fallar."""
    assert Supervisor().decidir(situacion(docker=False), ahora=0) == NADA


def test_si_craig_ya_corre_no_se_toca():
    assert Supervisor().decidir(situacion(craig=True), ahora=0) == NADA


def test_sin_configurar_no_se_intenta():
    """Faltan credenciales: insistir no las va a traer."""
    assert Supervisor().decidir(situacion(configurado=False), ahora=0) == NADA


def test_mientras_se_levanta_no_se_vuelve_a_lanzar():
    """El ciclo pasa cada diez segundos y `compose up` tarda bastante más."""
    s = Supervisor()
    s.empezo()

    assert s.decidir(situacion(), ahora=0) == NADA
    assert s.estado == LEVANTANDO


# --- Reintentos --------------------------------------------------------------


def test_tras_fallar_se_espera_antes_de_reintentar():
    s = Supervisor(esperas=(60.0, 300.0))
    s.empezo()
    s.termino(ok=False, motivo="puerto 5432 ocupado", ahora=0)

    assert s.estado == ESPERANDO
    assert s.decidir(situacion(), ahora=59) == NADA, "todavía no toca"
    assert s.decidir(situacion(), ahora=60) == LEVANTAR


def test_la_segunda_espera_es_mas_larga():
    s = Supervisor(esperas=(60.0, 300.0))
    s.empezo()
    s.termino(ok=False, motivo="x", ahora=0)
    s.empezo()
    s.termino(ok=False, motivo="x", ahora=60)

    assert s.decidir(situacion(), ahora=300) == NADA
    assert s.decidir(situacion(), ahora=360) == LEVANTAR


def test_tras_agotar_las_esperas_se_rinde():
    """Un fallo propio de Craig no se arregla repitiendo el mismo comando."""
    s = Supervisor(esperas=(60.0, 300.0))
    for instante in (0, 60, 360):
        s.empezo()
        s.termino(ok=False, motivo="imagen corrupta", ahora=instante)

    assert s.estado == RENDIDO
    assert s.decidir(situacion(), ahora=10_000) == NADA
    assert s.motivo == "imagen corrupta", "y se recuerda por qué, para contarlo"


def test_al_conseguirlo_se_olvidan_los_fallos():
    s = Supervisor()
    s.empezo()
    s.termino(ok=False, motivo="x", ahora=0)
    s.empezo()
    s.termino(ok=True, motivo="", ahora=60)

    assert s.estado == OCIOSO
    assert s.fallos == 0
    assert s.motivo == ""


# --- Docker yendo y viniendo -------------------------------------------------


def test_si_docker_vuelve_se_empieza_de_cero():
    """Es la única situación de verdad nueva: el mundo ha cambiado."""
    s = Supervisor(esperas=(60.0, 300.0))
    for instante in (0, 60, 360):
        s.empezo()
        s.termino(ok=False, motivo="sin memoria", ahora=instante)
    assert s.estado == RENDIDO

    s.decidir(situacion(docker=False), ahora=400)  # Docker se cae
    decision = s.decidir(situacion(), ahora=401)  # y vuelve

    assert decision == LEVANTAR, "con Docker de vuelta se intenta otra vez"
    assert s.fallos == 0


def test_esperar_a_docker_no_gasta_intentos():
    """Arrancar la aplicación antes que Docker no debe agotar los reintentos."""
    s = Supervisor()
    for segundo in range(0, 60, 10):
        assert s.decidir(situacion(docker=False), ahora=segundo) == NADA

    assert s.decidir(situacion(), ahora=60) == LEVANTAR
    assert s.fallos == 0


def test_mientras_se_espera_a_docker_no_se_dice_que_fallo_nada():
    s = Supervisor()
    s.empezo()
    s.termino(ok=False, motivo="algo", ahora=0)

    s.decidir(situacion(docker=False), ahora=1)

    assert s.estado == OCIOSO and s.motivo == "", "la culpa no es de Craig"


def test_un_intento_en_curso_sobrevive_a_un_parpadeo_de_docker():
    """`compose up` tarda minutos; un `docker info` que falle no lo cancela."""
    s = Supervisor()
    s.empezo()

    s.decidir(situacion(docker=False), ahora=1)

    assert s.estado == LEVANTANDO


# --- Caídas con la aplicación abierta ----------------------------------------


def test_si_craig_se_cae_despues_se_vuelve_a_levantar():
    """El Exited (137) de madrugada: se recoge solo, sin enterarse nadie."""
    s = Supervisor()
    s.empezo()
    s.termino(ok=True, motivo="", ahora=0)
    assert s.decidir(situacion(craig=True), ahora=10) == NADA

    assert s.decidir(situacion(craig=False), ahora=20) == LEVANTAR
