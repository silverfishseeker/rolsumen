# Prompts

Estos archivos son las instrucciones que recibe el modelo de lenguaje al
redactar los resúmenes. Puedes editarlos para ajustar el estilo o el nivel de
detalle **sin tocar el código**: se leen cada vez que se genera un resumen, así
que puedes afinarlos y volver a probar sin reiniciar nada.

## Modos

Hay una carpeta por modo. El modo activo se elige en `config.ini`:

```ini
[general]
modo = rol            ; o: conversacion
```

| Carpeta | Para qué sirve |
|---|---|
| `rol/` | Crónica de partida de rol. Recoge **solo la acción dentro de la ficción** e ignora la charla de la mesa: reglas, tiradas, bromas, temas ajenos. |
| `conversacion/` | Resumen de una conversación normal. Recoge **todo lo que se habló**, sin filtrar nada por ser informal. |

Dentro de cada carpeta:

| Archivo | Qué controla |
|---|---|
| `cronologia.txt` | Convierte cada tramo de transcripción en su parte del resumen. Es el que más influye en el resultado. |
| `cabecera.txt` | La cabecera del documento: sinopsis y, según el modo, personajes y lugares o temas y conclusiones. |

Si a un modo le falta alguno de los dos archivos, se usa el de `rol/`; y si
tampoco está, una versión interna por defecto. Así nada se rompe por borrar un
archivo.

## Cómo se usan

A las instrucciones de `cronologia.txt` se les añade automáticamente, por
debajo:

1. Lo ocurrido en el tramo anterior, como contexto (salvo en el primer tramo).
2. La transcripción del tramo que toca resumir.

No hace falta que menciones nada de eso en el prompt: se encarga la aplicación.

Los encabezados que pidas deben ser de nivel `### `, porque el documento final
los anida bajo su propio `## Cronología`.

## Probar un cambio

Tras editar un prompt no hace falta volver a transcribir:

```bash
python -m app.main --rehacer lista        # ver las sesiones disponibles
python -m app.main --rehacer 2026-08-18_2ne2jFXgXgRO
```

## Consejos

- **Si se cuela contenido que no quieres**, refuerza la regla correspondiente y
  pon un ejemplo del tipo de frase que se está colando.
- **Si el resultado es demasiado escueto**, pide explícitamente que recoja
  frases concretas, nombres y cifras.
- **Si inventa cosas**, insiste en que omita lo que no esté claro en lugar de
  rellenar huecos.
- Los ejemplos concretos funcionan mejor que las órdenes genéricas: decir
  *escribe "Kaelen distinguió dos figuras", no "Kaelen sacó un 20"* dio mucho
  mejor resultado que *"no menciones las tiradas"*.

## Añadir un modo nuevo

1. Crea `prompts/<nombre>/` con sus `cronologia.txt` y `cabecera.txt`.
2. Añade el nombre a `MODOS` en `app/config.py`.
