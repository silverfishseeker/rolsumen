"""Tests de la cola de tareas.

Se ejecutan en serie por una razón medida, no por gusto: en la GPU de 8 GB de
referencia, Whisper large-v3 ocupa 4,0 GB y qwen3:8b a 8192 de contexto otros
5,8 GB. Dos tareas de GPU a la vez no caben.
"""

import threading
import time

from app.pipeline.cola import RESUMIR, TRANSCRIBIR, Cola, Tarea


def esperar(condicion, limite=3.0):
    """Espera activa breve: la cola trabaja en su propio hilo."""
    fin = time.time() + limite
    while time.time() < fin:
        if condicion():
            return True
        time.sleep(0.01)
    return False


def tarea(clave="a", accion=TRANSCRIBIR, encadenar=False):
    return Tarea(accion=accion, clave=clave, titulo=clave, encadenar=encadenar)


def test_las_tareas_se_ejecutan_de_una_en_una():
    a_la_vez = []
    pico = []

    def ejecutar(_t, _c):
        a_la_vez.append(1)
        pico.append(len(a_la_vez))
        time.sleep(0.05)
        a_la_vez.pop()

    cola = Cola(ejecutar=ejecutar)
    cola.arrancar()
    for i in range(4):
        cola.encolar(tarea(str(i)))

    assert esperar(lambda: len(pico) == 4)
    cola.parar()
    assert max(pico) == 1, "no puede haber dos tareas solapadas"


def test_se_respeta_el_orden_de_llegada():
    hechas = []
    cola = Cola(ejecutar=lambda t, _c: hechas.append(t.clave))
    cola.arrancar()
    for clave in "abc":
        cola.encolar(tarea(clave))

    assert esperar(lambda: len(hechas) == 3)
    cola.parar()
    assert hechas == ["a", "b", "c"]


def test_cancelar_solo_afecta_a_la_tarea_en_curso():
    empezadas, terminadas = [], []
    arrancada = threading.Event()

    def ejecutar(t, cancelado):
        empezadas.append(t.clave)
        arrancada.set()
        for _ in range(200):
            if cancelado():
                return
            time.sleep(0.005)
        terminadas.append(t.clave)

    cola = Cola(ejecutar=ejecutar)
    cola.arrancar()
    cola.encolar(tarea("larga"))
    assert arrancada.wait(2), "la primera tarea no llegó a arrancar"
    cola.encolar(tarea("siguiente"))

    cola.cancelar_actual()

    assert esperar(lambda: "siguiente" in terminadas, limite=4)
    cola.parar()
    assert "larga" not in terminadas, "la cancelada no debe terminar"
    assert empezadas == ["larga", "siguiente"], "la cola debe seguir con la siguiente"


def test_la_cancelacion_no_se_arrastra_a_la_tarea_siguiente():
    # El evento de cancelar se reutiliza; si no se limpiara, la tarea que
    # entra despues nacería ya cancelada.
    vistos = []

    def ejecutar(t, cancelado):
        vistos.append((t.clave, cancelado()))
        time.sleep(0.02)

    cola = Cola(ejecutar=ejecutar)
    cola.arrancar()
    cola.encolar(tarea("primera"))
    cola.cancelar_actual()
    assert esperar(lambda: len(vistos) >= 1)
    cola.encolar(tarea("segunda"))

    assert esperar(lambda: len(vistos) == 2)
    cola.parar()
    assert vistos[1] == ("segunda", False)


def test_el_estado_cuenta_lo_que_espera():
    suelta = threading.Event()
    cola = Cola(ejecutar=lambda _t, _c: suelta.wait(2))
    cola.arrancar()
    for clave in "abcd":
        cola.encolar(tarea(clave))

    assert esperar(lambda: cola.estado().actual is not None)
    estado = cola.estado()
    assert estado.actual.clave == "a"
    assert estado.en_cola == 3

    suelta.set()
    cola.parar()


def test_contiene_evita_encolar_dos_veces_lo_mismo():
    suelta = threading.Event()
    cola = Cola(ejecutar=lambda _t, _c: suelta.wait(2))
    cola.arrancar()
    cola.encolar(tarea("x"))
    assert esperar(lambda: cola.ocupada)
    cola.encolar(tarea("y"))

    assert cola.contiene(TRANSCRIBIR, "x"), "la que se está ejecutando cuenta"
    assert cola.contiene(TRANSCRIBIR, "y"), "la que espera también"
    assert not cola.contiene(RESUMIR, "x"), "la acción forma parte de la identidad"
    assert not cola.contiene(TRANSCRIBIR, "z")

    suelta.set()
    cola.parar()


def test_vaciar_descarta_lo_que_espera_pero_no_lo_actual():
    suelta = threading.Event()
    hechas = []

    def ejecutar(t, _c):
        hechas.append(t.clave)
        suelta.wait(2)

    cola = Cola(ejecutar=ejecutar)
    cola.arrancar()
    for clave in "abc":
        cola.encolar(tarea(clave))
    assert esperar(lambda: cola.ocupada)

    assert cola.vaciar() == 2
    suelta.set()
    time.sleep(0.1)
    cola.parar()
    assert hechas == ["a"]


def test_avisa_de_cada_cambio_de_estado():
    estados = []
    suelta = threading.Event()
    cola = Cola(
        ejecutar=lambda _t, _c: suelta.wait(1),
        al_cambiar=lambda e: estados.append(e.actual.clave if e.actual else None),
    )
    cola.arrancar()
    cola.encolar(tarea("unica"))

    assert esperar(lambda: "unica" in estados)
    suelta.set()
    assert esperar(lambda: estados[-1] is None), "al acabar debe quedar sin tarea"
    cola.parar()


def test_un_fallo_de_la_tarea_no_mata_la_cola():
    hechas = []

    def ejecutar(t, _c):
        if t.clave == "rota":
            raise RuntimeError("algo revento")
        hechas.append(t.clave)

    cola = Cola(ejecutar=ejecutar)
    cola.arrancar()
    cola.encolar(tarea("rota"))
    cola.encolar(tarea("buena"))

    assert esperar(lambda: hechas == ["buena"]), "la cola debe sobrevivir al fallo"
    cola.parar()
