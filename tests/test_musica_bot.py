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


class VozFalsa:
    """Una conexión de voz que no habla con Discord: sólo apunta qué se puso."""

    def __init__(self):
        self.puestas = []
        self.conectada = True
        self.sonando = False

    def play(self, fuente, after=None):
        self.puestas.append(fuente)
        self.sonando = True

    def is_playing(self):
        return self.sonando

    def is_paused(self):
        return False

    def is_connected(self):
        return self.conectada

    def stop(self):
        self.sonando = False

    async def disconnect(self, force=False):
        self.conectada = False


class MensajeFalso:
    def __init__(self, contenido=""):
        self.ediciones = [contenido] if contenido else []
        self.borrado = False

    @property
    def contenido(self):
        return self.ediciones[-1] if self.ediciones else ""

    async def edit(self, content=None, view=None):
        self.ediciones.append(content)

    async def delete(self):
        self.borrado = True


class CanalFalso:
    def __init__(self, nombre="música", puede_escribir=True):
        self.id = 1
        self.name = nombre
        self.puede_escribir = puede_escribir
        self.publicados = []
        self.enviados = []

    async def send(self, contenido, view=None):
        if not self.puede_escribir:
            raise RuntimeError("Missing Permissions")
        self.publicados.append(contenido)
        mensaje = MensajeFalso(contenido)
        self.enviados.append(mensaje)
        return mensaje

    @property
    def vivos(self):
        """Los mensajes que siguen en el canal: los que no se han borrado."""
        return [m for m in self.enviados if not m.borrado]

    async def connect(self):
        return VozFalsa()


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


SEGUIDOS = {"conectar": "conectar", "reproducir_actual": "reproducir",
            "retirar_mensaje": "retirar"}


def _seguir(repro, monkeypatch):
    """Anota lo que hace el reproductor **sin sustituir lo que hace**.

    Un doble del reproductor no vale para probar el bot: el mensaje de
    controles lo lleva él, así que un doble con su propia versión de eso
    probaría el doble. Aquí sólo se envuelve para saber el orden.
    """
    orden = []
    for nombre, mote in SEGUIDOS.items():
        real = getattr(repro, nombre)

        def envuelto(*a, _real=real, _mote=mote, **k):
            orden.append(_mote)
            return _real(*a, **k)

        monkeypatch.setattr(repro, nombre, envuelto)
    return orden


def _montar(monkeypatch):
    """El bot entero, con el reproductor de verdad y una voz de mentira."""
    creado = modulo.crear_bot("", avisar=lambda _m: None)
    repro = modulo.Reproductor(creado, "", avisar=lambda _m: None)
    monkeypatch.setattr(repro, "_fuente", lambda pista: pista.titulo)
    repro.orden = _seguir(repro, monkeypatch)
    monkeypatch.setattr(creado, "reproductor_de", lambda _g: repro)
    monkeypatch.setattr(
        modulo, "resolver",
        lambda consulta, carpeta, quien: Pista(consulta, "C:/x.mp3", quien, local=True),
    )
    monkeypatch.setattr(modulo, "Controles", lambda _r: None)
    return creado, repro


@pytest.fixture
def entorno(monkeypatch):
    creado, repro = _montar(monkeypatch)
    return creado.tree.get_command("play").callback, repro


@pytest.fixture
def entorno_sin_bucle(monkeypatch):
    """El comando hermano: mismo cuerpo, la pista entra sin bucle."""
    creado, repro = _montar(monkeypatch)
    return creado.tree.get_command("playsinbucle").callback, repro


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

    assert repro.orden == ["retirar", "conectar", "reproducir"]
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


# --- Bucle, botones y título al cambiar de pista ------------------------------


class InteraccionBoton:
    def __init__(self):
        self.response = RespuestaFalsa()

    async def delete_original_response(self):
        pass


def tema(titulo, bucle=True):
    return Pista(titulo, f"C:/{titulo}.mp3", "ana", local=True, bucle=bucle)


def _reproductor(monkeypatch, *pistas):
    """Un reproductor de verdad con una voz de mentira."""
    repro = modulo.Reproductor(type("B", (), {"loop": None})(), "", avisar=lambda _m: None)
    monkeypatch.setattr(repro, "_fuente", lambda pista: pista.titulo)
    repro.voz = VozFalsa()
    repro.voz.sonando = bool(pistas)  # si hay pista actual, es que suena
    for pista in pistas:
        repro.lista.anadir(pista)
    return repro


def _boton(vista, etiqueta):
    return next(b for b in vista.children if b.label == etiqueta)


