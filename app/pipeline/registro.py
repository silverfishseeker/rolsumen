"""Registro de grabaciones ya procesadas, para no repetir trabajo.

La aplicación puede abrirse y cerrarse muchas veces; sin este registro, cada
arranque volvería a transcribir y resumir todo lo que hubiera en Craig.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path


@dataclass
class Entrada:
    """Una grabación ya procesada."""

    id: str
    fecha_proceso: str
    resumen: str
    ok: bool = True
    error: str = ""


@dataclass
class Registro:
    """Índice de lo ya procesado, persistido en JSON."""

    ruta: Path
    entradas: dict[str, Entrada] = field(default_factory=dict)

    @classmethod
    def cargar(cls, ruta: Path) -> Registro:
        registro = cls(ruta=ruta)
        if not ruta.exists():
            return registro
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # Un registro corrupto no debe impedir arrancar: se empieza de cero.
            return registro

        conocidos = {c.name for c in fields(Entrada)}
        for id_grabacion, bruto in datos.items():
            if not isinstance(bruto, dict):
                continue
            try:
                # Se ignoran las claves que no conozcamos en vez de tirar la
                # entrada entera: perderla haría reprocesar esa grabación.
                registro.entradas[id_grabacion] = Entrada(
                    **{k: v for k, v in bruto.items() if k in conocidos}
                )
            except TypeError:
                continue
        return registro

    def guardar(self) -> None:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        datos = {k: asdict(v) for k, v in self.entradas.items()}
        self.ruta.write_text(
            json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def ya_procesada(self, id_grabacion: str) -> bool:
        """Sólo cuenta como procesada si terminó bien; los fallos se reintentan."""
        entrada = self.entradas.get(id_grabacion)
        return entrada is not None and entrada.ok

    def marcar_ok(self, id_grabacion: str, resumen: Path) -> None:
        self.entradas[id_grabacion] = Entrada(
            id=id_grabacion,
            fecha_proceso=datetime.now().isoformat(timespec="seconds"),
            resumen=str(resumen),
            ok=True,
        )
        self.guardar()

    def marcar_error(self, id_grabacion: str, error: str) -> None:
        self.entradas[id_grabacion] = Entrada(
            id=id_grabacion,
            fecha_proceso=datetime.now().isoformat(timespec="seconds"),
            resumen="",
            ok=False,
            error=error,
        )
        self.guardar()
