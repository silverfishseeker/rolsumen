"""Genera el icono de la aplicación.

    python -m app.recursos.generar_icono

Se guarda el .ico ya generado en el repositorio; este script está para poder
rehacerlo si se quiere cambiar el diseño, no hace falta ejecutarlo al instalar.

El dibujo es un d20 visto de frente: un hexágono con la cara central triangular.
Es el símbolo más reconocible del rol de mesa y, a diferencia de un pergamino o
una pluma, se sigue distinguiendo a 16 píxeles, que es el tamaño al que se ve en
la barra de tareas.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

LADO = 1024  # se dibuja grande y se reduce: los bordes salen suaves
RUTA = Path(__file__).resolve().parent / "rolsumen.ico"

# Tamaños que Windows pide según el contexto (barra de tareas, escritorio,
# explorador en vista grande...). Incluirlos todos evita reescalados feos.
TAMANOS = [16, 24, 32, 48, 64, 128, 256]

VIOLETA_CLARO = (86, 62, 148)
VIOLETA_OSCURO = (28, 21, 51)
ORO = (240, 197, 106)
ORO_SOMBRA = (196, 148, 66)


def _fondo(lado: int) -> Image.Image:
    """Cuadrado redondeado con un degradado vertical."""
    degradado = Image.new("RGB", (1, lado))
    for y in range(lado):
        t = y / (lado - 1)
        degradado.putpixel(
            (0, y),
            tuple(
                round(claro + (oscuro - claro) * t)
                for claro, oscuro in zip(VIOLETA_CLARO, VIOLETA_OSCURO)
            ),
        )
    fondo = degradado.resize((lado, lado))

    mascara = Image.new("L", (lado, lado), 0)
    ImageDraw.Draw(mascara).rounded_rectangle(
        (0, 0, lado - 1, lado - 1), radius=round(lado * 0.22), fill=255
    )

    imagen = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    imagen.paste(fondo, (0, 0), mascara)
    return imagen


def _vertices(centro: float, radio: float, angulos: list[float]) -> list[tuple]:
    return [
        (
            centro + radio * math.cos(math.radians(a)),
            centro - radio * math.sin(math.radians(a)),
        )
        for a in angulos
    ]


def dibujar(lado: int = LADO, grosor_relativo: float = 0.022) -> Image.Image:
    imagen = _fondo(lado)
    lienzo = ImageDraw.Draw(imagen)

    centro = lado / 2
    radio = lado * 0.34
    grosor = max(2, round(lado * grosor_relativo))

    # Hexágono exterior (punta arriba) y triángulo central: así se ve un d20.
    hexagono = _vertices(centro, radio, [90, 150, 210, 270, 330, 30])
    triangulo = _vertices(centro, radio * 0.46, [90, 210, 330])

    lienzo.polygon(hexagono, fill=ORO)

    # Aristas del dado: cada punta del triángulo central sale en línea recta
    # hacia el vértice del hexágono que tiene enfrente. Si se conectan cruzadas,
    # el dado parece una espiral.
    for punta, esquina in zip(triangulo, _vertices(centro, radio, [90, 210, 330])):
        lienzo.line([punta, esquina], fill=ORO_SOMBRA, width=grosor)

    lienzo.polygon(triangulo, fill=ORO, outline=ORO_SOMBRA, width=grosor)
    lienzo.polygon(hexagono, outline=ORO_SOMBRA, width=grosor)

    return imagen


def _grosor_para(tamano: int) -> float:
    """Trazo relativo según el tamaño final del icono.

    Un único dibujo reducido no vale: a 16 px un trazo del 2,2% queda en un
    tercio de píxel y las aristas del dado se desvanecen, dejando una mancha
    dorada. Los tamaños pequeños necesitan un trazo proporcionalmente mayor.
    """
    if tamano <= 24:
        return 0.075
    if tamano <= 48:
        return 0.045
    return 0.022


def guardar(destino: Path = RUTA) -> Path:
    """Escribe el .ico con un dibujo propio para cada tamaño."""
    # Cada tamaño se dibuja en grande y se reduce: da bordes suaves sin
    # depender del reescalado que hiciera Pillow por su cuenta.
    capas = [
        dibujar(tamano * 8, _grosor_para(tamano)).resize(
            (tamano, tamano), Image.Resampling.LANCZOS
        )
        for tamano in TAMANOS
    ]
    destino.parent.mkdir(parents=True, exist_ok=True)
    capas[-1].save(
        destino, format="ICO", sizes=[(t, t) for t in TAMANOS], append_images=capas
    )
    return destino


if __name__ == "__main__":
    print(f"Icono guardado en {guardar()}")