def test_con_bucle_la_pista_se_repite(monkeypatch):
    repro = _reproductor(monkeypatch, tema("primera"), tema("segunda"))

    ejecutar(repro._avanzar())

    assert repro.lista.actual.titulo == "primera"
    assert repro.voz.puestas == ["primera"], "se vuelve a poner, no se pasa"


def test_sin_bucle_pasa_a_la_siguiente(monkeypatch):
    repro = _reproductor(monkeypatch, tema("primera", bucle=False), tema("segunda"))

    ejecutar(repro._avanzar())

    assert repro.lista.actual.titulo == "segunda"


def test_siguiente_manda_sobre_el_bucle(monkeypatch):
    """Pedir la siguiente teniendo el bucle puesto tiene que pasar de pista."""
    repro = _reproductor(monkeypatch, tema("primera"), tema("segunda"))

    assert repro.saltar()
    ejecutar(repro._avanzar())  # lo que dispara `after` al cortar

    assert repro.lista.actual.titulo == "segunda"


def test_saltar_una_vez_no_desactiva_el_bucle(monkeypatch):
    repro = _reproductor(monkeypatch, tema("primera"), tema("segunda"))
    repro.saltar()
    ejecutar(repro._avanzar())

    ejecutar(repro._avanzar())  # ahora termina sola

    assert repro.lista.actual.titulo == "segunda", "la segunda sigue en bucle"


def test_una_pista_rota_no_se_reintenta_sin_fin(monkeypatch):
    """Con bucle, reintentar lo que no se puede abrir sería un bucle infinito."""
    repro = _reproductor(monkeypatch, tema("rota"), tema("buena"))

    def revienta(pista):
        if pista.titulo == "rota":
            raise RuntimeError("no se puede abrir")
        return pista.titulo

    monkeypatch.setattr(repro, "_fuente", revienta)

    ejecutar(repro.reproducir_actual())

    assert repro.lista.actual.titulo == "buena"
    assert repro.voz.puestas == ["buena"]


def test_el_mensaje_dice_lo_que_suena_ahora(monkeypatch):
    repro = _reproductor(monkeypatch, tema("primera", bucle=False), tema("segunda"))
    repro.mensaje = MensajeFalso()

    ejecutar(repro._avanzar())

    assert "segunda" in repro.mensaje.contenido
    assert "primera" not in repro.mensaje.contenido


def test_al_acabarse_todo_se_retiran_los_controles(monkeypatch):
    """Y sobre todo se deja de apuntarlos: ahí estaba el mensaje duplicado."""
    repro = _reproductor(monkeypatch, tema("unica", bucle=False))
    repro.mensaje = MensajeFalso()
    mensaje, voz = repro.mensaje, repro.voz

    ejecutar(repro._avanzar())

    assert mensaje.borrado, "unos controles de algo que no suena no controlan nada"
    assert repro.mensaje is None, "y no se vuelven a editar por error"
    assert not voz.conectada, "y se sale del canal"


def test_los_botones_se_llaman_como_toca(monkeypatch):
    repro = _reproductor(monkeypatch, tema("x"))

    etiquetas = [b.label for b in modulo.Controles(repro).children]

    assert etiquetas == ["Pausa", "Bucle: sí", "Siguiente", "Quitar"]


def test_el_boton_de_bucle_lo_quita_y_lo_devuelve(monkeypatch):
    repro = _reproductor(monkeypatch, tema("x"))
    repro.mensaje = MensajeFalso()

    ejecutar(_boton(modulo.Controles(repro), "Bucle: sí").callback(InteraccionBoton()))
    assert not repro.lista.actual.bucle

    ejecutar(_boton(modulo.Controles(repro), "Bucle: no").callback(InteraccionBoton()))
    assert repro.lista.actual.bucle


def test_siguiente_no_reescribe_el_mensaje_con_el_titulo_viejo(monkeypatch):
    """La edición del botón podía llegar después de la de la pista nueva."""
    repro = _reproductor(monkeypatch, tema("primera"), tema("segunda"))
    repro.mensaje = MensajeFalso()

    ejecutar(_boton(modulo.Controles(repro), "Siguiente").callback(InteraccionBoton()))

    assert repro.mensaje.ediciones == [], "refresca quien pone la pista siguiente"


def test_el_estado_no_repite_lo_que_dice_el_boton(monkeypatch):
    """El bucle lo indica el botón; decirlo también en el título sobraba."""
    repro = _reproductor(monkeypatch, tema("x"))

    assert "bucle" not in modulo._texto_estado(repro.lista, False).lower()

    etiquetas = " ".join(b.label for b in modulo.Controles(repro).children)
    assert "Bucle" in etiquetas, "pero en algún sitio hay que poder verlo"


