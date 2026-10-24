"""Cuándo intentar levantar Craig, y cuándo dejar de intentarlo.

La aplicación se puede abrir antes que Docker: Docker Desktop tarda casi un
minuto en responder, y hasta ahora Craig se intentaba levantar **una sola vez**
al arrancar. Si en ese momento Docker no estaba listo, quedaba una línea en el
registro y nunca más se intentaba.

Aquí vive sólo la decisión, sin hablar con Docker ni con la ventana, para poder
probarla entera: estados, esperas y reintentos son lógica pura.

La regla, en una frase: **nunca se intenta a ciegas**. Sólo se levanta Craig
con el motor de Docker respondiendo, así que un fallo de aquí es un fallo
propio de Craig —puerto ocupado, imagen rota, el contenedor muerto por falta de
memoria— y esos casi nunca se arreglan solos. Por eso se reintenta espaciado y
se para; pero si Docker se cae y vuelve, eso sí es una situación nueva y se
empieza de cero.
"""

from __future__ import annotations

from dataclasses import dataclass

# Tras el primer fallo se espera un minuto, tras el segundo cinco, y ahí se
# para. Insistir más contra un fallo permanente es lanzar un comando de Docker
# para siempre sin que nadie lo lea.
ESPERAS_TRAS_FALLO = (60.0, 300.0)

# Qué toca hacer ahora mismo.
NADA = "nada"
LEVANTAR = "levantar"

# En qué anda el supervisor, para poder contarlo en la pestaña Estado.
OCIOSO = "ocioso"
LEVANTANDO = "levantando"
ESPERANDO = "esperando"
RENDIDO = "rendido"


@dataclass
class Situacion:
    """Lo que se ve del mundo en este instante."""

    docker_en_marcha: bool
    craig_en_marcha: bool
    craig_configurado: bool


class Supervisor:
    """Decide si toca intentar levantar Craig."""

    def __init__(self, esperas=ESPERAS_TRAS_FALLO) -> None:
        self.esperas = tuple(esperas)
        self.estado = OCIOSO
        self.motivo = ""
        self._fallos = 0
        self._proximo_intento: float | None = None
        # Se anota la **caída**, no la vuelta: arrancar con Docker ya listo no
        # es «Docker ha vuelto» y no debe borrar nada. Mirarlo al revés hacía
        # que el primer ciclo olvidara los fallos recién anotados.
        self._docker_cayo = False

    # ------------------------------------------------------------ decidir --

    def decidir(self, situacion: Situacion, ahora: float) -> str:
        """`LEVANTAR` o `NADA`. Quien llama ejecuta y luego cuenta qué pasó."""
        if not situacion.docker_en_marcha:
            # Que Docker se vaya no es un fallo de Craig: cuando vuelva habrá
            # que probar otra vez desde cero, aunque antes nos hubiéramos
            # rendido. Es la única situación realmente nueva.
            self._docker_cayo = True
            if self.estado != LEVANTANDO:
                self.estado = OCIOSO
                self.motivo = ""
            return NADA

        if self._docker_cayo:
            self._docker_cayo = False
            self._olvidar_fallos()
            if self.estado == RENDIDO:
                self.estado = OCIOSO

        if self.estado == LEVANTANDO:
            return NADA  # ya hay un intento en marcha

        if situacion.craig_en_marcha:
            self._olvidar_fallos()
            self.estado = OCIOSO
            return NADA

        if not situacion.craig_configurado:
            return NADA

        if self.estado == RENDIDO:
            return NADA

        if self._proximo_intento is not None and ahora < self._proximo_intento:
            return NADA

        return LEVANTAR

    # -------------------------------------------------------- contar qué --

    def empezo(self) -> None:
        self.estado = LEVANTANDO
        self.motivo = ""

    def termino(self, ok: bool, motivo: str, ahora: float) -> None:
        if ok:
            self._olvidar_fallos()
            self.estado = OCIOSO
            return

        self._fallos += 1
        self.motivo = motivo.strip()
        if self._fallos <= len(self.esperas):
            self._proximo_intento = ahora + self.esperas[self._fallos - 1]
            self.estado = ESPERANDO
        else:
            self._proximo_intento = None
            self.estado = RENDIDO

    # ------------------------------------------------------------ apoyos --

    @property
    def fallos(self) -> int:
        return self._fallos

    def _olvidar_fallos(self) -> None:
        self._fallos = 0
        self._proximo_intento = None
        self.motivo = ""
