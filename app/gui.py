"""Ventana de la aplicación: puramente informativa.

Muestra el estado de los servicios y por dónde va el proceso. Los únicos
controles son un botón para forzar una búsqueda y otro para abrir la carpeta
de crónicas; todo lo demás ocurre solo.

Todo el trabajo pesado (Docker, Whisper, Ollama) corre en un hilo aparte y se
comunica con la ventana mediante una cola, para que la interfaz nunca se
congele.
"""

from __future__ import annotations

import queue
import subprocess
import sys
import threading
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import scrolledtext, ttk

from . import config as cfg
from . import dependencias, docker_manager
from .pipeline import orquestador, resumidor

INTERVALO_BUSQUEDA_MS = 60_000  # cada minuto se buscan grabaciones nuevas
INTERVALO_COLA_MS = 100
INTERVALO_ESTADO_MS = 10_000

COLOR_OK = "#2e7d32"
COLOR_MAL = "#c62828"
COLOR_ESPERA = "#ef6c00"
COLOR_NEUTRO = "#666666"


@dataclass
class Aviso:
    """Mensaje del hilo de trabajo hacia la ventana."""

    tipo: str  # 'log' | 'estado' | 'ocupado' | 'servicios'
    texto: str = ""
    datos: dict | None = None


class Ventana:
    """Ventana principal de Rolsumen."""

    def __init__(self, raiz: tk.Tk) -> None:
        self.raiz = raiz
        self.cola: queue.Queue[Aviso] = queue.Queue()
        self.configuracion = cfg.cargar()
        self.ocupado = False
        self._parar = threading.Event()

        self.raiz.title("Rolsumen")
        self.raiz.geometry("640x520")
        self.raiz.minsize(520, 400)
        self.raiz.protocol("WM_DELETE_WINDOW", self._al_cerrar)

        self._construir()
        self._programar_bucles()
        self._arrancar()

    # ------------------------------------------------------------------ UI --

    def _construir(self) -> None:
        marco = ttk.Frame(self.raiz, padding=12)
        marco.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            marco, text="Rolsumen", font=("Segoe UI", 15, "bold")
        ).pack(anchor=tk.W)
        ttk.Label(
            marco,
            text="Crónicas automáticas de tus sesiones de rol",
            foreground=COLOR_NEUTRO,
        ).pack(anchor=tk.W, pady=(0, 10))

        # --- Estado de los servicios ---
        caja = ttk.LabelFrame(marco, text="Servicios", padding=10)
        caja.pack(fill=tk.X)

        self.indicadores: dict[str, ttk.Label] = {}
        for clave, etiqueta in (
            ("docker", "Docker"),
            ("craig", "Craig (grabación)"),
            ("ollama", "Ollama (resúmenes)"),
            ("ffmpeg", "ffmpeg (audio)"),
            ("gpu", "GPU (transcripción)"),
        ):
            fila = ttk.Frame(caja)
            fila.pack(fill=tk.X, pady=1)
            ttk.Label(fila, text=etiqueta, width=22).pack(side=tk.LEFT)
            valor = ttk.Label(fila, text="comprobando...", foreground=COLOR_NEUTRO)
            valor.pack(side=tk.LEFT)
            self.indicadores[clave] = valor

        # --- Actividad ---
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
            insertbackground="#d4d4d4",
            relief=tk.FLAT,
        )
        self.log.pack(fill=tk.BOTH, expand=True)

        # --- Barra inferior ---
        barra = ttk.Frame(marco)
        barra.pack(fill=tk.X)

        self.boton_buscar = ttk.Button(
            barra, text="Buscar grabaciones", command=self._buscar_ahora
        )
        self.boton_buscar.pack(side=tk.LEFT)

        ttk.Button(
            barra, text="Abrir crónicas", command=self._abrir_carpeta
        ).pack(side=tk.LEFT, padx=6)

        self.estado = ttk.Label(barra, text="Iniciando...", foreground=COLOR_NEUTRO)
        self.estado.pack(side=tk.RIGHT)

        self.progreso = ttk.Progressbar(marco, mode="indeterminate")

    # -------------------------------------------------------------- bucles --

    def _programar_bucles(self) -> None:
        self.raiz.after(INTERVALO_COLA_MS, self._vaciar_cola)
        self.raiz.after(INTERVALO_ESTADO_MS, self._refrescar_estado)
        self.raiz.after(INTERVALO_BUSQUEDA_MS, self._busqueda_periodica)

    def _vaciar_cola(self) -> None:
        """Aplica en la ventana los mensajes que manda el hilo de trabajo."""
        try:
            while True:
                aviso = self.cola.get_nowait()
                self._aplicar(aviso)
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
            self._pintar_servicios(aviso.datos)
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
            self._comprobar_servicios()
            return

        if not docker_manager.docker_en_marcha():
            self._avisar(
                "Docker no responde. Abre Docker Desktop y pulsa 'Buscar grabaciones'."
            )
            self._comprobar_servicios()
            return

        if docker_manager.esta_levantado():
            self._avisar("Craig ya estaba en marcha.")
        else:
            faltan = self.configuracion.discord.faltantes()
            if faltan:
                self._avisar(
                    "Faltan credenciales de Discord en app/config.ini "
                    f"[discord]: {', '.join(faltan)}"
                )
                self._comprobar_servicios()
                return

            self._avisar("Levantando Craig (docker compose up)...")
            resultado = docker_manager.levantar(
                credenciales=self.configuracion.discord
            )
            if resultado.ok:
                self._avisar("Craig levantado.")
            else:
                self._avisar(f"No se pudo levantar Craig: {resultado.mensaje}")

        self._comprobar_servicios()
        self._procesar_pendientes(silencioso=True)

    def _comprobar_servicios(self) -> None:
        diag = docker_manager.diagnostico()
        ffmpeg = dependencias.comprobar_ffmpeg()
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
                    "ffmpeg": ffmpeg.disponible,
                    "gpu": gpu.disponible,
                    "gpu_nombre": gpu.ruta,
                },
            )
        )

    def _buscar_ahora(self, silencioso: bool = False) -> None:
        if self.ocupado:
            return
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
                self.configuracion,
                avisar=self._avisar,
                detener=self._parar.is_set,
            )
            correctos = sum(1 for r in resultados if r.ok)
            if resultados:
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
        carpeta = cfg.DIR_RESUMENES
        carpeta.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", str(carpeta)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(carpeta)])
            else:
                subprocess.Popen(["xdg-open", str(carpeta)])
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

    def _pintar_servicios(self, datos: dict) -> None:
        if not datos.get("docker_instalado"):
            self._indicador("docker", "no instalado", COLOR_MAL)
        elif datos.get("docker"):
            self._indicador("docker", "en marcha", COLOR_OK)
        else:
            self._indicador("docker", "parado (abre Docker Desktop)", COLOR_MAL)

        if not datos.get("craig_instalado"):
            self._indicador("craig", "sin instalar", COLOR_MAL)
        elif not datos.get("craig_configurado"):
            self._indicador("craig", "falta install.config", COLOR_ESPERA)
        elif datos.get("craig"):
            self._indicador("craig", "grabando disponible", COLOR_OK)
        else:
            self._indicador("craig", "parado", COLOR_ESPERA)

        if datos.get("ollama"):
            self._indicador("ollama", "disponible", COLOR_OK)
        else:
            self._indicador("ollama", "no responde", COLOR_MAL)

        if datos.get("ffmpeg"):
            self._indicador("ffmpeg", "disponible", COLOR_OK)
        else:
            self._indicador("ffmpeg", "no encontrado", COLOR_MAL)

        if datos.get("gpu"):
            nombre = datos.get("gpu_nombre") or "activa"
            self._indicador("gpu", nombre, COLOR_OK)
        else:
            self._indicador("gpu", "sin GPU (irá lento)", COLOR_ESPERA)

    def _indicador(self, clave: str, texto: str, color: str) -> None:
        etiqueta = self.indicadores.get(clave)
        if etiqueta is not None:
            etiqueta.config(text=texto, foreground=color)


def lanzar() -> None:
    """Abre la ventana principal."""
    raiz = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    Ventana(raiz)
    raiz.mainloop()
