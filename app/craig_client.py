"""Acceso a las grabaciones de Craig self-hosted.

Craig no guarda las pistas separadas: en `rec/` deja flujos OGG multiplexados
(`<ID>.ogg.data` y sus cabeceras) con todos los usuarios dentro del mismo
archivo. Para obtener una pista por jugador hay que pasar por su proceso
"cook", que escribe por salida estándar el mismo ZIP que da la web de Craig.

Para saber qué grabaciones han terminado se consulta la base de datos: la
columna `endedAt` de la tabla `Recording` sólo se rellena al finalizar.
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
TIMEOUT_COCINADO = 3600  # cocinar una sesión larga tarda

NO_SON_PISTAS = {"info.txt", "raw.dat"}


class ErrorCraig(RuntimeError):
    """Fallo al hablar con Craig o con su base de datos."""


@dataclass(frozen=True)
class Grabacion:
    id: str
    creada: datetime | None
    terminada: datetime | None

    @property
    def etiqueta_fecha(self) -> str:
        momento = self.creada or self.terminada
        return momento.strftime("%Y-%m-%d") if momento else "sin-fecha"


def _en_craig(
    argumentos: list[str], dir_craig: Path, timeout: int = TIMEOUT_CONSULTA, **extra
):
    """Ejecuta `docker compose <argumentos>` en la carpeta de Craig."""
    return subprocess.run(
        ["docker", "compose", *argumentos],
        cwd=str(dir_craig),
        timeout=timeout,
        **extra,
    )


def _psql(consulta: str, dir_craig: Path = DIR_CRAIG) -> str:
    """Consulta la base de datos de Craig a través de Docker.

    Se usa `docker compose exec` en vez de un driver de Postgres para no añadir
    una dependencia: de Docker ya dependemos igualmente.
    """
    try:
        proceso = _en_craig(
            ["exec", "-T", "db", "psql", "-U", "craig", "-d", "craig",
             "-t", "-A", "-c", consulta],
            dir_craig,
            capture_output=True,
            text=True,
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

    Postgres da el desfase horario con dos dígitos ('+00'), que Python 3.10 no
    acepta: espera '+00:00'.
    """
    texto = texto.strip()
    if not texto:
        return None

    normalizado = texto.replace(" ", "T")
    if re.search(r"[+-]\d{2}$", normalizado):
        normalizado += ":00"

    try:
        return datetime.fromisoformat(normalizado)
    except ValueError:
        return None


def grabaciones_terminadas(dir_craig: Path = DIR_CRAIG) -> list[Grabacion]:
    salida = _psql(
        'SELECT id, "createdAt", "endedAt" FROM "Recording" '
        'WHERE "endedAt" IS NOT NULL AND errored = false ORDER BY "createdAt"',
        dir_craig,
    )

    grabaciones = []
    for linea in salida.splitlines():
        partes = linea.strip().split("|")
        if len(partes) >= 3:
            grabaciones.append(
                Grabacion(
                    id=partes[0].strip(),
                    creada=_fecha(partes[1]),
                    terminada=_fecha(partes[2]),
                )
            )
    return grabaciones


def usuarios(id_grabacion: str, dir_craig: Path = DIR_CRAIG) -> dict[str, str]:
    """Qué usuario de Discord corresponde a cada número de pista.

    El `cook` self-hosted nombra las pistas sólo con su número (`1.flac`), a
    diferencia de la web pública. La correspondencia está en `<ID>.ogg.users`,
    un fragmento JSON con una entrada por pista. Ese archivo pesa varios MB por
    los avatares en base64, así que se recortan dentro del contenedor y luego
    se extraen los nombres con una expresión regular.
    """
    try:
        proceso = _en_craig(
            ["exec", "-T", "craig", "bash", "-c",
             f"sed -E 's/\"avatar\":\"[^\"]*\"//g' /app/rec/{id_grabacion}.ogg.users"],
            dir_craig,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except (subprocess.SubprocessError, OSError):
        return {}

    if proceso.returncode != 0:
        return {}

    return dict(
        re.findall(r'"(\d+)"\s*:\s*\{[^{}]*?"username"\s*:\s*"([^"]+)"', proceso.stdout)
    )


def asegurar_atd(dir_craig: Path = DIR_CRAIG) -> bool:
    """Arranca el planificador `atd` dentro del contenedor si no está activo.

    `cook.sh` usa `at` para programar el borrado de sus temporales. Sin `atd`,
    `at` falla, el script aborta y el ZIP sale **vacío con código de salida 0**,
    sin ninguna pista de la causa real. La imagen de Craig no lo arranca.
    """
    try:
        proceso = _en_craig(
            ["exec", "-T", "craig", "bash", "-c",
             "pgrep atd >/dev/null || service atd start"],
            dir_craig,
            capture_output=True,
            text=True,
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
    """Ejecuta el `cook` de Craig y guarda el ZIP resultante.

    Equivale a pulsar "Multi-pista → FLAC" en su web de descarga.
    """
    destino_zip.parent.mkdir(parents=True, exist_ok=True)
    asegurar_atd(dir_craig)

    try:
        with destino_zip.open("wb") as salida:
            proceso = _en_craig(
                ["exec", "-T", "craig", "./cook.sh", id_grabacion, formato, "zip"],
                dir_craig,
                timeout=TIMEOUT_COCINADO,
                stdout=salida,
                stderr=subprocess.PIPE,
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
            f"El procesado de {id_grabacion} no produjo audio. ¿Se grabó algo?"
        )

    return destino_zip


def extraer_pistas(ruta_zip: Path, destino: Path) -> list[Path]:
    """Descomprime el ZIP y devuelve solo las pistas de audio."""
    destino.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(ruta_zip) as zf:
            zf.extractall(destino)
            nombres = zf.namelist()
    except zipfile.BadZipFile as exc:
        raise ErrorCraig(f"El archivo {ruta_zip.name} no es un ZIP válido.") from exc

    pistas = sorted(
        destino / nombre
        for nombre in nombres
        if Path(nombre).name not in NO_SON_PISTAS and not nombre.endswith("/")
    )
    return [p for p in pistas if p.is_file()]
