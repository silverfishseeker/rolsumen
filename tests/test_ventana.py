"""Comprobación de que la ventana se construye entera.

El fallo que motiva estos tests: al quitar una variable auxiliar de la pestaña
de configuración quedó un uso suelto (`c.jugadores`). Ni los tests ni un
`import app.gui` lo detectaban —la línea solo se ejecuta al construir la
ventana— así que la aplicación no arrancaba y el único aviso era un traceback
que `pythonw` se tragaba, sin consola donde mostrarlo.
"""

import sys
import tkinter as tk

import pytest

from app import gui
from app.pipeline.cola import RESUMIR, TRANSCRIBIR


@pytest.fixture(scope="module")
def raiz():
    """Una sola raíz de Tk para todo el módulo.

    Crear y destruir una por test hacía fallar el intérprete de Microsoft Store
    una vez de cada tres con «Can't find a usable init.tcl». No es cosa de la
    aplicación, pero un test que falla a ratos acaba ignorándose.
    """
    try:
        ventana_raiz = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"no hay entorno gráfico: {exc}")

    ventana_raiz.withdraw()
    yield ventana_raiz
    ventana_raiz.destroy()


@pytest.fixture
def ventana(raiz, monkeypatch):
    """Una ventana real, sin el arranque que habla con Docker ni bucle de eventos."""
    # `_arrancar` levanta Craig y comprueba dependencias: aquí sobra.
    monkeypatch.setattr(gui.Ventana, "_arrancar", lambda self: None)

    v = gui.Ventana(raiz)
    yield v

    v.cola.parar()
    for hijo in raiz.winfo_children():
        hijo.destroy()


def test_la_ventana_se_construye_entera(ventana):
    # Construirla ya ejerce las tres pestañas; si algo falla, revienta arriba.
    assert ventana.raiz.title() == "Rolsumen"


def test_estan_las_tres_pestanas(ventana):
    nombres = [ventana.pestanas.tab(i, "text").strip() for i in ventana.pestanas.tabs()]

    assert nombres == ["Trabajo", "Estado", "Configuración"]


def test_estan_las_tres_listas(ventana):
    assert set(ventana.listas) == {"grabaciones", "transcripciones", "resumenes"}


def test_las_casillas_de_configuracion_se_rellenan(ventana):
    valores = ventana._valores_actuales()

    assert valores, "la pestaña de configuración no tiene campos"
    for clave, esperado in valores.items():
        assert ventana.campos[clave].get() == esperado


def test_la_lista_de_jugadores_se_rellena_sin_reventar(ventana):
    # Es la línea exacta que estaba rota: usaba una variable que ya no existía.
    texto = ventana.jugadores.get("1.0", tk.END)

    for usuario, personaje in ventana.configuracion.jugadores.items():
        assert f"{usuario} = {personaje}" in texto


def test_el_boton_grande_empieza_desactivado(ventana):
    assert str(ventana.boton_paso["state"]) == "disabled"
    assert "Selecciona" in ventana.boton_paso["text"]


def test_el_boton_cambia_segun_la_lista_elegida(ventana):
    ventana.filas["grabaciones"] = [
        gui.orquestador.Disponible(clave="abc", titulo="abc", detalle="pendiente")
    ]
    ventana.listas["grabaciones"].insert(tk.END, "abc")
    ventana.listas["grabaciones"].selection_set(0)

    ventana._actualizar_boton()

    assert "Transcribir" in ventana.boton_paso["text"]
    assert str(ventana.boton_paso["state"]) == "normal"


def test_la_barra_inferior_dice_el_modo_desde_el_arranque(ventana):
    assert "Sin tareas" in ventana.etiqueta_tarea["text"]
    assert ventana.configuracion.ejecucion in ventana.etiqueta_cola["text"] or (
        gui.NOMBRE_EJECUCION.get(ventana.configuracion.ejecucion, "")
        in ventana.etiqueta_cola["text"]
    )


def test_cancelar_esta_desactivado_sin_tareas(ventana):
    assert str(ventana.boton_cancelar["state"]) == "disabled"


