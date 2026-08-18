"""Tests del resumidor que no requieren que Ollama esté en marcha."""

from app.pipeline.resumidor import (
    _limpiar,
    _prompt_bloque,
    _resumir_contexto,
    componer_documento,
)
from app.pipeline.tipos import Bloque, Segmento


def bloque(indice=1, total=1, texto="Abro la puerta"):
    return Bloque(
        indice=indice,
        total=total,
        segmentos=[Segmento(inicio=0.0, fin=5.0, texto=texto, hablante="Kaelen")],
    )


def test_limpia_bloques_de_razonamiento():
    crudo = "<think>Déjame pensar en esto.</think>\n## Escena\n- Pasó algo."

    assert _limpiar(crudo) == "## Escena\n- Pasó algo."


def test_limpia_razonamiento_multilinea():
    crudo = "<think>\nlínea 1\nlínea 2\n</think>Resultado"

    assert _limpiar(crudo) == "Resultado"


def test_texto_sin_razonamiento_no_se_altera():
    assert _limpiar("## Escena\n- Hecho") == "## Escena\n- Hecho"


def test_el_prompt_del_primer_bloque_no_lleva_contexto():
    prompt = _prompt_bloque(bloque(), contexto_previo=None)

    assert "LO OCURRIDO HASTA AHORA" not in prompt
    assert "Abro la puerta" in prompt


def test_el_prompt_encadena_el_contexto_anterior():
    prompt = _prompt_bloque(bloque(indice=2, total=3), contexto_previo="Mataron al orco")

    assert "Mataron al orco" in prompt
    assert "no repitas" in prompt.lower()


def test_el_prompt_indica_que_ignore_lo_de_fuera_de_personaje():
    prompt = _prompt_bloque(bloque(), contexto_previo=None).lower()

    assert "ignora" in prompt
    assert "tiradas de dados" in prompt
    assert "bromas" in prompt


def test_el_prompt_pide_traducir_la_mecanica_a_ficcion():
    # Sin esto el modelo cuela cosas como "sacó un 20 en percepción".
    prompt = _prompt_bloque(bloque(), contexto_previo=None).lower()

    assert "percepción" in prompt
    assert "nunca la tirada" in prompt


def test_el_prompt_pide_hablar_de_personajes_no_de_jugadores():
    prompt = _prompt_bloque(bloque(), contexto_previo=None).lower()

    assert "personajes" in prompt
    assert "no de los jugadores" in prompt or "nunca de los jugadores" in prompt


def test_el_prompt_prohibe_inventar():
    prompt = _prompt_bloque(bloque(), contexto_previo=None)

    assert "no inventes" in prompt.lower()


def test_el_contexto_largo_se_recorta_por_el_final():
    tramo = "x" * 5000

    contexto = _resumir_contexto(tramo, limite=100)

    assert len(contexto) <= 103  # 100 + los puntos suspensivos
    assert contexto.startswith("...")


def test_el_contexto_corto_no_se_toca():
    assert _resumir_contexto("corto", limite=100) == "corto"


def test_documento_final_lleva_titulo_y_cronologia():
    doc = componer_documento("Sesión 1", "## Sinopsis\nPasaron cosas.", ["## Escena\n- Hecho"])

    assert doc.startswith("# Sesión 1")
    assert "## Cronología" in doc
    assert "## Sinopsis" in doc
    assert "- Hecho" in doc


def test_documento_final_incluye_metadatos():
    doc = componer_documento(
        "Sesión 1", "", ["tramo"], metadatos={"Fecha": "2026-08-18", "Duración": "3h"}
    )

    assert "**Fecha:** 2026-08-18" in doc
    assert "**Duración:** 3h" in doc


def test_documento_concatena_todos_los_tramos():
    doc = componer_documento("S", "", ["primero", "segundo", "tercero"])

    assert "primero" in doc and "segundo" in doc and "tercero" in doc
