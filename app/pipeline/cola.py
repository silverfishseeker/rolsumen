"""Cola de tareas: una cada vez.

El paralelismo está descartado por hardware, no por comodidad. Medido en la
GPU de 8 GB para la que se hizo esto:

    Whisper large-v3 (float16)   4,0 GB
    Ollama qwen3:8b @ 8192       5,8 GB

Dos tareas de GPU a la vez no caben (9,8 GB pedidos), y dos transcripciones se
quedan en 8,1 GB, por encima de lo disponible. Así que las tareas se ejecutan
en serie, en un único hilo, y lo que no cabe espera turno.

Cancelar afecta solo a la tarea en curso: la cola sigue con la siguiente.
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from typing import Callable

TRANSCRIBIR = "transcribir"
RESUMIR = "resumir"


@dataclass(frozen=True)
class Tarea:
    accion: str
    clave: str
    titulo: str
    # En modo automático, al terminar de transcribir se encola el resumen.
    encadenar: bool = False


@dataclass
class Estado:
    """Lo que se pinta en la barra inferior."""

    actual: Tarea | None = None
    en_cola: int = 0
    detalle: str = ""


Ejecutar = Callable[[Tarea, Callable[[], bool]], None]


@dataclass
class Cola:
    """Un hilo de trabajo consumiendo tareas de una en una.

    `ejecutar` recibe la tarea y una función que dice si hay que abandonar;
    es responsabilidad suya consultarla de vez en cuando.
    """

    ejecutar: Ejecutar
    al_cambiar: Callable[[Estado], None] | None = None
    al_fallar: Callable[[Tarea, Exception], None] | None = None

    _pendientes: queue.Queue = field(default_factory=queue.Queue, init=False)
    _cancelar: threading.Event = field(default_factory=threading.Event, init=False)
    _parar: threading.Event = field(default_factory=threading.Event, init=False)
    _actual: Tarea | None = field(default=None, init=False)
    _detalle: str = field(default="", init=False)
    _hilo: threading.Thread | None = field(default=None, init=False)

    def arrancar(self) -> None:
        if self._hilo is not None:
            return
        self._hilo = threading.Thread(target=self._bucle, daemon=True)
        self._hilo.start()

    def encolar(self, tarea: Tarea) -> None:
        self._pendientes.put(tarea)
        self._anunciar()

    def cancelar_actual(self) -> None:
        """Aborta la tarea en curso. Las que esperan no se tocan."""
        if self._actual is not None:
            self._cancelar.set()

    def vaciar(self) -> int:
        """Descarta lo que espera turno, sin tocar la tarea en curso."""
        descartadas = 0
        while True:
            try:
                self._pendientes.get_nowait()
                self._pendientes.task_done()
                descartadas += 1
            except queue.Empty:
                break
        self._anunciar()
        return descartadas

    def parar(self) -> None:
        self._parar.set()
        self._cancelar.set()

    def detallar(self, texto: str) -> None:
        """Texto fino de progreso ('pista 2 de 3'), para la barra inferior."""
        self._detalle = texto
        self._anunciar()

    def estado(self) -> Estado:
        return Estado(
            actual=self._actual,
            en_cola=self._pendientes.qsize(),
            detalle=self._detalle,
        )

    @property
    def ocupada(self) -> bool:
        return self._actual is not None

    def contiene(self, accion: str, clave: str) -> bool:
        """Evita encolar dos veces lo mismo desde la interfaz."""
        if self._actual and self._actual.accion == accion and self._actual.clave == clave:
            return True
        # El deque interno se lee bajo el cerrojo de la propia Queue: sin él,
        # una inserción simultánea puede dejar la copia a medias.
        with self._pendientes.mutex:
            pendientes = list(self._pendientes.queue)
        return any(
            t.accion == accion and t.clave == clave for t in pendientes
        )

    # ------------------------------------------------------------- interno --

    def _bucle(self) -> None:
        while not self._parar.is_set():
            try:
                tarea = self._pendientes.get(timeout=0.2)
            except queue.Empty:
                continue

            self._cancelar.clear()
            self._actual = tarea
            self._detalle = ""
            self._anunciar()
            try:
                self.ejecutar(tarea, self._cancelar.is_set)
            except Exception as exc:  # noqa: BLE001
                # Un fallo no previsto no puede llevarse por delante el hilo:
                # la cola quedaría muerta en silencio el resto de la sesión.
                if self.al_fallar:
                    self.al_fallar(tarea, exc)
            finally:
                self._actual = None
                self._detalle = ""
                self._pendientes.task_done()
                self._anunciar()

    def _anunciar(self) -> None:
        if self.al_cambiar:
            self.al_cambiar(self.estado())
