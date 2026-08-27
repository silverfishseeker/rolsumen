"""Las etapas que convierten una grabación en un documento.

Se ejecutan en este orden, y cada una recibe lo que produjo la anterior:

    transcriptor  audio           -> segmentos de una pista
    combinador    varias pistas   -> una línea de tiempo única
    troceador     línea de tiempo -> bloques que quepan en el modelo
    resumidor     bloques         -> documento en Markdown

`tipos` define lo que circula entre ellas (`Segmento` y `Bloque`), `registro`
lleva la cuenta de lo ya procesado, y `orquestador` encadena todo lo anterior.

Los módulos no se reexportan aquí a propósito: importándolos por su nombre
completo (`from app.pipeline.troceador import trocear`) se ve de un vistazo de
qué etapa viene cada cosa.
"""
