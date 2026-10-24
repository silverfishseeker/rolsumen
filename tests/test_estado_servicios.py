"""Lo que dice la pestaña Estado de Docker y de Craig.

Dos cosas que decía mal y por las que se hicieron estos tests:

- «parado (abre Docker Desktop)» mientras Docker Desktop se estaba abriendo.
  El consejo era justo el contrario del que hacía falta: esperar.
- «grabando disponible», en verde, con el contenedor de Craig muerto y sólo
  `db` y `redis` en pie. No se podía grabar nada.
"""

from app import gui
from app import supervisor_craig


def datos(**cambios) -> dict:
    """Todo bien, salvo lo que diga cada test."""
    base = {
        "docker_instalado": True,
        "docker": True,
        "docker_abriendose": False,
        "craig_instalado": True,
        "craig_configurado": True,
        "craig": True,
        "craig_en_marcha": True,
        "servicios_activos": ["db", "redis", "craig"],
        "craig_estado": supervisor_craig.OCIOSO,
        "craig_motivo": "",
    }
    base.update(cambios)
    return base


def texto_docker(**cambios) -> str:
    return gui._estado_docker(datos(**cambios))[0]


def color_docker(**cambios) -> str:
    return gui._estado_docker(datos(**cambios))[1]


def texto_craig(**cambios) -> str:
    return gui._estado_craig(datos(**cambios))[0]


def color_craig(**cambios) -> str:
    return gui._estado_craig(datos(**cambios))[1]


# --- Docker ------------------------------------------------------------------


def test_docker_en_marcha():
    assert texto_docker() == "en marcha"
    assert color_docker() == gui.OK


def test_docker_sin_instalar():
    assert texto_docker(docker_instalado=False) == "no instalado"
    assert color_docker(docker_instalado=False) == gui.MAL


def test_docker_abriendose_no_es_docker_parado():
    """`docker info` falla igual, pero lo que hay que hacer es lo contrario."""
    texto = texto_docker(docker=False, docker_abriendose=True)

    assert "arrancando" in texto
    assert "abre Docker Desktop" not in texto, "no hay que abrir lo que ya se abre"
    assert color_docker(docker=False, docker_abriendose=True) == gui.ESPERA


def test_docker_parado_de_verdad_pide_abrirlo():
    texto = texto_docker(docker=False, docker_abriendose=False)

    assert "abre Docker Desktop" in texto
    assert color_docker(docker=False, docker_abriendose=False) == gui.MAL


# --- Craig -------------------------------------------------------------------


def test_craig_grabando():
    assert texto_craig() == "grabando disponible"
    assert color_craig() == gui.OK


def test_craig_caido_con_sus_companeros_en_pie_no_sale_en_verde():
    """El fallo que motivó todo esto: salía «grabando disponible» en verde."""
    cambios = dict(craig_en_marcha=False, servicios_activos=["db", "redis"])

    texto, color = gui._estado_craig(datos(**cambios))

    assert "grabando disponible" not in texto
    assert color == gui.MAL
    assert "db" in texto and "redis" in texto, "y se dice qué sí está en pie"


def test_craig_esperando_a_docker_lo_dice():
    """Antes ponía «parado», que hacía buscar el problema donde no estaba."""
    texto = texto_craig(docker=False, craig=False, craig_en_marcha=False,
                        servicios_activos=[])

    assert texto == "esperando a Docker"
    assert color_craig(docker=False, craig=False, craig_en_marcha=False,
                       servicios_activos=[]) == gui.ESPERA


def test_craig_esperando_a_que_docker_termine_de_arrancar():
    texto = texto_craig(docker=False, docker_abriendose=True, craig=False,
                        craig_en_marcha=False, servicios_activos=[])

    assert "Docker" in texto and "arranque" in texto


def test_craig_levantandose():
    texto = texto_craig(craig=False, craig_en_marcha=False, servicios_activos=[],
                        craig_estado=supervisor_craig.LEVANTANDO)

    assert "levantando" in texto.lower()
    assert color_craig(craig=False, craig_en_marcha=False, servicios_activos=[],
                       craig_estado=supervisor_craig.LEVANTANDO) == gui.ESPERA


def test_craig_reintentando_dice_el_motivo():
    cambios = dict(craig=False, craig_en_marcha=False, servicios_activos=[],
                   craig_estado=supervisor_craig.ESPERANDO,
                   craig_motivo="port is already allocated")

    texto, color = gui._estado_craig(datos(**cambios))

    assert "reintentando" in texto and "port is already allocated" in texto
    assert color == gui.ESPERA


def test_ningun_estado_desborda_la_fila():
    """La fila es una línea en una ventana de 760 px: no puede estirarla."""
    largo = "Error response from daemon: " + "x" * 300
    for estado in (supervisor_craig.ESPERANDO, supervisor_craig.RENDIDO):
        texto, _ = gui._estado_craig(
            datos(craig=False, craig_en_marcha=False, servicios_activos=[],
                  craig_estado=estado, craig_motivo=largo)
        )
        assert len(texto) <= 58, f"{estado}: {len(texto)} caracteres"


def test_craig_rendido_sale_en_rojo_con_el_motivo():
    cambios = dict(craig=False, craig_en_marcha=False, servicios_activos=[],
                   craig_estado=supervisor_craig.RENDIDO,
                   craig_motivo="no space left on device")

    texto, color = gui._estado_craig(datos(**cambios))

    assert "no se pudo levantar" in texto and "no space left" in texto
    assert color == gui.MAL


def test_craig_parado_sin_mas():
    texto = texto_craig(craig=False, craig_en_marcha=False, servicios_activos=[])

    assert texto == "parado"


def test_craig_sin_instalar_o_sin_configurar():
    assert texto_craig(craig_instalado=False) == "sin instalar"
    assert texto_craig(craig_configurado=False) == "falta configurar"


# --- El motivo no puede romper la fila ---------------------------------------


def test_un_motivo_larguisimo_se_recorta():
    """Docker contesta párrafos enteros; la fila es una línea."""
    cambios = dict(craig=False, craig_en_marcha=False, servicios_activos=[],
                   craig_estado=supervisor_craig.RENDIDO,
                   craig_motivo="Error response from daemon: " + "x" * 400)

    texto, _ = gui._estado_craig(datos(**cambios))

    assert len(texto) < 90
    assert texto.endswith("…")


def test_un_motivo_con_saltos_de_linea_queda_en_una():
    cambios = dict(craig=False, craig_en_marcha=False, servicios_activos=[],
                   craig_estado=supervisor_craig.RENDIDO,
                   craig_motivo="primera\nsegunda\n\ntercera")

    texto, _ = gui._estado_craig(datos(**cambios))

    assert "\n" not in texto
    assert "primera segunda tercera" in texto
