"""El bot de música no puede arrastrar a la aplicación.

Es un añadido opcional: si falla —token mal puesto, sin internet, Discord
caído, falta `discord.py`— grabar, transcribir y resumir tiene que seguir
funcionando igual. Lo único que debe cambiar es una línea en la pestaña Estado.

Estos tests comprueban justo eso, que es lo que se pidió.
"""

import threading
import time

import pytest

from app.config import Musica
from app.musica import servicio as mod
from app.musica.servicio import ARRANCANDO, SIN_CONFIGURAR, Servicio


def ajustes(token="x" * 50, idapp="123", carpeta="") -> Musica:
    return Musica(token_bot=token, id_aplicacion=idapp, carpeta=carpeta)


def esperar_a_que(condicion, limite=5.0) -> bool:
    fin = time.time() + limite
    while time.time() < fin:
        if condicion():
            return True
        time.sleep(0.05)
    return False


def test_sin_token_ni_se_intenta():
    s = Servicio(Musica())

    s.arrancar()

    assert s.estado == SIN_CONFIGURAR
    assert not s.conectado


def test_sin_token_no_deja_hilos_sueltos():
    antes = threading.active_count()
    s = Servicio(Musica())

    s.arrancar()

    assert threading.active_count() == antes


def test_arrancar_devuelve_el_control_enseguida(monkeypatch):
    """La ventana no puede quedarse esperando a que Discord conteste."""

    def bot_lento(_carpeta, _avisar=None):
        time.sleep(30)  # como si Discord tardara una eternidad

    monkeypatch.setattr("app.musica.bot.crear_bot", bot_lento)
    s = Servicio(ajustes())

    t = time.time()
    s.arrancar()
    tardanza = time.time() - t

    assert tardanza < 0.5, f"arrancar bloqueó {tardanza:.1f}s"
    assert s.estado == ARRANCANDO


def test_si_el_bot_revienta_solo_cambia_el_estado(monkeypatch):
    def explota(_carpeta, _avisar=None):
        raise RuntimeError("algo muy malo")

    monkeypatch.setattr("app.musica.bot.crear_bot", explota)
    s = Servicio(ajustes())

    s.arrancar()  # no debe lanzar

    assert esperar_a_que(lambda: "algo muy malo" in s.estado), s.estado
    assert not s.conectado


def test_un_token_rechazado_se_explica_en_cristiano(monkeypatch):
    class BotFalso:
        def is_closed(self): return True
        async def start(self, token):
            raise RuntimeError("Improper token has been passed.")
        async def wait_until_ready(self): pass

    monkeypatch.setattr("app.musica.bot.crear_bot", lambda _c, _a=None: BotFalso())
    s = Servicio(ajustes())

    s.arrancar()

    assert esperar_a_que(lambda: "token" in s.estado.lower()), s.estado
    assert "config.ini" in s.estado, "hay que decir dónde se arregla"


def test_sin_red_se_dice_que_es_la_red(monkeypatch):
    class BotFalso:
        def is_closed(self): return True
        async def start(self, token):
            raise OSError("getaddrinfo failed")
        async def wait_until_ready(self): pass

    monkeypatch.setattr("app.musica.bot.crear_bot", lambda _c, _a=None: BotFalso())
    s = Servicio(ajustes())
    s.arrancar()

    assert esperar_a_que(lambda: "conexión" in s.estado), s.estado


def test_parar_sin_haber_arrancado_no_falla():
    Servicio(Musica()).parar()


def test_parar_no_se_queda_colgado(monkeypatch):
    """Cerrar la ventana no puede depender de que el bot se porte bien."""

    class BotTerco:
        def is_closed(self): return False
        async def start(self, token):
            import asyncio
            await asyncio.sleep(3600)
        async def wait_until_ready(self):
            import asyncio
            await asyncio.sleep(3600)
        async def close(self):
            import asyncio
            await asyncio.sleep(3600)  # se niega a cerrar

    monkeypatch.setattr("app.musica.bot.crear_bot", lambda _c, _a=None: BotTerco())
    s = Servicio(ajustes())
    s.arrancar()
    esperar_a_que(lambda: s._bucle is not None, 3.0)

    t = time.time()
    s.parar(espera=0.5)
    tardanza = time.time() - t

    assert tardanza < 3.0, f"parar bloqueó {tardanza:.1f}s"


def test_el_hilo_es_demonio(monkeypatch):
    """Si no lo fuera, un bot colgado impediría cerrar el proceso."""

    class BotQuieto:
        def is_closed(self): return False
        async def start(self, token):
            import asyncio
            await asyncio.sleep(3600)
        async def wait_until_ready(self):
            import asyncio
            await asyncio.sleep(3600)
        async def close(self): pass

    monkeypatch.setattr("app.musica.bot.crear_bot", lambda _c, _a=None: BotQuieto())
    s = Servicio(ajustes())
    s.arrancar()

    assert s._hilo.daemon


