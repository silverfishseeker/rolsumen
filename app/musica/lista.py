"""Qué suena y qué espera turno.

Sin nada de Discord a propósito: así se puede probar entera sin red ni bot.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class Pista:
    """Algo que se puede reproducir."""

    titulo: str
    origen: str  # ruta de un archivo local o URL de audio
    pedida_por: str
    local: bool = False
    duracion: float | None = None

    def como_texto(self) -> str:
        if self.duracion is None:
            return self.titulo
        minutos, segundos = divmod(int(self.duracion), 60)
        return f"{self.titulo} ({minutos}:{segundos:02d})"


class Lista:
    """La pista actual y las que esperan.

    No reproduce nada: sólo lleva la cuenta. Quien reproduce le pide la
    siguiente cuando termina una.
    """

    def __init__(self) -> None:
        self.actual: Pista | None = None
        self._pendientes: deque[Pista] = deque()

    def __len__(self) -> int:
        return len(self._pendientes)

    @property
    def pendientes(self) -> list[Pista]:
        return list(self._pendientes)

    @property
    def vacia(self) -> bool:
        return self.actual is None and not self._pendientes

    def anadir(self, pista: Pista) -> int:
        """Encola una pista y devuelve su puesto.

        0 significa que no había nada sonando y le toca ya; 1 que es la
        siguiente, y así. Ese número es lo que se le responde a quien la pide.
        """
        if self.actual is None and not self._pendientes:
            self.actual = pista
            return 0
        self._pendientes.append(pista)
        return len(self._pendientes)

    def siguiente(self) -> Pista | None:
        """Pasa a la siguiente. None cuando ya no queda nada."""
        self.actual = self._pendientes.popleft() if self._pendientes else None
        return self.actual

    def vaciar(self) -> None:
        self.actual = None
        self._pendientes.clear()
