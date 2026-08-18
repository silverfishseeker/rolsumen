"""Tests de la plantilla de config.ini.

La lista de modos del archivo se genera a partir de los modos que existen de
verdad, para que no pueda quedarse desfasada al añadir o quitar uno.
"""

from app import config as cfg
from app.config import _comentario_modos, plantilla_config


def test_la_plantilla_lista_todos_los_modos():
    plantilla = plantilla_config()

    for modo in cfg.MODOS:
        assert modo in plantilla, modo


def test_cada_modo_lleva_su_descripcion():
    comentario = _comentario_modos()

    for modo, descripcion in cfg.DESCRIPCION_MODOS.items():
        assert modo in comentario
        # La primera palabra de la descripción basta para confirmar que está.
        assert descripcion.split()[0] in comentario


def test_la_lista_se_genera_de_los_modos_reales(monkeypatch):
    # Añadir un modo debe reflejarse solo en el comentario, sin tocar textos.
    monkeypatch.setattr(
        cfg, "DESCRIPCION_MODOS", {"inventado": "Un modo de prueba cualquiera."}
    )

    comentario = _comentario_modos()

    assert "inventado" in comentario
    assert "rol" not in comentario


def test_todo_el_bloque_va_comentado():
    # Una línea sin '#' rompería el archivo al leerlo.
    for linea in _comentario_modos().splitlines():
        assert linea.startswith("#"), linea


def test_las_lineas_de_continuacion_quedan_alineadas():
    lineas = _comentario_modos().splitlines()
    columnas = []

    for linea in lineas:
        if linea.startswith("#   ") and not linea.startswith("#    "):
            # Línea de nombre: la descripción empieza tras el nombre acolchado.
            columnas.append(len(linea) - len(linea[4:].split(maxsplit=1)[1]))
        else:
            columnas.append(len(linea) - len(linea.lstrip("# ")))

    assert len(set(columnas)) == 1, f"columnas dispares: {set(columnas)}"


def test_las_lineas_no_se_desbordan():
    for linea in _comentario_modos().splitlines():
        assert len(linea) <= 80, linea


def test_la_plantilla_es_un_ini_valido(tmp_path):
    ruta = tmp_path / "config.ini"
    ruta.write_text(plantilla_config(), encoding="utf-8")

    configuracion = cfg.cargar(ruta)

    assert configuracion.modo == cfg.MODO_POR_DEFECTO
    assert configuracion.modelos.transcripcion
    assert configuracion.jugadores == {}


def test_el_modo_por_defecto_de_la_plantilla_es_valido():
    assert cfg.MODO_POR_DEFECTO in cfg.MODOS


def test_el_config_real_documenta_los_modos():
    # El archivo del usuario debe llevar la lista, no solo la plantilla.
    if not cfg.RUTA_CONFIG.exists():
        return

    contenido = cfg.RUTA_CONFIG.read_text(encoding="utf-8")

    assert "Modos permitidos:" in contenido
    for modo in cfg.MODOS:
        assert modo in contenido, modo
