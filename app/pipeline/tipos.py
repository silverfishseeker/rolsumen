"""Tipos de datos compartidos por las distintas fases del pipeline."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Segmento:
    """Un fragmento de habla continuo de una sola persona.

    Los tiempos son segundos desde el inicio de la grabación.
    """

    inicio: float
    fin: float
    texto: str
    hablante: str

    @property
    def duracion(self) -> float:
        return self.fin - self.inicio

    def marca_tiempo(self) -> str:
        """Marca de tiempo legible, formato [h:mm:ss]."""
        total = int(self.inicio)
        horas, resto = divmod(total, 3600)
        minutos, segundos = divmod(resto, 60)
        return f"[{horas}:{minutos:02d}:{segundos:02d}]"

    def linea(self) -> str:
        """Representación en la línea de tiempo combinada."""
        return f"{self.marca_tiempo()} {self.hablante}: {self.texto}"


@dataclass
class Bloque:
    """Un trozo de la transcripción, listo para resumirse por separado."""

    indice: int
    total: int
    segmentos: list[Segmento]

    @property
    def inicio(self) -> float:
        return self.segmentos[0].inicio if self.segmentos else 0.0

    @property
    def fin(self) -> float:
        return self.segmentos[-1].fin if self.segmentos else 0.0

    def texto(self) -> str:
        """La línea de tiempo de este bloque, como texto plano."""
        return "\n".join(seg.linea() for seg in self.segmentos)
