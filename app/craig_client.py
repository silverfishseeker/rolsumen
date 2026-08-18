"""Acceso a las grabaciones de Craig self-hosted.

Craig NO guarda las pistas ya separadas. En `rec/` deja, por cada grabación:

    <ID>.ogg.header1   <ID>.ogg.header2   <ID>.ogg.data   <ID>.ogg.info ...

que son flujos OGG multiplexados con todos los usuarios dentro del mismo
archivo. Para obtener una pista por jugador hay que pasar por el proceso
"cook" que trae el propio Craig:

    ./cook.sh <ID> flac zip > grabacion.zip

`cook.sh` escribe el ZIP por su salida estándar, y ese ZIP contiene exactamente
lo mismo que descargarías desde la web de Craig: un `.flac` por jugador, más
`info.txt` y `raw.dat`.

Para saber qué grabaciones han terminado se consulta la base de datos: la tabla
`Recording` tiene una columna `endedAt` que sólo se rellena al finalizar.
"""

from __future__ import annotations

import re
import subprocess
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import DIR_CRAIG

TIMEOUT_CONSULTA = 60
# Cocinar una sesión larga puede tardar bastante.
TIMEOUT_COCINADO = 3600

# Archivos del ZIP que no son pistas de audio.
NO_SON_PISTAS = {"info.txt", "raw.dat"}


class ErrorCraig(RuntimeError):
    """Fallo al hablar con Craig o con su base de datos."""


@dataclass(frozen=True)
class Grabacion:
    """Una grabación terminada, lista para procesar."""

    id: str
    guild_id: str
    creada: datetime | None
    terminada: datetime | None

    @property
    def etiqueta_fecha(self) -> str:
        """Fecha en formato AAAA-MM-DD para nombrar archivos."""
        momento = self.creada or self.terminada
        return momento.strftime("%Y-%m-%d") if momento else "sin-fecha"


