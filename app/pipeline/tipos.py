"""Lo que circula entre las etapas del pipeline."""

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

    def linea(self) -> str:
        """Cómo aparece en la línea de tiempo combinada."""
        horas, resto = divmod(int(self.inicio), 3600)
        minutos, segundos = divmod(resto, 60)
        return f"[{horas}:{minutos:02d}:{segundos:02d}] {self.hablante}: {self.texto}"


@dataclass
class Bloque:
    """Un trozo de la transcripción, para resumirse por separado."""

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
        return "\n".join(seg.linea() for seg in self.segmentos)
