"""Tests de la lectura de configuración."""

from pathlib import Path

from app import config as cfg


def escribir(tmp_path: Path, contenido: str) -> Path:
    ruta = tmp_path / "config.ini"
    ruta.write_text(contenido, encoding="utf-8")
    return ruta


def test_sin_archivo_usa_valores_por_defecto(tmp_path):
    configuracion = cfg.cargar(tmp_path / "no_existe.ini")

    assert configuracion.modelos.transcripcion == "large-v3"
    assert configuracion.modelos.resumen == "qwen3:8b"
    assert configuracion.idioma == "es"
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
        "[general]\nidioma = en\n"
        "[modelos]\ntranscripcion = medium\nresumen = llama3\n"
        "precision = int8\ndispositivo = cpu\ncontexto_resumen = 8192\n",
    )

    configuracion = cfg.cargar(ruta)

    assert configuracion.modelos.transcripcion == "medium"
    assert configuracion.modelos.resumen == "llama3"
    assert configuracion.modelos.precision == "int8"
    assert configuracion.modelos.dispositivo == "cpu"
    assert configuracion.modelos.contexto_resumen == 8192
    assert configuracion.idioma == "en"


def test_dispositivo_explicito_manda_sobre_auto(tmp_path):
    ruta = escribir(tmp_path, "[modelos]\ndispositivo = cpu\n")

    assert cfg.cargar(ruta).modelos.dispositivo_efectivo() == "cpu"


def test_en_cpu_la_precision_float16_baja_a_int8(tmp_path):
    # float16 no existe en CPU; degradarlo evita un fallo al cargar el modelo.
    ruta = escribir(tmp_path, "[modelos]\ndispositivo = cpu\nprecision = float16\n")

    assert cfg.cargar(ruta).modelos.precision_efectiva() == "int8"


def test_en_gpu_se_respeta_la_precision(tmp_path):
    ruta = escribir(tmp_path, "[modelos]\ndispositivo = cuda\nprecision = float16\n")

    assert cfg.cargar(ruta).modelos.precision_efectiva() == "float16"


def test_contexto_invalido_cae_al_valor_por_defecto(tmp_path):
    ruta = escribir(tmp_path, "[modelos]\ncontexto_resumen = no_es_un_numero\n")

    assert cfg.cargar(ruta).modelos.contexto_resumen == 16384


def test_campo_vacio_no_pisa_el_valor_por_defecto(tmp_path):
    ruta = escribir(tmp_path, "[modelos]\ntranscripcion =\n")

    assert cfg.cargar(ruta).modelos.transcripcion == "large-v3"


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
    assert configuracion.modelos.transcripcion == "large-v3"
    assert configuracion.modelos.resumen == "qwen3:8b"
