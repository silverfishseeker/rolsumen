"""Ventana de la aplicación: puramente informativa.

Muestra el estado de los servicios y por dónde va el proceso. Los únicos
controles son un botón para forzar la búsqueda y otro para abrir la carpeta de
crónicas; el resto ocurre solo.

El trabajo pesado corre en un hilo aparte y se comunica con la ventana por una
cola, para que la interfaz nunca se congele.
"""

from __future__ import annotations

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
from .pipeline import orquestador, resumidor

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

DESCRIPCION_MODO = {
    "rol": "Crónicas de partidas de rol",
    "conversacion": "Resúmenes de conversaciones",
}


@dataclass
class Aviso:
    """Mensaje del hilo de trabajo hacia la ventana."""

    tipo: str  # 'log' | 'estado' | 'ocupado' | 'servicios'
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


class Ventana:
    def __init__(self, raiz: tk.Tk) -> None:
        self.raiz = raiz
        self.cola: queue.Queue[Aviso] = queue.Queue()
        self.configuracion = cfg.cargar()
        self.ocupado = False
        self._parar = threading.Event()

        raiz.title("Rolsumen")
        raiz.geometry("640x520")
        raiz.minsize(520, 400)
        raiz.protocol("WM_DELETE_WINDOW", self._al_cerrar)

        self._construir()
        self.raiz.after(INTERVALO_COLA_MS, self._vaciar_cola)
        self.raiz.after(INTERVALO_ESTADO_MS, self._refrescar_estado)
        self.raiz.after(INTERVALO_BUSQUEDA_MS, self._busqueda_periodica)
        self._arrancar()

    # ------------------------------------------------------------------ UI --

    def _construir(self) -> None:
        marco = ttk.Frame(self.raiz, padding=12)
        marco.pack(fill=tk.BOTH, expand=True)

        ttk.Label(marco, text="Rolsumen", font=("Segoe UI", 15, "bold")).pack(
            anchor=tk.W
        )
        descripcion = DESCRIPCION_MODO.get(self.configuracion.modo, "Resúmenes")
        self.subtitulo = ttk.Label(
            marco,
            text=f"{descripcion}  ·  modo: {self.configuracion.modo}",
            foreground=NEUTRO,
        )
        self.subtitulo.pack(anchor=tk.W, pady=(0, 10))

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
        caja_log.pack(fill=tk.BOTH, expand=True, pady=(10, 8))

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

        barra = ttk.Frame(marco)
        barra.pack(fill=tk.X)
        self.boton_buscar = ttk.Button(
            barra, text="Buscar grabaciones", command=self._buscar_ahora
        )
        self.boton_buscar.pack(side=tk.LEFT)
        ttk.Button(barra, text="Abrir crónicas", command=self._abrir_carpeta).pack(
            side=tk.LEFT, padx=6
        )
        self.estado = ttk.Label(barra, text="Iniciando...", foreground=NEUTRO)
        self.estado.pack(side=tk.RIGHT)

        self.progreso = ttk.Progressbar(marco, mode="indeterminate")

    # -------------------------------------------------------------- bucles --

    def _vaciar_cola(self) -> None:
        try:
            while True:
                self._aplicar(self.cola.get_nowait())
        except queue.Empty:
            pass
        finally:
            self.raiz.after(INTERVALO_COLA_MS, self._vaciar_cola)

    def _aplicar(self, aviso: Aviso) -> None:
        if aviso.tipo == "log":
            self._escribir(aviso.texto)
        elif aviso.tipo == "estado":
            self.estado.config(text=aviso.texto)
        elif aviso.tipo == "servicios" and aviso.datos:
            for clave, (texto, color) in _estado_servicios(aviso.datos).items():
                self.indicadores[clave].config(text=texto, foreground=color)
        elif aviso.tipo == "ocupado":
            self._marcar_ocupado(bool(aviso.datos and aviso.datos.get("valor")))

    def _busqueda_periodica(self) -> None:
        if not self.ocupado:
            self._buscar_ahora(silencioso=True)
        self.raiz.after(INTERVALO_BUSQUEDA_MS, self._busqueda_periodica)

    def _refrescar_estado(self) -> None:
        if not self.ocupado:
            self._en_hilo(self._comprobar_servicios)
        self.raiz.after(INTERVALO_ESTADO_MS, self._refrescar_estado)

    # ------------------------------------------------------------ acciones --

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
            self._avisar(
                "Docker no responde. Abre Docker Desktop y pulsa 'Buscar grabaciones'."
            )
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
        self._procesar_pendientes(silencioso=True)

    def _comprobar_servicios(self) -> None:
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

    def _buscar_ahora(self, silencioso: bool = False) -> None:
        if not self.ocupado:
            self._en_hilo(lambda: self._procesar_pendientes(silencioso))

    def _procesar_pendientes(self, silencioso: bool = False) -> None:
        if not docker_manager.esta_levantado():
            if not silencioso:
                self._avisar("Craig no está en marcha; no se puede buscar nada.")
            return
        if not resumidor.ollama_disponible():
            if not silencioso:
                self._avisar("Ollama no responde. Arráncalo para generar crónicas.")
            return

        self._ocupado(True)
        try:
            resultados = orquestador.procesar_pendientes(
                self.configuracion, avisar=self._avisar, detener=self._parar.is_set
            )
            if resultados:
                correctos = sum(1 for r in resultados if r.ok)
                self._enviar(
                    Aviso(
                        tipo="estado",
                        texto=f"{correctos}/{len(resultados)} crónicas generadas",
                    )
                )
            elif not silencioso:
                self._enviar(Aviso(tipo="estado", texto="Sin novedades"))
        finally:
            self._ocupado(False)

    def _abrir_carpeta(self) -> None:
        cfg.DIR_RESUMENES.mkdir(parents=True, exist_ok=True)
        abridor = {"win32": "explorer", "darwin": "open"}.get(sys.platform, "xdg-open")
        try:
            subprocess.Popen([abridor, str(cfg.DIR_RESUMENES)])
        except OSError as exc:
            self._escribir(f"No se pudo abrir la carpeta: {exc}")

    def _al_cerrar(self) -> None:
        self._parar.set()
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
        self.cola.put(aviso)

    def _avisar(self, texto: str) -> None:
        """Callback que reciben los módulos del pipeline."""
        self._enviar(Aviso(tipo="log", texto=texto))
        self._enviar(Aviso(tipo="estado", texto=texto[:60]))

    def _ocupado(self, valor: bool) -> None:
        self._enviar(Aviso(tipo="ocupado", datos={"valor": valor}))

    def _marcar_ocupado(self, valor: bool) -> None:
        self.ocupado = valor
        if valor:
            self.boton_buscar.state(["disabled"])
            self.progreso.pack(fill=tk.X, pady=(6, 0))
            self.progreso.start(12)
        else:
            self.boton_buscar.state(["!disabled"])
            self.progreso.stop()
            self.progreso.pack_forget()

    def _escribir(self, texto: str) -> None:
        marca = datetime.now().strftime("%H:%M:%S")
        self.log.config(state=tk.NORMAL)
        self.log.insert(tk.END, f"[{marca}] {texto}\n")
        self.log.see(tk.END)
        self.log.config(state=tk.DISABLED)


def lanzar() -> None:
    raiz = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    Ventana(raiz)
    raiz.mainloop()
