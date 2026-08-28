"""Tests de la instancia única.

Dos ventanas sobre los mismos datos se pisarían: las dos levantarían Craig, las
dos vigilarían grabaciones nuevas y podrían transcribir la misma sesión a la
vez, que es justo lo que la cola evita dentro de una sola.
"""

import sys

import pytest

from app import instancia


def test_los_nombres_globales_identifican_la_aplicacion():
    # Si dos aplicaciones compartieran nombre se bloquearían entre ellas.
    assert "Rolsumen" in instancia.NOMBRE_MUTEX
    assert "Rolsumen" in instancia.NOMBRE_EVENTO
    assert instancia.NOMBRE_MUTEX != instancia.NOMBRE_EVENTO


NOMBRE_DE_PRUEBA = "Rolsumen.Test.InstanciaUnica"
EVENTO_DE_PRUEBA = "Rolsumen.Test.TraerAlFrente"


@pytest.mark.skipif(sys.platform != "win32", reason="el mutex es de Windows")
def test_la_primera_reserva_tiene_exito():
    # Con un nombre propio: si no, fallaría cuando la aplicación esté abierta.
    assert instancia.reservar(NOMBRE_DE_PRUEBA, EVENTO_DE_PRUEBA) is True


@pytest.mark.skipif(sys.platform != "win32", reason="el mutex es de Windows")
def test_una_segunda_reserva_desde_otro_proceso_falla():
    """Es lo que distingue a la instancia nueva de la que ya estaba."""
    import subprocess
    import textwrap

    from app.procesos import SIN_CONSOLA

    instancia.reservar(NOMBRE_DE_PRUEBA, EVENTO_DE_PRUEBA)  # nos quedamos el puesto

    guion = textwrap.dedent(
        """
        import sys
        sys.path.insert(0, sys.argv[1])
        from app import instancia
        print("libre" if instancia.reservar(sys.argv[2], sys.argv[3]) else "ocupado")
        """
    )
    from app import config as cfg

    resultado = subprocess.run(
        [sys.executable, "-c", guion, str(cfg.RAIZ), NOMBRE_DE_PRUEBA,
         EVENTO_DE_PRUEBA],
        capture_output=True,
        text=True,
        timeout=120,
        **SIN_CONSOLA,
    )

    assert resultado.stdout.strip() == "ocupado", resultado.stderr


def test_sin_evento_no_hay_peticiones(monkeypatch):
    monkeypatch.setattr(instancia, "_evento", None)

    assert instancia.hay_peticion_de_frente() is False


def test_fuera_de_windows_se_deja_abrir(monkeypatch):
    """Sin mutex con nombre no se puede comprobar; bloquear sería peor."""
    monkeypatch.setattr(instancia.sys, "platform", "linux")

    assert instancia.reservar(NOMBRE_DE_PRUEBA, EVENTO_DE_PRUEBA) is True
    assert instancia.traer_al_frente() is False


def test_no_encontrar_la_ventana_no_revienta(monkeypatch):
    monkeypatch.setattr(instancia, "_buscar_ventana", lambda _t: None)

    assert instancia.traer_al_frente("no existe") is False