def test_play_encola_en_bucle_por_defecto(entorno):
    play, repro = entorno

    ejecutar(play(InteraccionFalsa(CanalFalso()), "lluvia"))

    assert repro.lista.actual.bucle


def test_playsinbucle_trae_la_cancion_sin_bucle(entorno_sin_bucle):
    play, repro = entorno_sin_bucle

    ejecutar(play(InteraccionFalsa(CanalFalso()), "lluvia"))

    assert not repro.lista.actual.bucle


def test_playsinbucle_hace_lo_mismo_por_lo_demás(entorno_sin_bucle):
    """No es un comando distinto: es el mismo cuerpo con otro bucle."""
    play, repro = entorno_sin_bucle
    canal = CanalFalso()

    ejecutar(play(InteraccionFalsa(canal), "lluvia"))

    assert repro.orden == ["retirar", "conectar", "reproducir"]
    assert canal.publicados, "y publica sus controles"


def test_los_comandos_son_los_que_se_teclean(monkeypatch):
    """Nombres y opciones son interfaz: se escriben en Discord a mano."""
    arbol = modulo.crear_bot("").tree

    comandos = {
        o.name: {p.name: (p.type.name, p.required) for p in o.parameters}
        for o in arbol.get_commands()
    }

    # Ninguno lleva opciones más allá de qué poner: lo que se quería evitar era
    # justo tener que desplegar un sí/no para quitar el bucle.
    assert comandos == {
        "play": {"consulta": ("string", True)},
        "playsinbucle": {"consulta": ("string", True)},
    }


def test_playsinbucle_no_deja_dos_mensajes_de_control(entorno_sin_bucle):
    """El fallo tal como se veía: dos mensajes de control en el canal.

    Sin bucle la cola se vacía al terminar la pista, pero el mensaje seguía
    apuntado. La vez siguiente se editaba ese **y** se publicaba otro, los dos
    con el mismo título y los dos con botones. Con `/play` no pasaba porque en
    bucle la cola nunca se vacía.
    """
    play, repro = entorno_sin_bucle
    canal = CanalFalso()

    ejecutar(play(InteraccionFalsa(canal), "primera"))
    ejecutar(repro._avanzar())  # la pista acaba y, sin bucle, no queda nada
    ejecutar(play(InteraccionFalsa(canal), "segunda"))

    assert len(canal.vivos) == 1, "sólo puede quedar un mensaje de control"
    assert "segunda" in canal.vivos[0].contenido


def test_el_boton_quitar_se_lleva_los_controles(monkeypatch):
    repro = _reproductor(monkeypatch, tema("x"))
    repro.mensaje = MensajeFalso()
    mensaje = repro.mensaje

    ejecutar(_boton(modulo.Controles(repro), "Quitar").callback(InteraccionBoton()))

    assert mensaje.borrado
    assert repro.mensaje is None


# --- Al cerrar la aplicación --------------------------------------------------


def test_retirar_controles_deja_el_servidor_como_estaba(monkeypatch):
    """Cerrar la ventana no puede dejar unos botones que no responden."""
    repro = _reproductor(monkeypatch, tema("x"), tema("y"))
    repro.mensaje = MensajeFalso()
    mensaje, voz = repro.mensaje, repro.voz
    bot = type("B", (), {"reproductores": {1: repro}})()

    ejecutar(modulo.retirar_controles(bot))

    assert mensaje.borrado, "los controles se van"
    assert repro.lista.vacia, "y la cola no se queda a medias"
    assert not voz.conectada, "y el bot sale del canal de voz"


def test_un_reproductor_atascado_no_impide_recoger_los_demas(monkeypatch):
    atascado = _reproductor(monkeypatch, tema("x"))
    atascado.mensaje = MensajeFalso()
    sano = _reproductor(monkeypatch, tema("y"))
    sano.mensaje = MensajeFalso()
    suyo = sano.mensaje

    async def se_niega():
        raise RuntimeError("Discord no contesta")

    monkeypatch.setattr(atascado, "retirar_mensaje", se_niega)
    bot = type("B", (), {"reproductores": {1: atascado, 2: sano}})()

    ejecutar(modulo.retirar_controles(bot))

    assert suyo.borrado


def test_sin_reproductores_no_hay_nada_que_recoger():
    ejecutar(modulo.retirar_controles(type("B", (), {})()))
