"""Ventana de la aplicación, en tres pestañas.

    Trabajo         qué hay (grabaciones, transcripciones, crónicas) y el botón
                    que lleva cada cosa al paso siguiente
    Estado          servicios y registro de actividad
    Configuración   todo lo que antes había que editar a mano en config.ini

Abajo, siempre visible, en qué se está trabajando, cuántas tareas esperan y el
botón de cancelar.

El trabajo pesado corre en el hilo de la cola y se comunica con la ventana por
otra cola de mensajes, para que la interfaz nunca se congele.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from tkinter import scrolledtext, ttk

from . import config as cfg
from . import dependencias, docker_manager
from .pipeline import cola as modulo_cola
from .pipeline import orquestador, resumidor
from .craig_client import ErrorCraig
from .procesos import SIN_CONSOLA
from .pipeline.cola import RESUMIR, TRANSCRIBIR, Cola, Tarea

INTERVALO_BUSQUEDA_MS = 60_000
INTERVALO_COLA_MS = 100
INTERVALO_ESTADO_MS = 10_000

OK = "#2e7d32"
MAL = "#c62828"
ESPERA = "#ef6c00"
NEUTRO = "#666666"

SERVICIOS = (
    ("docker", "Docker"),
    ("craig", "Craig (grabación)"),
    ("ollama", "Ollama (resúmenes)"),
    ("ffmpeg", "ffmpeg (audio)"),
    ("gpu", "GPU (transcripción)"),
)

# Cada lista sabe qué hace su botón y de dónde saca las filas.
NOMBRE_EJECUCION = {"automatico": "automático", "manual": "manual"}

LISTAS = (
    ("grabaciones", "Grabaciones", "Transcribir"),
    ("transcripciones", "Transcripciones", "Resumir"),
    ("resumenes", "Crónicas", "Abrir"),
)


@dataclass
class Aviso:
    """Mensaje del hilo de trabajo hacia la ventana."""

    tipo: str  # 'log' | 'servicios' | 'cola' | 'listas'
    texto: str = ""
    datos: dict | None = None


def _estado_servicios(datos: dict) -> dict[str, tuple[str, str]]:
    """Traduce el diagnóstico a (texto, color) por servicio."""
    if not datos.get("docker_instalado"):
        docker = ("no instalado", MAL)
    elif datos.get("docker"):
        docker = ("en marcha", OK)
    else:
        docker = ("parado (abre Docker Desktop)", MAL)

    if not datos.get("craig_instalado"):
        craig = ("sin instalar", MAL)
    elif not datos.get("craig_configurado"):
        craig = ("falta configurar", ESPERA)
    elif datos.get("craig"):
        craig = ("grabando disponible", OK)
    else:
        craig = ("parado", ESPERA)

    return {
        "docker": docker,
        "craig": craig,
        "ollama": ("disponible", OK) if datos.get("ollama") else ("no responde", MAL),
        "ffmpeg": ("disponible", OK) if datos.get("ffmpeg") else ("no encontrado", MAL),
        "gpu": (
            (datos.get("gpu_nombre") or "activa", OK)
            if datos.get("gpu")
            else ("sin GPU (irá lento)", ESPERA)
        ),
    }


# Windows agrupa las ventanas por este identificador. Sin él, la aplicación se
# agrupa bajo el intérprete y la barra de tareas muestra el icono de Python en
# lugar del suyo, por mucho que la ventana tenga el correcto.
ID_APLICACION = "silverfishlord.Rolsumen"


def _identificar_aplicacion() -> None:
    """Separa la aplicación del intérprete de cara a la barra de tareas.

    **Tiene que llamarse antes de crear la ventana.** Windows decide el icono
    de la barra de tareas cuando aparece la primera ventana; hacerlo después no
    surte efecto y se sigue viendo el icono de Python.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(ID_APLICACION)
    except (AttributeError, OSError):
        pass


