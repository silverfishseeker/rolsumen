"""Ninguna llamada a un programa externo debe abrir una ventana de consola.

El acceso directo lanza la aplicación con `pythonw.exe`, que no tiene consola.
Windows entonces crea una **nueva y visible** por cada subproceso; como el
estado de los servicios se refresca cada diez segundos y cada refresco son
varios comandos de Docker, la pantalla se llena de ventanas negras
parpadeando.

Basta con olvidar `CREATE_NO_WINDOW` en una sola llamada frecuente para que el
parpadeo vuelva, así que aquí se comprueban todas de golpe.
"""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from app.procesos import SIN_CONSOLA

RAIZ_APP = Path(__file__).resolve().parent.parent / "app"

# `procesos.py` es quien define la bandera; ahí las llamadas son las envoltorias.
EXENTOS = {"procesos.py"}


def _llamadas_a_subprocess(arbol: ast.AST):
    """Nodos que invocan subprocess.run o subprocess.Popen."""
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Call):
            continue
        funcion = nodo.func
        if (
            isinstance(funcion, ast.Attribute)
            and funcion.attr in {"run", "Popen"}
            and isinstance(funcion.value, ast.Name)
            and funcion.value.id == "subprocess"
        ):
            yield nodo


def _pasa_sin_consola(llamada: ast.Call) -> bool:
    return any(
        clave.arg is None
        and isinstance(clave.value, ast.Name)
        and clave.value.id == "SIN_CONSOLA"
        for clave in llamada.keywords
    )


def archivos_con_subprocess():
    for ruta in sorted(RAIZ_APP.rglob("*.py")):
        if ruta.name in EXENTOS or "craig" in ruta.parts:
            continue
        arbol = ast.parse(ruta.read_text(encoding="utf-8"))
        for llamada in _llamadas_a_subprocess(arbol):
            yield ruta, llamada


def test_hay_llamadas_que_comprobar():
    # Si esto falla, el test de abajo no estaría comprobando nada.
    assert list(archivos_con_subprocess()), "no se encontró ninguna llamada"


def test_toda_llamada_a_un_programa_externo_va_sin_consola():
    olvidadas = [
        f"{ruta.relative_to(RAIZ_APP.parent)}:{llamada.lineno}"
        for ruta, llamada in archivos_con_subprocess()
        if not _pasa_sin_consola(llamada)
    ]

    assert not olvidadas, (
        "estas llamadas abrirán una consola bajo pythonw.exe; "
        f"añádeles **SIN_CONSOLA: {', '.join(olvidadas)}"
    )


@pytest.mark.skipif(sys.platform != "win32", reason="la bandera es de Windows")
def test_la_bandera_es_la_de_windows():
    assert SIN_CONSOLA == {"creationflags": subprocess.CREATE_NO_WINDOW}


def test_fuera_de_windows_no_se_pasa_nada(monkeypatch):
    # El diccionario se calcula al importar; se comprueba la regla, no el valor.
    import importlib

    from app import procesos

    monkeypatch.setattr(sys, "platform", "linux")
    recargado = importlib.reload(procesos)
    try:
        assert recargado.SIN_CONSOLA == {}
    finally:
        monkeypatch.undo()
        importlib.reload(procesos)