def _psql(consulta: str, dir_craig: Path = DIR_CRAIG) -> str:
    """Lanza una consulta contra la base de datos de Craig vía Docker.

    Se usa `docker compose exec` en vez de un driver de Postgres para no añadir
    dependencias: ya dependemos de Docker de todos modos.
    """
    try:
        proceso = subprocess.run(
            [
                "docker",
                "compose",
                "exec",
                "-T",
                "db",
                "psql",
                "-U",
                "craig",
                "-d",
                "craig",
                "-t",  # sólo filas, sin cabeceras
                "-A",  # sin alineación, separador '|'
                "-c",
                consulta,
            ],
            cwd=str(dir_craig),
            capture_output=True,
            text=True,
            timeout=TIMEOUT_CONSULTA,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:
        raise ErrorCraig("No se encontró Docker.") from exc
    except subprocess.TimeoutExpired as exc:
        raise ErrorCraig("La consulta a la base de datos tardó demasiado.") from exc

    if proceso.returncode != 0:
        raise ErrorCraig(
            f"Error consultando la base de datos de Craig: {proceso.stderr.strip()}"
        )

    return proceso.stdout


def _fecha(texto: str) -> datetime | None:
    """Convierte una marca de tiempo de Postgres a datetime.

    Postgres devuelve p.ej. '2026-08-18 01:23:45.678+00'. Python 3.10 no acepta
    un desfase horario de dos dígitos ('+00'), sólo '+00:00', así que hay que
    normalizarlo antes.
    """
    texto = texto.strip()
    if not texto:
        return None

    normalizado = texto.replace(" ", "T")

    # '+00' / '-05' -> '+00:00' / '-05:00'
    if re.search(r"[+-]\d{2}$", normalizado):
        normalizado += ":00"

    try:
        return datetime.fromisoformat(normalizado)
    except ValueError:
        return None


def grabaciones_terminadas(dir_craig: Path = DIR_CRAIG) -> list[Grabacion]:
    """Grabaciones cuyo `endedAt` está relleno, es decir, ya finalizadas."""
    consulta = (
        'SELECT id, "guildId", "createdAt", "endedAt" FROM "Recording" '
        'WHERE "endedAt" IS NOT NULL AND errored = false '
        'ORDER BY "createdAt"'
    )
    salida = _psql(consulta, dir_craig)

    grabaciones: list[Grabacion] = []
    for linea in salida.splitlines():
        linea = linea.strip()
        if not linea:
            continue
        partes = linea.split("|")
        if len(partes) < 4:
            continue
        grabaciones.append(
            Grabacion(
                id=partes[0].strip(),
                guild_id=partes[1].strip(),
                creada=_fecha(partes[2]),
                terminada=_fecha(partes[3]),
            )
        )
    return grabaciones


def usuarios(id_grabacion: str, dir_craig: Path = DIR_CRAIG) -> dict[str, str]:
    """Devuelve qué usuario de Discord corresponde a cada número de pista.

    El `cook` self-hosted nombra las pistas sólo con su número (`1.flac`,
    `2.flac`...), a diferencia de la web pública de Craig, que les añade el
    nombre. La correspondencia está en `<ID>.ogg.users`, un fragmento JSON con
    una entrada por pista:

        "0":{}
        ,"1":{"id":"...","username":"silverfishlord",...}

    Ese archivo pesa varios MB porque incluye los avatares en base64, así que
    se extraen los nombres con una expresión regular en vez de parsear el JSON
    entero.
    """
    try:
        proceso = subprocess.run(
            [
                "docker",
                "compose",
                "exec",
                "-T",
                "craig",
                "bash",
                "-c",
                # Se recortan los avatares antes de sacar el archivo del
                # contenedor: sin esto se transferirían megas de base64.
                f"sed -E 's/\"avatar\":\"[^\"]*\"//g' /app/rec/{id_grabacion}.ogg.users",
            ],
            cwd=str(dir_craig),
            capture_output=True,
            text=True,
            timeout=TIMEOUT_CONSULTA,
            encoding="utf-8",
            errors="replace",
        )
    except (subprocess.SubprocessError, OSError):
        return {}

    if proceso.returncode != 0:
        return {}

    encontrados = re.findall(
        r'"(\d+)"\s*:\s*\{[^{}]*?"username"\s*:\s*"([^"]+)"', proceso.stdout
    )
    return {numero: nombre for numero, nombre in encontrados}


def asegurar_atd(dir_craig: Path = DIR_CRAIG) -> bool:
    """Arranca el planificador `atd` dentro del contenedor si no está activo.

    `cook.sh` usa `at` para programar el borrado de sus archivos temporales
    dentro de dos horas. Si el demonio `atd` no está corriendo, `at` devuelve
    error, el script aborta y el ZIP sale vacío, sin ningún mensaje que
    explique la causa real. La imagen de Craig no lo arranca por su cuenta.
    """
    try:
        proceso = subprocess.run(
            [
                "docker",
                "compose",
                "exec",
                "-T",
                "craig",
                "bash",
                "-c",
                "pgrep atd >/dev/null || service atd start",
            ],
            cwd=str(dir_craig),
            capture_output=True,
            text=True,
            timeout=TIMEOUT_CONSULTA,
        )
        return proceso.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


def cocinar(
    id_grabacion: str,
    destino_zip: Path,
    formato: str = "flac",
    dir_craig: Path = DIR_CRAIG,
) -> Path:
    """Ejecuta el proceso `cook` de Craig y guarda el ZIP resultante.

    Equivale a pulsar "Multi-pista → FLAC" en la web de descarga de Craig.
    """
    destino_zip.parent.mkdir(parents=True, exist_ok=True)
    asegurar_atd(dir_craig)

    try:
        with destino_zip.open("wb") as salida:
            proceso = subprocess.run(
                [
                    "docker",
                    "compose",
                    "exec",
                    "-T",
                    "craig",
                    "./cook.sh",
                    id_grabacion,
                    formato,
                    "zip",
                ],
                cwd=str(dir_craig),
                stdout=salida,
                stderr=subprocess.PIPE,
                timeout=TIMEOUT_COCINADO,
            )
    except FileNotFoundError as exc:
        raise ErrorCraig("No se encontró Docker.") from exc
    except subprocess.TimeoutExpired as exc:
        raise ErrorCraig(
            f"El procesado de la grabación {id_grabacion} tardó demasiado."
        ) from exc

    if proceso.returncode != 0:
        detalle = (proceso.stderr or b"").decode("utf-8", errors="replace").strip()
        destino_zip.unlink(missing_ok=True)
        raise ErrorCraig(f"Falló el procesado de {id_grabacion}: {detalle}")

    if not destino_zip.exists() or destino_zip.stat().st_size == 0:
        destino_zip.unlink(missing_ok=True)
        raise ErrorCraig(
            f"El procesado de {id_grabacion} no produjo audio. "
            "¿Se grabó realmente algo?"
        )

    return destino_zip


def extraer_pistas(ruta_zip: Path, destino: Path) -> list[Path]:
    """Descomprime el ZIP y devuelve las rutas de las pistas de audio.

    Se descarta `raw.dat`, que es el volcado crudo y no sirve para transcribir.
    """
    destino.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(ruta_zip) as zf:
            zf.extractall(destino)
            nombres = zf.namelist()
    except zipfile.BadZipFile as exc:
        raise ErrorCraig(f"El archivo {ruta_zip.name} no es un ZIP válido.") from exc

    pistas = [
        destino / nombre
        for nombre in nombres
        if Path(nombre).name not in NO_SON_PISTAS and not nombre.endswith("/")
    ]
    # Ordenar por el número de pista que antepone Craig (1-, 2-, ...).
    pistas.sort(key=lambda p: p.name)
    return [p for p in pistas if p.is_file()]