def _aplicar_icono(raiz: tk.Tk) -> None:
    """Pone el icono en la ventana y en la barra de tareas.

    `iconbitmap` basta para la barra de título, pero la barra de tareas usa el
    icono grande de la ventana (`WM_SETICON`), que tkinter no rellena. Sin
    ponerlo a mano, ahí se sigue viendo el icono de Python.
    """
    try:
        raiz.iconbitmap(default=str(cfg.RUTA_ICONO))
    except tk.TclError:
        pass

    if sys.platform != "win32" or not cfg.RUTA_ICONO.exists():
        return

    try:
        import ctypes

        raiz.update_idletasks()  # hasta que no existe de verdad no hay ventana
        usuario = ctypes.windll.user32
        # winfo_id() da la ventana interna; la de la barra de tareas es su padre.
        ventana = usuario.GetParent(raiz.winfo_id()) or raiz.winfo_id()

        IMAGE_ICON, LR_LOADFROMFILE, LR_DEFAULTSIZE = 1, 0x10, 0x40
        WM_SETICON, ICON_SMALL, ICON_BIG = 0x0080, 0, 1

        for cual, medida in ((ICON_SMALL, 16), (ICON_BIG, 32)):
            icono = usuario.LoadImageW(
                None,
                str(cfg.RUTA_ICONO),
                IMAGE_ICON,
                medida,
                medida,
                LR_LOADFROMFILE | LR_DEFAULTSIZE,
            )
            if icono:
                usuario.SendMessageW(ventana, WM_SETICON, cual, icono)
    except (AttributeError, OSError, tk.TclError):
        # Sin icono la aplicación funciona igual; no merece romper el arranque.
        pass


def _abrir_con_el_sistema(ruta) -> None:
    """Abre un archivo o carpeta con el programa que le toque en este sistema."""
    if sys.platform == "win32":
        # `os.startfile` evita pasar por `cmd`, que asomaría una consola.
        os.startfile(str(ruta))  # noqa: S606 - es la ruta de un archivo nuestro
    else:
        abridor = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.Popen([abridor, str(ruta)], **SIN_CONSOLA)