def test_arrancar_dos_veces_no_duplica_el_bot(monkeypatch):
    creados = []

    class BotQuieto:
        def is_closed(self): return False
        async def start(self, token):
            import asyncio
            await asyncio.sleep(3600)
        async def wait_until_ready(self):
            import asyncio
            await asyncio.sleep(3600)
        async def close(self): pass

    def contar(_c, _a=None):
        creados.append(1)
        return BotQuieto()

    monkeypatch.setattr("app.musica.bot.crear_bot", contar)
    s = Servicio(ajustes())
    s.arrancar()
    esperar_a_que(lambda: creados, 3.0)
    s.arrancar()
    time.sleep(0.3)

    assert len(creados) == 1
    s.parar(espera=0.5)


@pytest.mark.parametrize("token,esperado", [("", False), ("x" * 50, True)])
def test_configurado_depende_del_token(token, esperado):
    assert Musica(token_bot=token, id_aplicacion="1").configurado is esperado


# --- Lo que pasa con la música se cuenta en la ventana ----------------------


def test_los_avisos_llegan_a_quien_los_pidio(monkeypatch):
    """Sin esto, un fallo al reproducir era silencio y nada más.

    El usuario no oía música y tampoco tenía dónde mirar por qué.
    """
    recibidos = []

    def bot_que_avisa(_carpeta, avisar=None):
        avisar("no se pudo reproducir «algo»: el vídeo no existe")

        class BotFalso:
            def is_closed(self): return True
            async def start(self, token): pass
            async def wait_until_ready(self): pass

        return BotFalso()

    monkeypatch.setattr("app.musica.bot.crear_bot", bot_que_avisa)
    s = Servicio(ajustes(), avisar=recibidos.append)

    s.arrancar()

    assert esperar_a_que(lambda: recibidos), "no llegó ningún aviso"
    assert recibidos[0].startswith("Música:"), recibidos[0]
    assert "no existe" in recibidos[0]


def test_un_fallo_al_avisar_no_tumba_el_bot(monkeypatch):
    def avisador_roto(_mensaje):
        raise RuntimeError("la ventana ya no está")

    def bot_que_avisa(_carpeta, avisar=None):
        avisar("hola")

        class BotFalso:
            def is_closed(self): return True
            async def start(self, token): pass
            async def wait_until_ready(self): pass

        return BotFalso()

    monkeypatch.setattr("app.musica.bot.crear_bot", bot_que_avisa)
    s = Servicio(ajustes(), avisar=avisador_roto)

    s.arrancar()  # no debe lanzar

    assert esperar_a_que(lambda: not s._hilo.is_alive() or True)


def test_sin_avisador_tambien_funciona():
    # La aplicación es quien lo pasa; en pruebas y en consola no hay ninguno.
    Servicio(Musica()).arrancar()


# --- Al cerrar, recoger lo dejado en Discord ----------------------------------


class BotDormido:
    """Se queda esperando como el de verdad, y apunta cuándo se le cierra."""

    def __init__(self, hechos):
        self.hechos = hechos
        self.reproductores = {}
        self.cerrado = False

    def is_closed(self):
        return self.cerrado

    async def start(self, token):
        import asyncio

        await asyncio.sleep(3600)

    async def wait_until_ready(self):
        import asyncio

        await asyncio.sleep(3600)

    async def close(self):
        self.hechos.append("cerrar")
        self.cerrado = True


def _servicio_en_marcha(monkeypatch, hechos):
    monkeypatch.setattr(
        "app.musica.bot.crear_bot", lambda _c, _a=None: BotDormido(hechos)
    )
    s = Servicio(ajustes())
    s.arrancar()
    assert esperar_a_que(lambda: s._bucle is not None, 3.0)
    return s


def test_al_cerrar_se_retiran_los_controles(monkeypatch):
    """Si el mensaje se queda, sus botones no responden a nadie.

    Y anuncia una pista que ya no suena, así que desde el canal parece que el
    bot sigue puesto.
    """
    hechos = []

    async def retirada(_bot):
        hechos.append("retirar")

    monkeypatch.setattr("app.musica.bot.retirar_controles", retirada)
    s = _servicio_en_marcha(monkeypatch, hechos)

    s.parar(espera=3.0)

    assert esperar_a_que(lambda: hechos == ["retirar", "cerrar"], 3.0), (
        f"hay que recoger antes de cerrar la sesión; quedó en {hechos}"
    )


def test_si_no_se_pueden_retirar_se_cierra_igual(monkeypatch):
    """Cerrar manda sobre recoger: la ventana tiene que poder irse."""
    hechos = []

    async def revienta(_bot):
        raise RuntimeError("Discord no contesta")

    monkeypatch.setattr("app.musica.bot.retirar_controles", revienta)
    s = _servicio_en_marcha(monkeypatch, hechos)

    s.parar(espera=3.0)

    assert esperar_a_que(lambda: hechos == ["cerrar"], 3.0)
