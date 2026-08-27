"""Tests del script de diagnóstico.

No comprueba el estado real del sistema (que varía), sino que el script se
ejecuta entero sin reventar aunque falte todo, que es justo cuando hay que
poder usarlo.
"""

from app import diagnostico


def test_linea_devuelve_el_estado():
    assert diagnostico._linea(True, "algo") is True
    assert diagnostico._linea(False, "algo") is False


def test_marca_visualmente_distinta_segun_el_estado(capsys):
    diagnostico._linea(True, "bien")
    diagnostico._linea(False, "mal")

    salida = capsys.readouterr().out
    assert diagnostico.OK in salida
    assert diagnostico.MAL in salida


def test_muestra_el_detalle_cuando_lo_hay(capsys):
    diagnostico._linea(False, "docker", "no responde")

    assert "no responde" in capsys.readouterr().out


def test_se_ejecuta_entero_sin_docker(monkeypatch, capsys):
    # Con Docker parado el diagnóstico tiene que seguir funcionando: es
    # precisamente el momento en que hace falta.
    monkeypatch.setattr(
        diagnostico.docker_manager,
        "diagnostico",
        lambda *a, **k: {
            "docker_instalado": False,
            "docker_en_marcha": False,
            "craig_instalado": False,
            "craig_configurado": False,
            "craig_levantado": False,
        },
    )
    monkeypatch.setattr(diagnostico.docker_manager, "servicios_con_estado", lambda *a, **k: [])
    monkeypatch.setattr(
        diagnostico.resumidor, "ollama_disponible", lambda *a, **k: False
    )

    assert diagnostico.main() == 0

    salida = capsys.readouterr().out
    assert "Dependencias" in salida
    assert "Docker y Craig" in salida
    assert "Ollama" in salida


def test_avisa_si_falta_el_modelo_de_ollama(monkeypatch, capsys):
    monkeypatch.setattr(
        diagnostico.docker_manager,
        "diagnostico",
        lambda *a, **k: dict.fromkeys(
            [
                "docker_instalado",
                "docker_en_marcha",
                "craig_instalado",
                "craig_configurado",
                "craig_levantado",
            ],
            False,
        ),
    )
    monkeypatch.setattr(diagnostico.docker_manager, "servicios_con_estado", lambda *a, **k: [])
    monkeypatch.setattr(
        diagnostico.resumidor, "ollama_disponible", lambda *a, **k: True
    )
    monkeypatch.setattr(
        diagnostico.resumidor, "modelos_disponibles", lambda *a, **k: ["otro:7b"]
    )

    diagnostico.main()

    salida = capsys.readouterr().out
    # El modelo configurado no está en la lista: debe salir marcado como fallo.
    assert diagnostico.MAL in salida