class Ventana:
    def __init__(self, raiz: tk.Tk) -> None:
        self.raiz = raiz
        self.mensajes: queue.Queue[Aviso] = queue.Queue()
        self.configuracion = cfg.cargar()
        self._parar = threading.Event()
        # `docker compose ps` puede tardar más que el intervalo de refresco;
        # sin esto se acumularían hilos, uno cada diez segundos.
        self._comprobando = threading.Event()

        # Modo automático: solo actúa sobre grabaciones que aparezcan a partir
        # de ahora. Lo anterior se queda esperando en la pestaña Trabajo.
        # None = todavía no se ha podido preguntar a Craig; hasta que conteste
        # no se considera nada "nuevo", porque lo parecería todo.
        self._conocidas: set[str] | None = None

        self.cola = Cola(
            ejecutar=self._ejecutar_tarea,
            al_cambiar=self._cola_cambio,
            al_fallar=lambda tarea, exc: self._avisar(
                f"ERROR inesperado en {tarea.accion} {tarea.clave}: {exc}"
            ),
        )

        raiz.title("Rolsumen")
        _aplicar_icono(raiz)
        raiz.geometry("760x600")
        raiz.minsize(660, 500)
        raiz.protocol("WM_DELETE_WINDOW", self._al_cerrar)

        self._construir()
        # La barra se pinta con cada cambio de la cola; sin esto se quedaría
        # con el texto de relleno hasta que hubiera una primera tarea.
        self._pintar_barra({})
        self.cola.arrancar()
        self.raiz.after(INTERVALO_COLA_MS, self._vaciar_mensajes)
        self.raiz.after(INTERVALO_ESTADO_MS, self._refrescar_estado)
        self.raiz.after(INTERVALO_BUSQUEDA_MS, self._busqueda_periodica)
        self._arrancar()

    # ------------------------------------------------------------------ UI --

    def _construir(self) -> None:
        marco = ttk.Frame(self.raiz, padding=(10, 8))
        marco.pack(fill=tk.BOTH, expand=True)

        self.pestanas = ttk.Notebook(marco)
        self.pestanas.pack(fill=tk.BOTH, expand=True)
        self.pestanas.add(self._pestana_trabajo(), text="  Trabajo  ")
        self.pestanas.add(self._pestana_estado(), text="  Estado  ")
        self.pestanas.add(self._pestana_config(), text="  Configuración  ")

        self._barra_inferior(marco)

    def _pestana_trabajo(self) -> ttk.Frame:
        marco = ttk.Frame(self.pestanas, padding=10)

        columnas = ttk.Frame(marco)
        columnas.pack(fill=tk.BOTH, expand=True)

        self.listas: dict[str, tk.Listbox] = {}
        self.filas: dict[str, list] = {}

        for indice, (clave, titulo, _) in enumerate(LISTAS):
            caja = ttk.LabelFrame(columnas, text=titulo, padding=6)
            caja.grid(row=0, column=indice, sticky="nsew", padx=(0 if not indice else 6, 0))
            columnas.columnconfigure(indice, weight=1)

            lista = tk.Listbox(
                caja, exportselection=False, activestyle="none", font=("Segoe UI", 9)
            )
            # Los nombres son largos y la columna estrecha: sin esto se cortan
            # justo en la parte que dice en qué estado está cada cosa.
            desplazar = ttk.Scrollbar(
                caja, orient=tk.HORIZONTAL, command=lista.xview
            )
            lista.config(xscrollcommand=desplazar.set)
            desplazar.pack(side=tk.BOTTOM, fill=tk.X)
            lista.pack(fill=tk.BOTH, expand=True)
            lista.bind("<<ListboxSelect>>", lambda _e, c=clave: self._seleccion(c))
            lista.bind("<Double-Button-1>", lambda _e: self._paso_siguiente())
            self.listas[clave] = lista
            self.filas[clave] = []

        columnas.rowconfigure(0, weight=1)

        acciones = ttk.Frame(marco)
        acciones.pack(fill=tk.X, pady=(10, 0))

        self.boton_paso = ttk.Button(
            acciones,
            text="Selecciona algo de una lista",
            state=tk.DISABLED,
            command=self._paso_siguiente,
        )
        self.boton_paso.pack(fill=tk.X, ipady=8)

        ttk.Button(acciones, text="Actualizar listas", command=self._refrescar_listas).pack(
            pady=(6, 0)
        )
        return marco

    def _pestana_estado(self) -> ttk.Frame:
        marco = ttk.Frame(self.pestanas, padding=10)

        caja = ttk.LabelFrame(marco, text="Servicios", padding=10)
        caja.pack(fill=tk.X)

        self.indicadores: dict[str, ttk.Label] = {}
        for clave, etiqueta in SERVICIOS:
            fila = ttk.Frame(caja)
            fila.pack(fill=tk.X, pady=1)
            ttk.Label(fila, text=etiqueta, width=22).pack(side=tk.LEFT)
            valor = ttk.Label(fila, text="comprobando...", foreground=NEUTRO)
            valor.pack(side=tk.LEFT)
            self.indicadores[clave] = valor

        caja_log = ttk.LabelFrame(marco, text="Actividad", padding=6)
        caja_log.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

        self.log = scrolledtext.ScrolledText(
            caja_log,
            height=12,
            wrap=tk.WORD,
            state=tk.DISABLED,
            font=("Consolas", 9),
            background="#1e1e1e",
            foreground="#d4d4d4",
            relief=tk.FLAT,
        )
        self.log.pack(fill=tk.BOTH, expand=True)
        return marco

    def _pestana_config(self) -> ttk.Frame:
        contenedor = ttk.Frame(self.pestanas)
        lienzo = tk.Canvas(contenedor, highlightthickness=0)
        barra = ttk.Scrollbar(contenedor, orient=tk.VERTICAL, command=lienzo.yview)
        marco = ttk.Frame(lienzo, padding=10)

        marco.bind(
            "<Configure>", lambda _e: lienzo.configure(scrollregion=lienzo.bbox("all"))
        )
        ventana_interna = lienzo.create_window((0, 0), window=marco, anchor="nw")
        lienzo.bind(
            "<Configure>", lambda e: lienzo.itemconfig(ventana_interna, width=e.width)
        )
        lienzo.configure(yscrollcommand=barra.set)
        lienzo.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        barra.pack(side=tk.RIGHT, fill=tk.Y)

        self.campos: dict[tuple[str, str], tk.Variable] = {}
        # Una sola fuente para el valor de cada casilla, compartida con el
        # repintado posterior a guardar.
        inicial = self._valores_actuales()

        general = ttk.LabelFrame(marco, text="General", padding=8)
        general.pack(fill=tk.X)
        self._desplegable(
            general, ("general", "ejecucion"), "Ejecución", inicial[("general", "ejecucion")], cfg.EJECUCIONES
        )
        self._desplegable(
            general, ("general", "modo"), "Tipo de resumen", inicial[("general", "modo")], cfg.MODOS
        )
        self._entrada(general, ("general", "idioma"), "Idioma (ISO)", inicial[("general", "idioma")])
        self._entrada(
            general,
            ("general", "carpeta_resumenes"),
            "Carpeta extra",
            inicial[("general", "carpeta_resumenes")],
        )

        modelos = ttk.LabelFrame(marco, text="Modelos", padding=8)
        modelos.pack(fill=tk.X, pady=(8, 0))
        self._desplegable(
            modelos,
            ("modelos", "transcripcion"),
            "Transcripción",
            inicial[("modelos", "transcripcion")],
            ("large-v3", "medium", "small", "base"),
        )
        self._desplegable(
            modelos,
            ("modelos", "precision"),
            "Precisión",
            inicial[("modelos", "precision")],
            ("float16", "int8_float16", "int8"),
        )
        self._desplegable(
            modelos, ("modelos", "dispositivo"), "Dispositivo", inicial[("modelos", "dispositivo")],
            ("auto", "cuda", "cpu"),
        )
        self._entrada(modelos, ("modelos", "resumen"), "Modelo de resumen", inicial[("modelos", "resumen")])
        self._entrada(
            modelos,
            ("modelos", "contexto_resumen"),
            "Contexto",
            inicial[("modelos", "contexto_resumen")],
        )

        discord = ttk.LabelFrame(marco, text="Discord", padding=8)
        discord.pack(fill=tk.X, pady=(8, 0))
        self._entrada(discord, ("discord", "id_aplicacion"), "Application ID", inicial[("discord", "id_aplicacion")])
        self._entrada(discord, ("discord", "token_bot"), "Token del bot", inicial[("discord", "token_bot")], oculto=True)
        self._entrada(
            discord, ("discord", "secreto_cliente"), "Client secret", inicial[("discord", "secreto_cliente")], oculto=True
        )

        jugadores = ttk.LabelFrame(marco, text="Jugadores", padding=8)
        jugadores.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(
            jugadores,
            text="Un «usuario = personaje» por línea. Si falta, se usa el nick de Discord.",
            foreground=NEUTRO,
            wraplength=560,
        ).pack(anchor=tk.W, pady=(0, 4))
        self.jugadores = tk.Text(jugadores, height=5, font=("Consolas", 9))
        self.jugadores.pack(fill=tk.X)
        self.jugadores.insert(
            "1.0",
            "\n".join(
                f"{u} = {p}" for u, p in self.configuracion.jugadores.items()
            ),
        )

        pie = ttk.Frame(marco)
        pie.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(pie, text="Guardar", command=self._guardar_config).pack(side=tk.LEFT)
        self.aviso_config = ttk.Label(pie, text="", foreground=NEUTRO)
        self.aviso_config.pack(side=tk.LEFT, padx=8)
        return contenedor

    def _entrada(self, padre, clave, etiqueta, valor, oculto: bool = False) -> None:
        fila = ttk.Frame(padre)
        fila.pack(fill=tk.X, pady=2)
        ttk.Label(fila, text=etiqueta, width=18).pack(side=tk.LEFT)
        variable = tk.StringVar(value=valor)
        ttk.Entry(fila, textvariable=variable, show="•" if oculto else "").pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )
        self.campos[clave] = variable

    def _desplegable(self, padre, clave, etiqueta, valor, opciones) -> None:
        fila = ttk.Frame(padre)
        fila.pack(fill=tk.X, pady=2)
        ttk.Label(fila, text=etiqueta, width=18).pack(side=tk.LEFT)
        variable = tk.StringVar(value=valor)
        ttk.Combobox(
            fila, textvariable=variable, values=list(opciones), state="readonly"
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.campos[clave] = variable

    def _barra_inferior(self, padre) -> None:
        barra = ttk.Frame(padre, padding=(0, 8, 0, 0))
        barra.pack(fill=tk.X)

        izquierda = ttk.Frame(barra)
        izquierda.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.etiqueta_tarea = ttk.Label(
            izquierda, text="Sin tareas.", font=("Segoe UI", 9, "bold")
        )
        self.etiqueta_tarea.pack(anchor=tk.W)
        self.etiqueta_cola = ttk.Label(izquierda, text="", foreground=NEUTRO)
        self.etiqueta_cola.pack(anchor=tk.W)

        self.boton_cancelar = ttk.Button(
            barra, text="Cancelar", state=tk.DISABLED, command=self.cola.cancelar_actual
        )
        self.boton_cancelar.pack(side=tk.RIGHT)

    # -------------------------------------------------------------- bucles --

    def _vaciar_mensajes(self) -> None:
        try:
            while True:
                self._aplicar(self.mensajes.get_nowait())
        except queue.Empty:
            pass
        finally:
            self.raiz.after(INTERVALO_COLA_MS, self._vaciar_mensajes)

    def _aplicar(self, aviso: Aviso) -> None:
        if aviso.tipo == "log":
            self._escribir(aviso.texto)
        elif aviso.tipo == "servicios" and aviso.datos:
            for clave, (texto, color) in _estado_servicios(aviso.datos).items():
                self.indicadores[clave].config(text=texto, foreground=color)
        elif aviso.tipo == "cola":
            self._pintar_barra(aviso.datos or {})
        elif aviso.tipo == "listas":
            self._pintar_listas(aviso.datos or {})

    def _busqueda_periodica(self) -> None:
        if self.configuracion.ejecucion == "automatico" and not self.cola.ocupada:
            self._en_hilo(self._buscar_nuevas)
        self.raiz.after(INTERVALO_BUSQUEDA_MS, self._busqueda_periodica)

    def _refrescar_estado(self) -> None:
        if not self._comprobando.is_set():
            self._en_hilo(self._comprobar_servicios)
        self.raiz.after(INTERVALO_ESTADO_MS, self._refrescar_estado)

    # ------------------------------------------------------------ arranque --

    def _arrancar(self) -> None:
        self._escribir("Iniciando Rolsumen...")
        if cfg.crear_config_si_falta():
            self._escribir(f"Creado archivo de configuración: {cfg.RUTA_CONFIG}")
        cfg.asegurar_carpetas()
        dependencias.preparar_entorno()
        orquestador.limpiar_temporales()

        for dependencia in dependencias.comprobar_todo():
            if not dependencia.disponible:
                self._escribir(f"Aviso ({dependencia.nombre}): {dependencia.ayuda}")

        self._en_hilo(self._levantar_craig)

    def _levantar_craig(self) -> None:
        self._avisar("Comprobando Docker...")

        if not docker_manager.docker_instalado():
            self._avisar("Docker no está instalado. Craig no puede arrancar.")
        elif not docker_manager.docker_en_marcha():
            self._avisar("Docker no responde. Abre Docker Desktop.")
        elif docker_manager.esta_levantado():
            self._avisar("Craig ya estaba en marcha.")
        elif faltan := self.configuracion.discord.faltantes():
            self._avisar(
                f"Faltan credenciales de Discord en {cfg.RUTA_CONFIG.name} "
                f"[discord]: {', '.join(faltan)}"
            )
        else:
            self._avisar("Levantando Craig (docker compose up)...")
            resultado = docker_manager.levantar(credenciales=self.configuracion.discord)
            self._avisar(
                "Craig levantado."
                if resultado.ok
                else f"No se pudo levantar Craig: {resultado.mensaje}"
            )

        self._comprobar_servicios()

        self._fijar_referencia()
        self._refrescar_listas()
        if self.configuracion.ejecucion == "automatico":
            self._avisar("Modo automático: esperando nuevas grabaciones...")
        else:
            self._avisar("Modo manual: lanza los pasos desde la pestaña Trabajo.")

    # -------------------------------------------------------------- listas --

    def _refrescar_listas(self) -> None:
        self._en_hilo(self._recolectar_listas)

    def _recolectar_listas(self) -> None:
        self._enviar(
            Aviso(
                tipo="listas",
                datos={
                    "grabaciones": orquestador.grabaciones_disponibles(),
                    "transcripciones": orquestador.transcripciones_disponibles(),
                    "resumenes": orquestador.resumenes_disponibles(),
                },
            )
        )

    def _pintar_listas(self, datos: dict) -> None:
        for clave, _, _ in LISTAS:
            filas = datos.get(clave, [])
            lista = self.listas[clave]
            seleccion = self._clave_seleccionada(clave)

            lista.delete(0, tk.END)
            for fila in filas:
                lista.insert(tk.END, f"{fila.titulo}   ({fila.detalle})")
            self.filas[clave] = filas

            for indice, fila in enumerate(filas):
                if fila.clave == seleccion:
                    lista.selection_set(indice)
        self._actualizar_boton()

    def _clave_seleccionada(self, lista: str) -> str | None:
        indices = self.listas[lista].curselection()
        if not indices:
            return None
        filas = self.filas[lista]
        return filas[indices[0]].clave if indices[0] < len(filas) else None

    def _seleccion(self, lista: str) -> None:
        # Selección única en las tres listas: el botón hace una sola cosa.
        for clave, _, _ in LISTAS:
            if clave != lista:
                self.listas[clave].selection_clear(0, tk.END)
        self._actualizar_boton()

    def _lista_activa(self) -> tuple[str, str] | None:
        for clave, _, _ in LISTAS:
            elegida = self._clave_seleccionada(clave)
            if elegida:
                return clave, elegida
        return None

    def _actualizar_boton(self) -> None:
        activa = self._lista_activa()
        if not activa:
            self.boton_paso.config(
                text="Selecciona algo de una lista", state=tk.DISABLED
            )
            return
        lista, clave = activa
        accion = next(a for c, _, a in LISTAS if c == lista)
        self.boton_paso.config(text=f"{accion}  ·  {clave}", state=tk.NORMAL)

    def _paso_siguiente(self) -> None:
        activa = self._lista_activa()
        if not activa:
            return
        lista, clave = activa

        if lista == "resumenes":
            # Las listas se refrescan solas al terminar una tarea, asi que la
            # fila seleccionada puede haber desaparecido entre el clic y esto.
            ruta = next(
                (f.ruta for f in self.filas[lista] if f.clave == clave), None
            )
            if ruta is None:
                self._escribir(f"{clave} ya no esta en la lista.")
                self._refrescar_listas()
                return
            try:
                _abrir_con_el_sistema(ruta)
            except OSError as exc:
                self._escribir(f"No se pudo abrir {ruta}: {exc}")
            return

        accion = TRANSCRIBIR if lista == "grabaciones" else RESUMIR
        if self.cola.contiene(accion, clave):
            self._escribir(f"{clave} ya está en la cola.")
            return
        self.cola.encolar(Tarea(accion=accion, clave=clave, titulo=clave))
        self._escribir(f"En cola: {accion} {clave}")

    # -------------------------------------------------------------- tareas --

    def _ejecutar_tarea(self, tarea: Tarea, cancelado) -> None:
        """Corre en el hilo de la cola: aquí no se toca la interfaz."""
        try:
            if tarea.accion == TRANSCRIBIR:
                try:
                    grabacion = self._buscar_grabacion(tarea.clave)
                except ErrorCraig as exc:
                    self._avisar(f"No se pudo consultar Craig: {exc}")
                    return
                if grabacion is None:
                    self._avisar(
                        f"La grabación {tarea.clave} ya no está en Craig "
                        "(las borra pasado su plazo de retención)."
                    )
                    return
                resultado = orquestador.transcribir_grabacion(
                    grabacion, self.configuracion, avisar=self._avisar, cancelado=cancelado
                )
                if resultado.ok and tarea.encadenar:
                    self.cola.encolar(
                        Tarea(
                            accion=RESUMIR,
                            clave=orquestador.etiqueta_de(grabacion),
                            titulo=tarea.titulo,
                        )
                    )
            else:
                orquestador.reprocesar(
                    tarea.clave, self.configuracion, avisar=self._avisar, cancelado=cancelado
                )
        finally:
            self._recolectar_listas()

    def _buscar_grabacion(self, id_grabacion: str):
        """La grabacion, None si no existe, o ErrorCraig si no se pudo preguntar.

        Son casos distintos: decirle al usuario que su grabacion desaparecio
        cuando lo que pasa es que Craig no contesta manda a buscar donde no es.
        """
        return next(
            (
                g
                for g in orquestador.craig_client.grabaciones_terminadas()
                if g.id == id_grabacion
            ),
            None,
        )

    def _fijar_referencia(self) -> bool:
        """Anota qué grabaciones ya existían. Falla en silencio si Craig no está."""
        if self._conocidas is not None:
            return True
        conocidas = orquestador.ids_terminadas()
        if conocidas is None:
            return False
        self._conocidas = conocidas
        return True

    def _buscar_nuevas(self) -> None:
        # Sin referencia no se puede decir qué es nuevo: se fija y se espera al
        # siguiente ciclo, que es cuando ya hay con qué comparar.
        if not self._fijar_referencia():
            return

        encoladas = []
        for grabacion in orquestador.grabaciones_nuevas(self._conocidas):
            if self.cola.contiene(TRANSCRIBIR, grabacion.id):
                continue
            self._conocidas.add(grabacion.id)
            self._avisar(f"Nueva grabación detectada: {grabacion.id}")
            self.cola.encolar(
                Tarea(
                    accion=TRANSCRIBIR,
                    clave=grabacion.id,
                    titulo=orquestador.etiqueta_de(grabacion),
                    encadenar=True,
                )
            )
            encoladas.append(grabacion)
        if encoladas:
            self._recolectar_listas()

    def _cola_cambio(self, estado: modulo_cola.Estado) -> None:
        self._enviar(
            Aviso(
                tipo="cola",
                datos={
                    "titulo": estado.actual.titulo if estado.actual else "",
                    "accion": estado.actual.accion if estado.actual else "",
                    "en_cola": estado.en_cola,
                    "detalle": estado.detalle,
                },
            )
        )

    def _pintar_barra(self, datos: dict) -> None:
        modo = NOMBRE_EJECUCION.get(
            self.configuracion.ejecucion, self.configuracion.ejecucion
        )
        accion, titulo = datos.get("accion"), datos.get("titulo")

        if accion:
            verbo = "Transcribiendo" if accion == TRANSCRIBIR else "Resumiendo"
            detalle = datos.get("detalle") or ""
            self.etiqueta_tarea.config(
                text=f"{verbo} {titulo}" + (f"  ·  {detalle}" if detalle else "")
            )
            self.boton_cancelar.config(state=tk.NORMAL)
        else:
            espera = (
                "esperando nuevas grabaciones"
                if self.configuracion.ejecucion == "automatico"
                else "a la espera de que lances un paso"
            )
            self.etiqueta_tarea.config(text=f"Sin tareas: {espera}.")
            self.boton_cancelar.config(state=tk.DISABLED)

        en_cola = datos.get("en_cola", 0)
        pendientes = f"  ·  {en_cola} en cola" if en_cola else ""
        self.etiqueta_cola.config(text=f"modo {modo}{pendientes}")

    # ------------------------------------------------------- configuración --

    def _guardar_config(self) -> None:
        valores = {clave: variable.get().strip() for clave, variable in self.campos.items()}

        jugadores = {}
        for linea in self.jugadores.get("1.0", tk.END).splitlines():
            if "=" in linea and not linea.strip().startswith("#"):
                usuario, personaje = linea.split("=", 1)
                if usuario.strip() and personaje.strip():
                    jugadores[usuario.strip().lower()] = personaje.strip()

        try:
            cfg.guardar_valores(valores)
            cfg.guardar_jugadores(jugadores)
        except OSError as exc:
            self.aviso_config.config(text=f"No se pudo guardar: {exc}", foreground=MAL)
            return

        antes = dict(valores)
        self.configuracion = cfg.cargar()
        # Los campos se repintan con lo que ha quedado de verdad: un modo
        # desconocido cae al de por defecto y un contexto no numérico también.
        # Sin esto, la casilla seguiría mostrando algo que la aplicación ignora.
        self._refrescar_campos()
        corregidos = [
            clave for clave, valor in antes.items()
            if self.campos[clave].get() != valor
        ]

        if corregidos:
            nombres = ", ".join(c for _, c in corregidos)
            self.aviso_config.config(
                text=f"Guardado; se corrigió: {nombres}", foreground=ESPERA
            )
            self._escribir(f"Configuración guardada (valores corregidos: {nombres}).")
        else:
            self.aviso_config.config(
                text=f"Guardado en {cfg.RUTA_CONFIG.name}", foreground=OK
            )
            self._escribir("Configuración guardada.")
        self._cola_cambio(self.cola.estado())

    def _valores_actuales(self) -> dict[tuple[str, str], str]:
        """Lo que hay que mostrar en cada casilla, según la configuración viva."""
        c = self.configuracion
        m = c.modelos
        d = c.discord
        return {
            ("general", "ejecucion"): c.ejecucion,
            ("general", "modo"): c.modo,
            ("general", "idioma"): c.idioma,
            ("general", "carpeta_resumenes"): str(c.carpeta_resumenes_extra or ""),
            ("modelos", "transcripcion"): m.transcripcion,
            ("modelos", "precision"): m.precision,
            ("modelos", "dispositivo"): m.dispositivo,
            ("modelos", "resumen"): m.resumen,
            ("modelos", "contexto_resumen"): str(m.contexto_resumen),
            ("discord", "id_aplicacion"): d.id_aplicacion,
            ("discord", "token_bot"): d.token_bot,
            ("discord", "secreto_cliente"): d.secreto_cliente,
        }

    def _refrescar_campos(self) -> None:
        for clave, valor in self._valores_actuales().items():
            if clave in self.campos:
                self.campos[clave].set(valor)

    # ------------------------------------------------------------ servicios --

    def _comprobar_servicios(self) -> None:
        self._comprobando.set()
        try:
            self._recoger_servicios()
        finally:
            self._comprobando.clear()

    def _recoger_servicios(self) -> None:
        diag = docker_manager.diagnostico()
        gpu = dependencias.comprobar_gpu()
        self._enviar(
            Aviso(
                tipo="servicios",
                datos={
                    "docker": diag["docker_en_marcha"],
                    "docker_instalado": diag["docker_instalado"],
                    "craig": diag["craig_levantado"],
                    "craig_instalado": diag["craig_instalado"],
                    "craig_configurado": diag["craig_configurado"],
                    "ollama": resumidor.ollama_disponible(),
                    "ffmpeg": dependencias.comprobar_ffmpeg().disponible,
                    "gpu": gpu.disponible,
                    "gpu_nombre": gpu.ruta,
                },
            )
        )

    # ------------------------------------------------------------- cierre --

    def _al_cerrar(self) -> None:
        self._parar.set()
        self.cola.parar()
        self._escribir("Cerrando: bajando Craig...")
        self.raiz.update_idletasks()
        try:
            docker_manager.bajar()
        except Exception:  # noqa: BLE001 - cerrar nunca debe fallar
            pass
        self.raiz.destroy()

    # ------------------------------------------------------------ utilidad --

    def _en_hilo(self, funcion) -> None:
        threading.Thread(target=funcion, daemon=True).start()

    def _enviar(self, aviso: Aviso) -> None:
        self.mensajes.put(aviso)

    def _avisar(self, texto: str) -> None:
        self._enviar(Aviso(tipo="log", texto=texto))
        if self.cola.ocupada:
            self.cola.detallar(texto)

    def _escribir(self, texto: str) -> None:
        marca = datetime.now().strftime("%H:%M:%S")
        self.log.config(state=tk.NORMAL)
        self.log.insert(tk.END, f"[{marca}] {texto}\n")
        self.log.see(tk.END)
        self.log.config(state=tk.DISABLED)


def lanzar() -> None:
    # Antes que nada: si no, la barra de tareas se queda con el icono de Python.
    _identificar_aplicacion()
    raiz = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    Ventana(raiz)
    raiz.mainloop()
