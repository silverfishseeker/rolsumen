"""Tests del comando `/play`.

El fallo que motiva el más importante de estos tests: el mensaje con los
controles se publicaba **antes** de empezar a reproducir. En un canal donde el
bot no tiene permiso para escribir, eso reventaba y abortaba el comando entero:
ni sonaba la música ni aparecían los controles, y desde fuera parecía que el
bot estaba roto.

Reproducir no puede depender de poder escribir.
"""

import asyncio

import pytest

from app.musica import bot as modulo
from app.musica.lista import Pista


class CanalFalso:
    def __init__(self, nombre="música", puede_escribir=True):
        self.id = 1
        self.name = nombre
        self.puede_escribir = puede_escribir
        self.publicados = []

    async def send(self, contenido, view=None):
        if not self.puede_escribir:
            raise RuntimeError("Missing Permissions")
        self.publicados.append(contenido)
        return "mensaje"


class RespuestaFalsa:
    def __init__(self):
        self.diferida = False
        self.mensajes = []

    async def defer(self, ephemeral=False):
        self.diferida = True

    async def send_message(self, contenido, ephemeral=False):
        self.mensajes.append(contenido)
        self.diferida = True

    def is_done(self):
        return self.diferida


class SeguimientoFalso:
    def __init__(self):
        self.mensajes = []

    async def send(self, contenido, ephemeral=False):
        self.mensajes.append(contenido)


class InteraccionFalsa:
    def __init__(self, canal, en_voz=True):
        self.guild_id = 99
        self.channel = canal
        self.response = RespuestaFalsa()
        self.followup = SeguimientoFalso()
        self.borrada = False
        voz = type("V", (), {"channel": canal})() if en_voz else None
        self.user = type("U", (), {"voice": voz, "display_name": "ana"})()

    async def delete_original_response(self):
        self.borrada = True


class ReproductorFalso:
    def __init__(self):
        from app.musica.lista import Lista

        self.lista = Lista()
        self.carpeta = ""
        self.mensaje = None
        self.orden = []

    async def conectar(self, canal):
        self.orden.append("conectar")

    async def reproducir_actual(self):
        self.orden.append("reproducir")

    async def refrescar_mensaje(self):
        pass


@pytest.fixture
def entorno(monkeypatch):
    """El bot con `/play`, sin hablar con Discord."""
    creado = modulo.crear_bot("", avisar=lambda _m: None)
    repro = ReproductorFalso()
    monkeypatch.setattr(creado, "reproductor_de", lambda _g: repro)
    monkeypatch.setattr(
        modulo, "resolver",
        lambda consulta, carpeta, quien: Pista(consulta, "C:/x.mp3", quien, local=True),
    )
    monkeypatch.setattr(modulo, "Controles", lambda _r: None)
    orden = creado.tree.get_command("play")
    return orden.callback, repro


def ejecutar(corrutina):
    return asyncio.run(corrutina)


def test_suena_aunque_no_se_puedan_publicar_los_controles(entorno):
    """El fallo de verdad: sin permiso de escritura no sonaba nada."""
    play, repro = entorno
    canal = CanalFalso(puede_escribir=False)

    ejecutar(play(InteraccionFalsa(canal), "lluvia"))

    assert "reproducir" in repro.orden, "la música tiene que sonar igualmente"


def test_se_reproduce_antes_de_publicar(entorno):
    play, repro = entorno
    canal = CanalFalso()

    interaccion = InteraccionFalsa(canal)
    ejecutar(play(interaccion, "lluvia"))

    assert repro.orden == ["conectar", "reproducir"]
    assert canal.publicados, "y los controles se publican después"
    assert interaccion.followup.mensajes == [], "sin avisos de trámite"
    assert interaccion.borrada


def test_si_no_se_puede_escribir_se_explica_por_privado(entorno):
    play, _ = entorno
    interaccion = InteraccionFalsa(CanalFalso(puede_escribir=False))

    ejecutar(play(interaccion, "lluvia"))

    aviso = " ".join(interaccion.followup.mensajes).lower()
    assert "permiso" in aviso and "escribir" in aviso
    assert "sonando" in aviso, "hay que dejar claro que la música sí va"


def test_fuera_de_un_canal_de_voz_se_avisa(entorno):
    play, repro = entorno
    interaccion = InteraccionFalsa(CanalFalso(), en_voz=False)

    ejecutar(play(interaccion, "lluvia"))

    assert repro.orden == [], "no hay dónde reproducir"
    assert "canal de voz" in " ".join(interaccion.response.mensajes)


def test_lo_segundo_se_encola_en_vez_de_interrumpir(entorno):
    play, repro = entorno
    canal = CanalFalso()
    interaccion = InteraccionFalsa(canal)

    ejecutar(play(interaccion, "primera"))
    repro.orden.clear()
    ejecutar(play(interaccion, "segunda"))

    assert repro.orden == [], "no se reconecta ni se corta lo que suena"
    assert len(repro.lista) == 1
    assert interaccion.followup.mensajes == [], (
        "encolar no merece un mensaje: el de controles ya dice cuántas esperan"
    )
    assert interaccion.borrada, "y no debe quedar el «pensando...» colgado"


def test_un_fallo_buscando_se_cuenta_y_no_reproduce(entorno, monkeypatch):
    play, repro = entorno

    def no_encontrado(*a, **k):
        raise modulo.ErrorBusqueda("ese vídeo no está disponible")

    monkeypatch.setattr(modulo, "resolver", no_encontrado)
    interaccion = InteraccionFalsa(CanalFalso())

    ejecutar(play(interaccion, "algo que no existe"))

    assert repro.orden == []
    assert "no está disponible" in " ".join(interaccion.followup.mensajes)