def test_pintar_la_barra_con_una_tarea_activa(ventana):
    ventana._pintar_barra(
        {"accion": TRANSCRIBIR, "titulo": "sesion", "en_cola": 2, "detalle": "pista 1"}
    )

    assert "Transcribiendo sesion" in ventana.etiqueta_tarea["text"]
    assert "pista 1" in ventana.etiqueta_tarea["text"]
    assert "2 en cola" in ventana.etiqueta_cola["text"]
    assert str(ventana.boton_cancelar["state"]) == "normal"


def test_pintar_la_barra_resumiendo(ventana):
    ventana._pintar_barra({"accion": RESUMIR, "titulo": "sesion", "en_cola": 0})

    assert "Resumiendo sesion" in ventana.etiqueta_tarea["text"]
    assert "en cola" not in ventana.etiqueta_cola["text"]


def test_las_listas_se_pintan_con_lo_que_haya(ventana):
    ventana._pintar_listas(
        {
            "grabaciones": [
                gui.orquestador.Disponible(clave="g1", titulo="g1", detalle="pendiente")
            ],
            "transcripciones": [],
            "resumenes": [],
        }
    )

    assert ventana.listas["grabaciones"].size() == 1
    assert "g1" in ventana.listas["grabaciones"].get(0)
    assert ventana.listas["transcripciones"].size() == 0


def test_elegir_en_una_lista_deselecciona_las_otras(ventana):
    for clave in ("grabaciones", "transcripciones"):
        ventana.filas[clave] = [
            gui.orquestador.Disponible(clave=f"{clave}-1", titulo="x", detalle="")
        ]
        ventana.listas[clave].insert(tk.END, "x")

    ventana.listas["grabaciones"].selection_set(0)
    ventana.listas["transcripciones"].selection_set(0)
    ventana._seleccion("transcripciones")

    assert not ventana.listas["grabaciones"].curselection()
    assert ventana.listas["transcripciones"].curselection()


# --- Icono de la barra de tareas ---------------------------------------------


@pytest.mark.skipif(sys.platform != "win32", reason="WM_SETICON es de Windows")
def test_la_ventana_lleva_sus_dos_iconos(ventana):
    """El grande es el que usa la barra de tareas.

    `iconbitmap` solo arregla la barra de título: sin rellenar los iconos de la
    ventana por WM_SETICON, la barra de tareas sigue mostrando el de Python.
    """
    import ctypes

    ventana.raiz.update_idletasks()
    usuario = ctypes.windll.user32
    handle = usuario.GetParent(ventana.raiz.winfo_id()) or ventana.raiz.winfo_id()

    WM_GETICON, ICON_SMALL, ICON_BIG = 0x007F, 0, 1
    grande = usuario.SendMessageW(handle, WM_GETICON, ICON_BIG, 0)
    pequeno = usuario.SendMessageW(handle, WM_GETICON, ICON_SMALL, 0)

    assert grande, "sin icono grande la barra de tareas usa el de Python"
    assert pequeno, "falta el icono pequeño de la barra de título"


# --- Escalado en pantallas con DPI alto --------------------------------------


def test_a_escala_normal_no_se_cambia_el_tamano():
    assert gui.tamano_escalado(96) == (gui.ANCHO, gui.ALTO,
                                       gui.ANCHO_MINIMO, gui.ALTO_MINIMO)


def test_al_150_por_ciento_la_ventana_crece_igual():
    """Escalar solo las fuentes deja el texto grande en una ventana pequeña.

    Es lo que pasaba: el contenido se salía y la barra inferior quedaba cortada.
    """
    ancho, alto, _, _ = gui.tamano_escalado(144)

    assert (ancho, alto) == (round(gui.ANCHO * 1.5), round(gui.ALTO * 1.5))


def test_los_minimos_escalan_tambien():
    _, _, ancho_min, alto_min = gui.tamano_escalado(192)

    assert (ancho_min, alto_min) == (gui.ANCHO_MINIMO * 2, gui.ALTO_MINIMO * 2)


def test_el_escalado_de_fuentes_acompana(raiz, monkeypatch):
    monkeypatch.setattr(gui, "puntos_por_pulgada", lambda _r: 144)

    gui._ajustar_escalado(raiz)

    assert float(raiz.tk.call("tk", "scaling")) == pytest.approx(144 / 72.0, rel=0.01)
