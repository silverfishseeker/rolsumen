"""Tests del arranque en modo automático.

El fallo que los motiva: al abrir la aplicación se ponía a procesar el
historial entero. La causa de fondo era confundir «Craig no contesta» con «no
hay ninguna grabación»: con Craig todavía instalándose, la referencia de lo ya
conocido quedaba vacía y al primer ciclo todo parecía recién grabado.
"""

from datetime import datetime

import pytest

from app.craig_client import ErrorCraig, Grabacion
from app.pipeline import orquestador


def grabacion(id_grabacion: str) -> Grabacion:
    momento = datetime(2026, 8, 18, 10, 0)
    return Grabacion(id=id_grabacion, creada=momento, terminada=momento)


@pytest.fixture
def craig(monkeypatch):
    """Sustituye la consulta a Craig por algo controlable desde el test."""

    class Falso:
        respuesta: list = []
        error: bool = False

        def terminadas(self):
            if self.error:
                raise ErrorCraig("Craig no responde")
            return list(self.respuesta)

    falso = Falso()
    monkeypatch.setattr(
        orquestador.craig_client, "grabaciones_terminadas", falso.terminadas
    )
    return falso


def test_si_craig_no_contesta_no_se_sabe_nada(craig):
    craig.error = True

    assert orquestador.ids_terminadas() is None


def test_sin_grabaciones_la_respuesta_es_un_conjunto_vacio(craig):
    craig.respuesta = []

    # Vacío y None son cosas distintas: uno es "no hay", el otro "no se sabe".
    assert orquestador.ids_terminadas() == set()


def test_se_devuelven_los_identificadores_conocidos(craig):
    craig.respuesta = [grabacion("aaa"), grabacion("bbb")]

    assert orquestador.ids_terminadas() == {"aaa", "bbb"}


def test_solo_es_nueva_la_que_no_estaba(craig):
    craig.respuesta = [grabacion("vieja"), grabacion("nueva")]

    nuevas = orquestador.grabaciones_nuevas({"vieja"})

    assert [g.id for g in nuevas] == ["nueva"]


def test_el_historial_completo_no_cuenta_como_nuevo(craig):
    craig.respuesta = [grabacion("a"), grabacion("b"), grabacion("c")]

    assert orquestador.grabaciones_nuevas({"a", "b", "c"}) == []


def test_si_craig_cae_no_se_inventan_grabaciones_nuevas(craig):
    craig.error = True

    assert orquestador.grabaciones_nuevas(set()) == []


def test_la_referencia_no_se_fija_mientras_craig_no_responda(craig):
    """Reproduce el arranque real: Craig tarda en estar listo.

    Mientras no conteste, la referencia sigue sin fijarse. Cuando por fin
    responde, lo que ya existía se anota y NO se considera nuevo.
    """
    craig.error = True
    conocidas = orquestador.ids_terminadas()
    assert conocidas is None, "sin respuesta no se puede fijar la referencia"

    # Craig termina de instalarse y aparece el historial de siempre.
    craig.error = False
    craig.respuesta = [grabacion("de-hace-semanas")]
    conocidas = orquestador.ids_terminadas()

    assert conocidas == {"de-hace-semanas"}
    assert orquestador.grabaciones_nuevas(conocidas) == [], (
        "el historial anterior no debe dispararse solo"
    )

    # Y ahora sí: una grabación que llega después.
    craig.respuesta.append(grabacion("recien-grabada"))
    assert [g.id for g in orquestador.grabaciones_nuevas(conocidas)] == [
        "recien-grabada"
    ]
