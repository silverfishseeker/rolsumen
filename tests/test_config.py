"""Tests de la lectura de configuración."""

from pathlib import Path

from app import config as cfg


def escribir(tmp_path: Path, contenido: str) -> Path:
    ruta = tmp_path / "config.ini"
    ruta.write_text(contenido, encoding="utf-8")
    return ruta


def test_sin_archivo_usa_valores_por_defecto(tmp_path):
    configuracion = cfg.cargar(tmp_path / "no_existe.ini")

    assert configuracion.modelo_whisper == "large-v3"
    assert configuracion.modelo_ollama == "qwen3:8b"
    assert configuracion.idioma == "Spanish"
    assert configuracion.carpeta_resumenes_extra is None


def test_carpeta_extra_vacia_equivale_a_no_configurada(tmp_path):
    ruta = escribir(tmp_path, "[general]\ncarpeta_resumenes =\n")

    assert cfg.cargar(ruta).carpeta_resumenes_extra is None


def test_carpeta_extra_configurada_se_lee(tmp_path):
    ruta = escribir(tmp_path, "[general]\ncarpeta_resumenes = C:\\Rol\\Cronicas\n")

    configuracion = cfg.cargar(ruta)

    assert configuracion.carpeta_resumenes_extra == Path("C:\\Rol\\Cronicas")


def test_ruta_de_windows_con_porcentaje_no_rompe(tmp_path):
    # configparser interpolaría '%' si no lo desactivásemos.
    ruta = escribir(tmp_path, "[general]\ncarpeta_resumenes = C:\\100%%rol\\x\n")

    configuracion = cfg.cargar(ruta)

    assert configuracion.carpeta_resumenes_extra is not None


def test_los_resumenes_se_guardan_siempre_en_datos(tmp_path):
    destinos = cfg.cargar(tmp_path / "no_existe.ini").destinos_resumen()

    assert destinos == [cfg.DIR_RESUMENES]


def test_con_carpeta_extra_se_duplica_el_resumen(tmp_path):
    ruta = escribir(tmp_path, "[general]\ncarpeta_resumenes = C:\\Rol\n")

    destinos = cfg.cargar(ruta).destinos_resumen()

    assert len(destinos) == 2
    assert destinos[0] == cfg.DIR_RESUMENES
    assert destinos[1] == Path("C:\\Rol")


def test_mapeo_de_jugadores(tmp_path):
    ruta = escribir(
        tmp_path,
        "[jugadores]\nsilverfishlord = Kaelen\ncaliece = Marina\n",
    )

    configuracion = cfg.cargar(ruta)

    assert configuracion.nombre_personaje("silverfishlord") == "Kaelen"
    assert configuracion.nombre_personaje("caliece") == "Marina"


def test_el_mapeo_no_distingue_mayusculas(tmp_path):
    ruta = escribir(tmp_path, "[jugadores]\nSilverFishLord = Kaelen\n")

    assert cfg.cargar(ruta).nombre_personaje("silverfishlord") == "Kaelen"


def test_jugador_sin_mapeo_conserva_su_nick(tmp_path):
    ruta = escribir(tmp_path, "[jugadores]\notro = Nombre\n")

    assert cfg.cargar(ruta).nombre_personaje("desconocido") == "desconocido"


def test_jugador_con_valor_vacio_se_ignora(tmp_path):
    ruta = escribir(tmp_path, "[jugadores]\nana =\n")

    assert cfg.cargar(ruta).nombre_personaje("ana") == "ana"


def test_modelos_configurables(tmp_path):
    ruta = escribir(
        tmp_path,
        "[general]\nmodelo_whisper = medium\nmodelo_ollama = llama3\nidioma = English\n",
    )

    configuracion = cfg.cargar(ruta)

    assert configuracion.modelo_whisper == "medium"
    assert configuracion.modelo_ollama == "llama3"
    assert configuracion.idioma == "English"


def test_crear_config_si_falta(tmp_path):
    ruta = tmp_path / "config.ini"

    assert cfg.crear_config_si_falta(ruta) is True
    assert ruta.exists()
    # La segunda vez no lo toca.
    assert cfg.crear_config_si_falta(ruta) is False


def test_el_config_creado_es_valido_y_no_configura_nada(tmp_path):
    ruta = tmp_path / "config.ini"
    cfg.crear_config_si_falta(ruta)

    configuracion = cfg.cargar(ruta)

    # Recién creado debe comportarse como "sin configurar".
    assert configuracion.carpeta_resumenes_extra is None
    assert configuracion.jugadores == {}
    assert configuracion.modelo_whisper == "large-v3"
