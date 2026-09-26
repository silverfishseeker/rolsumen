"""Tests de la cola de reproducción.

Sin Discord ni red: la cola es lógica pura a propósito, para poder probarla
entera. Lo que sí toca Discord vive en `app/musica/bot.py`.
"""

from app.musica.lista import Lista, Pista


def pista(titulo="algo", quien="ana", local=False, duracion=None) -> Pista:
    return Pista(titulo, f"C:/{titulo}.mp3", quien, local=local, duracion=duracion)


def test_una_lista_nueva_esta_vacia():
    lista = Lista()

    assert lista.vacia
    assert lista.actual is None
    assert len(lista) == 0


def test_la_primera_pista_suena_ya():
    """El 0 es lo que distingue «suena» de «encolada», y se le dice al usuario."""
    lista = Lista()

    puesto = lista.anadir(pista("lluvia"))

    assert puesto == 0
    assert lista.actual.titulo == "lluvia"
    assert len(lista) == 0, "la que suena no cuenta como pendiente"


def test_las_siguientes_se_encolan_con_su_numero():
    lista = Lista()
    lista.anadir(pista("primera"))

    assert lista.anadir(pista("segunda")) == 1
    assert lista.anadir(pista("tercera")) == 2
    assert len(lista) == 2


def test_se_avanza_en_orden_de_llegada():
    lista = Lista()
    for nombre in ("a", "b", "c"):
        lista.anadir(pista(nombre))

    assert lista.siguiente().titulo == "b"
    assert lista.siguiente().titulo == "c"


def test_al_acabar_la_ultima_no_queda_nada():
    lista = Lista()
    lista.anadir(pista("unica"))

    assert lista.siguiente() is None
    assert lista.vacia


def test_avanzar_en_una_lista_vacia_no_revienta():
    assert Lista().siguiente() is None


def test_vaciar_lo_deja_como_nuevo():
    lista = Lista()
    lista.anadir(pista("a"))
    lista.anadir(pista("b"))

    lista.vaciar()

    assert lista.vacia and len(lista) == 0


def test_tras_vaciar_la_siguiente_vuelve_a_sonar_ya():
    lista = Lista()
    lista.anadir(pista("a"))
    lista.anadir(pista("b"))
    lista.vaciar()

    assert lista.anadir(pista("c")) == 0


def test_las_pendientes_se_pueden_mirar_sin_tocarlas():
    lista = Lista()
    lista.anadir(pista("suena"))
    lista.anadir(pista("espera"))

    assert [p.titulo for p in lista.pendientes] == ["espera"]
    assert len(lista) == 1, "mirar no consume"


def test_el_texto_incluye_la_duracion_si_se_conoce():
    assert pista("tema", duracion=125).como_texto() == "tema (2:05)"


def test_sin_duracion_solo_sale_el_titulo():
    assert pista("tema").como_texto() == "tema"


# --- Bucle por pista ---------------------------------------------------------


def test_una_pista_nace_en_bucle():
    """Lo normal es música de ambiente: tiene que durar toda la escena."""
    assert pista().bucle


def test_alternar_el_bucle_cambia_solo_la_actual():
    lista = Lista()
    lista.anadir(pista("suena"))
    lista.anadir(pista("espera"))

    lista.alternar_bucle()

    assert not lista.actual.bucle
    assert lista.pendientes[0].bucle, "el bucle es de cada pista, no de la lista"


def test_alternar_devuelve_como_queda():
    lista = Lista()
    lista.anadir(pista())

    assert lista.alternar_bucle() is False
    assert lista.alternar_bucle() is True


def test_alternar_sin_nada_sonando_no_revienta():
    assert Lista().alternar_bucle() is False


def test_la_pista_que_llega_conserva_su_bucle():
    """Quitarle el bucle a la que suena no debe contagiar a la siguiente."""
    lista = Lista()
    lista.anadir(pista("suena"))
    lista.anadir(pista("espera"))
    lista.alternar_bucle()

    lista.siguiente()

    assert lista.actual.bucle
