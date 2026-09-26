"""Arranca y para el bot de música sin que pueda arrastrar a la aplicación.

La regla de este módulo: **nada de aquí sale hacia fuera**. Ni excepciones, ni
esperas largas, ni hilos que impidan cerrar la ventana. Si el bot no funciona
—token mal puesto, sin internet, Discord caído, falta `discord.py`— la
aplicación sigue grabando, transcribiendo y resumiendo exactamente igual; lo
único que cambia es una línea en la pestaña Estado.

Por eso el bot vive en un hilo demonio con su propio bucle asíncrono, y todo
lo que pueda fallar se convierte en un texto de estado.
"""

from __future__ import annotations

import asyncio
import logging
import threading

from ..config import Musica

registro = logging.getLogger(__name__)

# Cuánto se espera a que el bot cierre solo antes de dejarlo atrás. Es un hilo
# demonio: si tarda más, cerrar la ventana no se bloquea por él.
ESPERA_AL_CERRAR = 5.0

SIN_CONFIGURAR = "sin configurar"
ARRANCANDO = "arrancando..."


class Servicio:
    """El bot de música, visto desde el resto de la aplicación."""

    def __init__(self, ajustes: Musica, avisar=None) -> None:
        self.ajustes = ajustes
        # Lo que pase con la música se cuenta en el registro de actividad de la
        # ventana. Sin esto, un fallo al reproducir era silencio sin más: ni
        # sonaba ni había forma de saber por qué.
        self.avisar = avisar or (lambda _m: None)
        self._hilo: threading.Thread | None = None
        self._bucle: asyncio.AbstractEventLoop | None = None
        self._bot = None
        self._estado = SIN_CONFIGURAR

    # ------------------------------------------------------------ estado --

    @property
    def estado(self) -> str:
        """Texto para la pestaña Estado. Nunca bloquea ni lanza."""
        return self._estado

    @property
    def conectado(self) -> bool:
        return bool(self._bot and not getattr(self._bot, "is_closed", lambda: True)())

    # ---------------------------------------------------------- arrancar --

    def arrancar(self) -> None:
        """Pone el bot en marcha en segundo plano. Vuelve al instante."""
        if self._hilo and self._hilo.is_alive():
            return
        if not self.ajustes.configurado:
            self._estado = SIN_CONFIGURAR
            return

        self._estado = ARRANCANDO
        self._hilo = threading.Thread(
            target=self._vivir, name="musica", daemon=True
        )
        self._hilo.start()

    def _vivir(self) -> None:
        """El hilo del bot, de principio a fin. Aquí se traga todo."""
        try:
            from .bot import crear_bot
        except ImportError as exc:
            self._estado = f"falta discord.py ({exc})"
            return

        bucle = asyncio.new_event_loop()
        asyncio.set_event_loop(bucle)
        self._bucle = bucle

        try:
            self._bot = crear_bot(self.ajustes.carpeta, self._contar)
            bucle.run_until_complete(self._arrancar_y_esperar())
        except Exception as exc:  # noqa: BLE001 - el bot no puede tumbar nada
            registro.warning("el bot de música se detuvo: %s", exc)
            self._estado = self._traducir(exc)
        finally:
            try:
                # Deja que las tareas pendientes de `close()` terminen; si no,
                # asyncio se queja por consola con «Task was destroyed».
                pendientes = asyncio.all_tasks(bucle)
                if pendientes:
                    bucle.run_until_complete(
                        asyncio.gather(*pendientes, return_exceptions=True)
                    )
            except Exception:  # noqa: BLE001
                pass
            try:
                bucle.close()
            except Exception:  # noqa: BLE001
                pass
            self._bucle = None
            if self._estado == ARRANCANDO:
                self._estado = "desconectado"

    def _contar(self, mensaje: str) -> None:
        """Lleva un aviso a la ventana sin que un fallo ahí afecte al bot."""
        try:
            self.avisar(f"Música: {mensaje}")
        except Exception:  # noqa: BLE001
            pass

    async def _arrancar_y_esperar(self) -> None:
        async def avisar_cuando_este():
            await self._bot.wait_until_ready()
            nombre = getattr(self._bot.user, "name", "?")
            servidores = len(self._bot.guilds)
            self._estado = f"conectado como {nombre} ({servidores} servidor(es))"

        asyncio.create_task(avisar_cuando_este())
        await self._bot.start(self.ajustes.token_bot)

    @staticmethod
    def _traducir(exc: Exception) -> str:
        """Mensajes de Discord que no dicen nada, traducidos a algo útil."""
        texto = str(exc).lower()
        if "improper token" in texto or "unauthorized" in texto or "401" in texto:
            return "token rechazado: revísalo en config.ini"
        if "privileged" in texto:
            return "faltan intents privilegiados en el portal de Discord"
        if "getaddrinfo" in texto or "connect" in texto or "network" in texto:
            return "sin conexión con Discord"
        return f"error: {exc}"

    # -------------------------------------------------------------- parar --

    def parar(self, espera: float = ESPERA_AL_CERRAR) -> None:
        """Cierra el bot. Si se resiste, se deja atrás: es un hilo demonio.

        Se pide el cierre y se espera **al hilo**, no al futuro de `close()`.
        Esperar al futuro agotaba siempre el plazo entero: `close()` sólo
        termina del todo cuando el bucle sigue girando, y quien sabe de verdad
        que ya acabó todo es el hilo al salir.
        """
        bucle, bot = self._bucle, self._bot
        if bucle and bot:
            try:
                asyncio.run_coroutine_threadsafe(bot.close(), bucle)
            except Exception:  # noqa: BLE001 - cerrar nunca debe fallar
                pass

        if self._hilo and self._hilo.is_alive():
            self._hilo.join(timeout=espera)

        self._hilo = None
        self._bot = None
        self._estado = SIN_CONFIGURAR if not self.ajustes.configurado else "parado"
