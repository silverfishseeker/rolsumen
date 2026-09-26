"""El bot de música: dos comandos y un mensaje con botones.

Mismo patrón que Craig, que es el que ya funciona aquí: se pide una pista con un
comando y todo el control va en botones dentro del mensaje. `/play` la deja en
bucle y `/playsinbucle` no; son dos comandos porque en Discord toda opción se
escribe `nombre:valor`, así que como parámetro habría que desplegar un sí/no
cada vez.

Todo lo que puede fallar (YouTube, la red, el canal de voz) se responde al
usuario; nada de esto puede tumbar el hilo del bot ni, mucho menos, la ventana.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace

from .. import dependencias
from .busqueda import ErrorBusqueda, resolver
from .lista import Lista, Pista

registro = logging.getLogger(__name__)

# A media potencia: un bot que entra a todo volumen en una partida es un susto.
VOLUMEN = 0.5

# Sin esto, un corte de red deja la pista muda en vez de reconectar.
ANTES_DE_FFMPEG = "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
OPCIONES_FFMPEG = "-vn"


def _texto_estado(lista: Lista, pausado: bool) -> str:
    if lista.actual is None:
        return "Nada sonando."
    cabecera = "⏸ En pausa" if pausado else "♪ Sonando"
    lineas = [f"**{cabecera}:** {lista.actual.como_texto()}"]

    # El bucle no se menciona aquí: lo dice el botón, y en dos sitios estorba.
    detalles = []
    if lista.actual.pedida_por:
        detalles.append(f"pedida por {lista.actual.pedida_por}")
    if len(lista):
        detalles.append(f"{len(lista)} en cola")
    if lista.actual.local:
        detalles.append("archivo local")
    if detalles:
        lineas.append(" · ".join(detalles))
    return "\n".join(lineas)


class Reproductor:
    """Lo que suena en un servidor: la cola, la voz y el mensaje de control."""

    def __init__(self, bot, carpeta: str, avisar=None) -> None:
        self.bot = bot
        self.carpeta = carpeta
        self.avisar = avisar or (lambda _m: None)
        self.lista = Lista()
        self.voz = None
        self.mensaje = None
        # Lo pone «Siguiente» para que al terminar la pista no se repita aunque
        # tenga el bucle puesto: pedir la siguiente manda sobre el bucle.
        self._saltando = False

    # ------------------------------------------------------------ estado --

    @property
    def pausado(self) -> bool:
        return bool(self.voz and self.voz.is_paused())

    async def conectar(self, canal) -> None:
        """Entra al canal de quien lo pidió, o se cambia si ya estaba en otro."""
        if self.voz and self.voz.is_connected():
            if self.voz.channel.id != canal.id:
                await self.voz.move_to(canal)
            return
        self.voz = await canal.connect()

    async def desconectar(self) -> None:
        self.lista.vaciar()
        if self.voz:
            try:
                await self.voz.disconnect(force=True)
            except Exception:  # noqa: BLE001 - salir nunca debe fallar
                pass
        self.voz = None

    # -------------------------------------------------------- reproducir --

    def _fuente(self, pista: Pista):
        import discord

        dependencias.asegurar_en_path("ffmpeg")
        audio = discord.FFmpegPCMAudio(
            pista.origen,
            before_options="" if pista.local else ANTES_DE_FFMPEG,
            options=OPCIONES_FFMPEG,
        )
        return discord.PCMVolumeTransformer(audio, volume=VOLUMEN)

    def _al_acabar(self, error) -> None:
        """Lo llama discord.py desde OTRO hilo cuando termina una pista."""
        if error:
            registro.warning("la pista terminó con error: %s", error)
        asyncio.run_coroutine_threadsafe(self._avanzar(), self.bot.loop)

    async def _avanzar(self) -> None:
        repetir = bool(
            self.lista.actual and self.lista.actual.bucle and not self._saltando
        )
        self._saltando = False
        if repetir:
            await self.reproducir_actual()
            return
        if self.lista.siguiente() is None:
            await self.retirar_mensaje()
            await self.desconectar()
            return
        await self.reproducir_actual()

    async def reproducir_actual(self) -> None:
        pista = self.lista.actual
        if pista is None or self.voz is None:
            return
        try:
            self.voz.play(self._fuente(pista), after=self._al_acabar)
        except Exception as exc:  # noqa: BLE001 - una pista mala no para la cola
            self.avisar(f"no se pudo reproducir «{pista.titulo}»: {exc}")
            # Con el bucle puesto, reintentar una pista rota sería un bucle de
            # verdad: hay que saltarla igual que si se hubiera pulsado.
            self._saltando = True
            await self._avanzar()
            return
        await self.refrescar_mensaje()

    # ----------------------------------------------------------- botones --

    def saltar(self) -> bool:
        if self.voz and (self.voz.is_playing() or self.voz.is_paused()):
            self._saltando = True
            self.voz.stop()  # dispara `after`, que encadena la siguiente
            return True
        return False

    def alternar_bucle(self) -> bool:
        return self.lista.alternar_bucle()

    def pausar_o_reanudar(self) -> bool:
        if not self.voz:
            return False
        if self.voz.is_paused():
            self.voz.resume()
        elif self.voz.is_playing():
            self.voz.pause()
        else:
            return False
        return True

    # ----------------------------------------------------------- mensaje --

    async def retirar_mensaje(self) -> None:
        """Borra el mensaje de controles y deja de seguirlo.

        Unos controles de algo que ya no suena no controlan nada. Y si se
        quedaran apuntados, la próxima pista los editaría **y** publicaría
        otros: dos mensajes de control a la vez, los dos con el mismo título.
        Pasaba con `/playsinbucle`, el único que llega a vaciar la cola.
        """
        mensaje, self.mensaje = self.mensaje, None
        if mensaje is None:
            return
        try:
            await mensaje.delete()
        except Exception:  # noqa: BLE001 - lo habrán borrado ya; da igual
            pass

    async def refrescar_mensaje(self) -> None:
        """Edita el mensaje de control en vez de publicar uno nuevo."""
        if self.mensaje is None:
            return
        try:
            await self.mensaje.edit(
                content=_texto_estado(self.lista, self.pausado),
                view=None if self.lista.vacia else Controles(self),
            )
        except Exception:  # noqa: BLE001 - lo habrán borrado; da igual
            self.mensaje = None


class Controles:
    """Los botones del mensaje. Se construye tarde para no importar discord."""

    def __new__(cls, reproductor: Reproductor):
        import discord

        vista = discord.ui.View(timeout=None)

        async def responder(interaccion, accion, refrescar=True) -> None:
            try:
                accion()
                if refrescar:
                    await reproductor.refrescar_mensaje()
                await interaccion.response.defer()
            except Exception as exc:  # noqa: BLE001
                registro.warning("fallo atendiendo un botón: %s", exc)
                if not interaccion.response.is_done():
                    await interaccion.response.defer()

        en_bucle = bool(reproductor.lista.actual and reproductor.lista.actual.bucle)

        etiqueta = "Reanudar" if reproductor.pausado else "Pausa"
        pausa = discord.ui.Button(label=etiqueta, style=discord.ButtonStyle.secondary)
        # El botón dice cómo está, no lo que hará: leerlo de un vistazo importa
        # más que adivinar el efecto de pulsarlo, que además es reversible.
        bucle = discord.ui.Button(
            label="Bucle: sí" if en_bucle else "Bucle: no",
            style=discord.ButtonStyle.primary if en_bucle else discord.ButtonStyle.secondary,
        )
        siguiente = discord.ui.Button(
            label="Siguiente", style=discord.ButtonStyle.secondary
        )
        quitar = discord.ui.Button(label="Quitar", style=discord.ButtonStyle.danger)

        async def al_pausar(i):
            await responder(i, reproductor.pausar_o_reanudar)

        async def al_bucle(i):
            await responder(i, reproductor.alternar_bucle)

        async def al_siguiente(i):
            # Sin refrescar aquí: `stop()` encadena la siguiente desde otro
            # hilo y quien la pone ya actualiza el mensaje. Refrescar también
            # desde aquí mete una edición con el título viejo que puede llegar
            # después y dejar el mensaje mintiendo.
            await responder(i, reproductor.saltar, refrescar=False)

        async def al_quitar(i):
            reproductor.lista.vaciar()
            if reproductor.voz:
                reproductor.voz.stop()
            await reproductor.desconectar()
            await reproductor.retirar_mensaje()
            if not i.response.is_done():
                await i.response.defer()

        pausa.callback = al_pausar
        bucle.callback = al_bucle
        siguiente.callback = al_siguiente
        quitar.callback = al_quitar
        for boton in (pausa, bucle, siguiente, quitar):
            vista.add_item(boton)
        return vista


def asegurar_opus() -> bool:
    """Carga la biblioteca que codifica la voz.

    discord.py la trae para Windows pero **no la carga sola**, y sin ella
    conectar al canal funciona y no se oye nada: un fallo mudo.
    """
    import discord.opus

    if discord.opus.is_loaded():
        return True
    try:
        discord.opus._load_default()
    except Exception as exc:  # noqa: BLE001 - se reporta, no se propaga
        registro.warning("no se pudo cargar opus: %s", exc)
    return discord.opus.is_loaded()


async def _callar(interaccion) -> None:
    """Quita el «pensando...» sin dejar mensaje.

    Discord obliga a responder a toda interacción, pero no obliga a que quede
    nada escrito. Los avisos de trámite —qué se pone, qué se encola— sobran en
    el chat: eso ya lo dice el mensaje de controles, y además queda en el
    registro de actividad de la aplicación.
    """
    try:
        await interaccion.delete_original_response()
    except Exception:  # noqa: BLE001 - no quedarse callado nunca es un fallo
        pass


async def _responder(interaccion, texto: str) -> None:
    """Para lo que el usuario sí necesita leer en Discord.

    Se reserva a lo que deja al usuario parado: un vídeo que no se puede
    reproducir, o unos controles que no aparecen. Si esto fuera al registro de
    la aplicación y ya está, habría que ir a mirar la ventana para enterarse.
    """
    try:
        await interaccion.followup.send(texto, ephemeral=True)
    except Exception:  # noqa: BLE001
        pass


async def retirar_controles(bot) -> None:
    """Quita los mensajes de control y sale de los canales de voz.

    Se llama al cerrar la aplicación. Unos controles huérfanos no responden a
    los botones y siguen anunciando una pista que ya no suena: desde el canal
    parece que el bot está puesto cuando no hay nadie al otro lado.
    """
    for repro in list(getattr(bot, "reproductores", {}).values()):
        try:
            repro.lista.vaciar()
            await repro.retirar_mensaje()
            await repro.desconectar()
        except Exception as exc:  # noqa: BLE001 - uno mal no impide los demás
            registro.warning("no se pudo recoger un reproductor: %s", exc)


def crear_bot(carpeta: str, avisar=None):
    """El cliente de Discord con sus comandos. Importa discord aquí."""
    import discord
    from discord import app_commands

    contar = avisar or (lambda _m: None)

    if not asegurar_opus():
        contar("falta la biblioteca opus: se conectará pero no sonará nada")

    intenciones = discord.Intents.default()  # sin permisos privilegiados
    bot = discord.Client(intents=intenciones)
    bot.tree = app_commands.CommandTree(bot)
    bot.reproductores: dict[int, Reproductor] = {}
    bot.carpeta = carpeta

    def reproductor_de(guild_id: int) -> Reproductor:
        if guild_id not in bot.reproductores:
            bot.reproductores[guild_id] = Reproductor(bot, bot.carpeta, contar)
        return bot.reproductores[guild_id]

    bot.reproductor_de = reproductor_de

    @bot.event
    async def on_ready():
        # A cada servidor donde esté: así aparece al instante en vez de tardar
        # hasta una hora, que es lo que tardan los comandos globales.
        for servidor in bot.guilds:
            try:
                bot.tree.copy_global_to(guild=servidor)
                await bot.tree.sync(guild=servidor)
            except Exception as exc:  # noqa: BLE001
                registro.warning("no se pudo sincronizar en %s: %s", servidor, exc)
        contar(f"listo como {bot.user} en {len(bot.guilds)} servidor(es)")

    async def poner(interaccion, consulta: str, bucle: bool) -> None:
        """El cuerpo de los dos comandos: sólo cambia el bucle.

        Son dos comandos y no un parámetro porque en Discord toda opción se
        escribe `nombre:valor`: poner una pista sin bucle obligaba a desplegar
        un sí/no. Como comando aparte se teclea de un tirón.
        """
        canal = getattr(interaccion.user.voice, "channel", None)
        if canal is None:
            await interaccion.response.send_message(
                "Entra antes a un canal de voz.", ephemeral=True
            )
            return

        # Buscar puede tardar unos segundos: Discord da 3 para responder.
        await interaccion.response.defer(ephemeral=True)
        repro = bot.reproductor_de(interaccion.guild_id)
        repro.carpeta = bot.carpeta

        try:
            pista = await asyncio.to_thread(
                resolver, consulta, bot.carpeta, interaccion.user.display_name
            )
        except ErrorBusqueda as exc:
            contar(f"no se pudo poner «{consulta}»: {exc}")
            await _responder(interaccion, str(exc))
            return

        # El bucle acompaña a la pista, así que se decide al encolarla y no
        # cambia cuando le llegue el turno.
        pista = replace(pista, bucle=bucle)
        puesto = repro.lista.anadir(pista)
        if puesto:
            contar(f"en cola ({puesto}): {pista.titulo}")
            # Sin mensaje: el de controles ya dice cuántas esperan turno.
            await _callar(interaccion)
            await repro.refrescar_mensaje()
            return

        contar(f"poniendo «{pista.titulo}» en {canal.name}")
        # Antes de nada, soltar los controles de la vez anterior: aquí no hay
        # nada sonando, así que lo que quede apuntado está caducado.
        await repro.retirar_mensaje()
        try:
            await repro.conectar(canal)
        except Exception as exc:  # noqa: BLE001
            repro.lista.vaciar()
            contar(f"no se pudo entrar en {canal.name}: {exc}")
            await _responder(interaccion, f"No pude entrar al canal de voz: {exc}")
            return

        # Primero sonar, luego los controles. Si se hiciera al revés, no poder
        # escribir en el canal impediría la música, que es lo que se pedía.
        await repro.reproducir_actual()

        try:
            repro.mensaje = await interaccion.channel.send(
                _texto_estado(repro.lista, False), view=Controles(repro)
            )
        except Exception as exc:  # noqa: BLE001 - suele ser falta de permiso
            contar(f"sonando, pero sin controles: no puedo escribir en "
                   f"#{getattr(interaccion.channel, 'name', '?')} ({exc})")
            # Aquí sí hace falta decirlo: si no, los botones no aparecen y no
            # hay forma de saber por qué.
            await _responder(
                interaccion,
                "Está sonando, pero no puedo publicar los controles aquí: "
                "me falta permiso para escribir en este canal.",
            )
        else:
            # Todo bien: los controles son la respuesta, no hace falta nada más.
            await _callar(interaccion)

    donde = "Nombre, búsqueda de YouTube o enlace"

    @bot.tree.command(
        name="play", description="Pon música en tu canal de voz, repitiéndose."
    )
    @app_commands.describe(consulta=donde)
    async def play(interaccion, consulta: str):
        await poner(interaccion, consulta, bucle=True)

    @bot.tree.command(
        name="playsinbucle",
        description="Igual que /play, pero suena una vez y pasa a la siguiente.",
    )
    @app_commands.describe(consulta=donde)
    async def play_sin_bucle(interaccion, consulta: str):
        await poner(interaccion, consulta, bucle=False)

    return bot
