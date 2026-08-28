"""Tests del guardado de config.ini desde la interfaz.

config.ini no es solo datos: sus comentarios son la documentacion de cada
opcion. `configparser` sabe leerlo pero al reescribirlo los tira todos, asi que
el guardado sustituye valores linea a linea.
"""

from app import config as cfg


def preparar(tmp_path):
    ruta = tmp_path / "config.ini"
    ruta.write_text(cfg.plantilla_config(), encoding="utf-8")
    return ruta


def comentarios(ruta):
    return [l for l in ruta.read_text(encoding="utf-8").splitlines()
            if l.strip().startswith("#")]


def test_guardar_no_pierde_ningun_comentario(tmp_path):
    ruta = preparar(tmp_path)
    antes = comentarios(ruta)

    cfg.guardar_valores({("general", "idioma"): "en"}, ruta)

    assert comentarios(ruta) == antes


def test_el_valor_guardado_se_relee(tmp_path):
    ruta = preparar(tmp_path)

    cfg.guardar_valores(
        {
            ("general", "idioma"): "fr",
            ("general", "ejecucion"): "manual",
            ("modelos", "contexto_resumen"): "4096",
            ("discord", "token_bot"): "abc123",
        },
        ruta,
    )

    leida = cfg.cargar(ruta)
    assert leida.idioma == "fr"
    assert leida.ejecucion == "manual"
    assert leida.modelos.contexto_resumen == 4096
    assert leida.discord.token_bot == "abc123"


def test_una_clave_que_no_existia_se_anade_a_su_seccion(tmp_path):
    ruta = preparar(tmp_path)
    # 'ejecucion' se lee de [general]; se comprueba con una clave inventada
    # para no depender de que la plantilla la traiga.
    cfg.guardar_valores({("general", "inventada"): "si"}, ruta)

    texto = ruta.read_text(encoding="utf-8")
    general = texto.split("[general]")[1].split("[")[0]
    assert "inventada = si" in general


def test_una_seccion_que_no_existia_se_crea(tmp_path):
    ruta = preparar(tmp_path)

    cfg.guardar_valores({("nueva", "clave"): "valor"}, ruta)

    texto = ruta.read_text(encoding="utf-8")
    assert "[nueva]" in texto
    assert texto.index("[nueva]") > texto.index("[jugadores]")


def test_guardar_no_toca_los_valores_que_no_se_pasan(tmp_path):
    ruta = preparar(tmp_path)
    original = cfg.cargar(ruta)

    cfg.guardar_valores({("general", "idioma"): "de"}, ruta)

    leida = cfg.cargar(ruta)
    assert leida.modo == original.modo
    assert leida.modelos.transcripcion == original.modelos.transcripcion
    assert leida.discord.id_aplicacion == original.discord.id_aplicacion


def test_los_jugadores_sustituyen_a_los_anteriores(tmp_path):
    ruta = preparar(tmp_path)
    cfg.guardar_jugadores({"ana": "Elara"}, ruta)
    cfg.guardar_jugadores({"luis": "Bran"}, ruta)

    assert cfg.cargar(ruta).jugadores == {"luis": "Bran"}


def test_guardar_jugadores_conserva_los_comentarios_de_su_seccion(tmp_path):
    ruta = preparar(tmp_path)

    cfg.guardar_jugadores({"ana": "Elara"}, ruta)

    seccion = ruta.read_text(encoding="utf-8").split("[jugadores]")[1]
    assert "# Asocia cada usuario de Discord" in seccion
    assert "ana = Elara" in seccion


def test_guardar_sin_cambios_deja_el_archivo_igual(tmp_path):
    ruta = preparar(tmp_path)
    antes = ruta.read_text(encoding="utf-8")

    cfg.guardar_valores({}, ruta)

    assert ruta.read_text(encoding="utf-8") == antes


def test_el_modo_de_ejecucion_desconocido_cae_al_automatico(tmp_path):
    ruta = preparar(tmp_path)
    cfg.guardar_valores({("general", "ejecucion"): "inventado"}, ruta)

    assert cfg.cargar(ruta).ejecucion == cfg.EJECUCION_POR_DEFECTO


def test_la_plantilla_documenta_los_modos_de_ejecucion():
    plantilla = cfg.plantilla_config()
    for nombre in cfg.EJECUCIONES:
        assert nombre in plantilla


# --- Lo que se guarda no siempre es lo que queda ------------------------------


def test_un_contexto_no_numerico_se_guarda_pero_no_se_usa(tmp_path):
    """La interfaz debe repintar la casilla, no dejar el valor fantasma.

    `cargar()` cae al valor por defecto sin avisar; si la casilla siguiera
    mostrando lo tecleado, el usuario creeria estar usando algo que no usa.
    """
    ruta = preparar(tmp_path)
    cfg.guardar_valores({("modelos", "contexto_resumen"): "abc"}, ruta)

    escrito = ruta.read_text(encoding="utf-8")
    efectivo = cfg.cargar(ruta).modelos.contexto_resumen

    assert "contexto_resumen = abc" in escrito
    assert efectivo == cfg.CONTEXTO_POR_DEFECTO
    assert str(efectivo) != "abc", "lo mostrado y lo efectivo difieren: hay que repintar"


def test_un_modo_desconocido_cae_al_de_por_defecto(tmp_path):
    ruta = preparar(tmp_path)
    cfg.guardar_valores({("general", "modo"): "inventado"}, ruta)

    assert cfg.cargar(ruta).modo == cfg.MODO_POR_DEFECTO


def test_la_carpeta_extra_se_expande(tmp_path):
    ruta = preparar(tmp_path)
    cfg.guardar_valores({("general", "carpeta_resumenes"): "~/Rol"}, ruta)

    carpeta = cfg.cargar(ruta).carpeta_resumenes_extra

    assert carpeta is not None
    assert "~" not in str(carpeta), "'~' debe quedar resuelto"


def test_una_carpeta_extra_vacia_significa_sin_carpeta(tmp_path):
    ruta = preparar(tmp_path)
    cfg.guardar_valores({("general", "carpeta_resumenes"): "   "}, ruta)

    assert cfg.cargar(ruta).carpeta_resumenes_extra is None
    assert cfg.cargar(ruta).destinos_resumen() == [cfg.DIR_RESUMENES]
