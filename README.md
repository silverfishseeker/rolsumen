# Rolsumen

Graba sesiones de rol de mesa jugadas por Discord, las transcribe y genera una **cronología estructurada** de lo sucedido, para poder consultar después qué pasó en cada sesión.

## Enlace de invitación del bot

```
https://discord.com/oauth2/authorize?client_id=1539028879342047263&permissions=68176896&scope=bot%20applications.commands
```

---

## Objetivo

Tener un registro consultable de cada partida. **No es un relato literario**: es un acta cronológica, con títulos y secciones, pensada para responder preguntas del tipo *"¿a quién matamos en la torre?"* o *"¿qué nos prometió el alcalde?"* varias sesiones después.

El resumen debe centrarse en la **acción dentro del rol** e ignorar la charla fuera de personaje (reglas, tiradas, temas ajenos a la partida).

## Flujo de uso

1. Abres la aplicación → levanta Craig automáticamente.
2. `/join` en Discord → Craig empieza a grabar.
3. `/stop` en Discord → Craig termina la grabación.
4. La aplicación detecta la grabación y procesa todo sola: transcribe, combina y resume.
5. Cierras la aplicación → baja Craig.

Comandos disponibles del bot: `join`, `stop`, `note`, `recordings`, `autorecord`, `info`, `features`, `server-settings`, `voice-test`, `webapp`, `bless`, `unbless`. (No hay `/leave`: para terminar se usa `/stop`.)

Los pasos 2 y 3 se hacen en Discord y son necesariamente manuales (ver *Decisiones de diseño*). Todo lo demás es automático.

## Instalación y puesta en marcha

```bash
# 1. Descargar y preparar Craig (una sola vez)
python -m app.instalar_craig

# 2. Rellenar las credenciales de Discord en config.ini, sección [discord]
#    (el identificador de la aplicación ya viene puesto)

# 3. Crear el acceso directo (una vez) y abrir con doble clic
python -m app.acceso_directo            # deja Rolsumen.lnk en esta carpeta
python -m app.acceso_directo --escritorio   # y otro en el escritorio
```

También se puede abrir sin él: `python -m app.main`.

`config.ini`, en la raíz del proyecto, es el **único** archivo que hay que tocar. Las credenciales van ahí:

```ini
[discord]
token_bot =            ; pestaña "Bot" -> "Reset Token"
secreto_cliente =      ; pestaña "OAuth2" -> "Reset Secret"
id_aplicacion = 1539028879342047263   ; "General Information" -> Application ID
```

La aplicación las copia sola al `install.config` interno de Craig antes de arrancarlo, así que ese archivo es un detalle de implementación que no hay que mantener a mano. `config.ini` está en el `.gitignore`, de modo que los secretos no acaban en el repositorio.

Al hacerlo, se aplican también los ajustes que Craig necesita para funcionar dentro de Docker: su `install.config.example` apunta la base de datos a `localhost:5432`, que **no funciona** dentro de un contenedor, y debe ser `db:5432` (el nombre del servicio en `docker-compose.yml`). Lo mismo con Redis.

## El acceso directo

`Rolsumen.lnk` apunta a `pythonw.exe`, el intérprete sin consola, así que abre la ventana sin dejar detrás un terminal negro. Lleva el icono de la aplicación y no se sube al repositorio, porque guarda rutas absolutas de la máquina donde se creó: se regenera con `python -m app.acceso_directo`.

El icono (`app/recursos/rolsumen.ico`) es un d20, y se dibuja por separado para cada tamaño que pide Windows: a 16 px, que es el de la barra de tareas, un trazo del 2% se queda en un tercio de píxel y el dado se convierte en una mancha dorada, así que los tamaños pequeños llevan el trazo más grueso. Se regenera con `python -m app.recursos.generar_icono`.

Para que la barra de tareas use ese icono y no el de Python no basta con ponérselo a la ventana: hay que declarar un identificador de aplicación propio con `SetCurrentProcessExplicitAppUserModelID`, y **antes de crear la primera ventana**. Hacerlo después no surte efecto.

## La ventana

Tres pestañas y una barra inferior siempre visible.

**Trabajo** — las tres listas de lo que hay: grabaciones en Craig, transcripciones guardadas y crónicas generadas. Se selecciona una fila de cualquiera de ellas y el botón grande cambia según lo que toque: *Transcribir*, *Resumir* o *Abrir* (esta última abre la crónica con el editor de texto del sistema). Cada fila indica en qué estado está.

**Estado** — los servicios (Docker, Craig, Ollama, ffmpeg, GPU) y el registro de actividad.

**Configuración** — todo lo de `config.ini` sin salir de la aplicación. Al guardar se sustituyen solo los valores: **los comentarios del archivo se conservan**, así que sigue siendo editable a mano.

La barra inferior muestra en qué se está trabajando, cuántas tareas esperan turno, el modo de ejecución y un botón para cancelar la tarea en curso.

### Automático o manual

Se elige en `config.ini` (`[general] ejecucion`) o en la pestaña de configuración.

- **automático** — al abrirse se queda esperando. Cuando termina una grabación en Craig, la transcribe y la resume sin intervención. **Las grabaciones anteriores a abrir la aplicación no se tocan**: si quieres procesar una del historial, se lanza a mano desde la pestaña Trabajo.
- **manual** — no hace nada por su cuenta; cada paso se lanza desde la pestaña Trabajo.

### Una tarea cada vez

Las tareas se encolan y se ejecutan en serie. No es una limitación de diseño sino de memoria de vídeo, medida en la GPU de 8 GB de referencia:

| | VRAM |
|---|---|
| Whisper large-v3 (float16) | 4,0 GB |
| Ollama qwen3:8b @ 8192 de contexto | 5,8 GB |

Dos tareas de GPU a la vez piden 9,8 GB y no caben; dos transcripciones se quedan en 8,1 GB, también por encima. Con lo que hay, ejecutarlas en paralelo solo conseguiría que Ollama descargase capas a la CPU y la generación se desplomara.

Cancelar afecta únicamente a la tarea en curso: la cola continúa con la siguiente.

Si algo no arranca, este comando revisa todos los requisitos por orden y dice cuál falla:

```bash
python -m app.diagnostico
```

Modo consola, útil para depurar sin la ventana de por medio:

```bash
python -m app.main --consola
```

Regenerar la crónica de una sesión ya transcrita, sin volver a transcribir. Es la forma práctica de afinar los prompts o el mapeo de personajes: tarda un minuto en lugar de lo que cueste transcribir horas de audio.

```bash
python -m app.main --rehacer lista      # ver las sesiones disponibles
python -m app.main --rehacer 2026-08-18_2ne2jFXgXgRO
```

Tests:

```bash
python -m pytest tests/ -q
```

## Arquitectura

```
┌─────────────────────────────────────────────┐
│  Aplicación orquestadora (Python + tkinter) │
│  · Trabajo / Estado / Configuración         │
│  · Cola en serie, una tarea cada vez        │
└───┬──────────────┬──────────────┬───────────┘
    │              │              │
    │ docker       │ transcribe   │ HTTP
    ▼ compose      ▼              ▼ localhost:11434
┌─────────┐   ┌─────────┐   ┌──────────┐
│  Craig  │   │ Whisper │   │  Ollama  │
│ (Docker)│   │large-v3 │   │ qwen3:8b │
│ Discord │   │  (GPU)  │   │  (local) │
└─────────┘   └─────────┘   └──────────┘
```

**Pipeline:** Craig (audio multipista) → Whisper (transcripción por pista) → combinado por marcas de tiempo → Ollama (cronología) → Markdown.

La aplicación ejecuta `docker compose up -d` al abrirse y `docker compose stop` al cerrarse, para no tener Craig corriendo permanentemente. Los datos (base de datos, grabaciones) sobreviven entre sesiones.

Es `stop` y no `down` por una razón medida: Craig hace su instalación completa —yarn, prisma, compilar los binarios del `cook`— **al arrancar el contenedor**, no al construir la imagen, y lo marca con `/app/.installed` en su capa de escritura. `down` borra el contenedor y con él el marcador, así que la instalación entera se repite: unos 15 minutos.

Con `stop`, cerrar y reabrir la aplicación tarda **6 segundos**. No es una garantía absoluta: se ha observado que un reinicio de Docker Desktop (o suspender el equipo) puede vaciar igualmente la capa de escritura del contenedor y disparar la reinstalación. Pero en el uso normal —abrir, grabar, cerrar— el arranque es inmediato.

Por el mismo motivo, el `docker-compose.override.yml` fija `restart: "no"` en los tres servicios: Craig trae `restart: always`, que devuelve los contenedores a la vida al arrancar Docker Desktop aunque Rolsumen esté cerrado.

## Decisiones de diseño

### Grabación: Craig self-hosted

Se usa [Craig](https://github.com/CraigChat/craig) auto-alojado vía su `docker-compose.yml` oficial (servicios `db` Postgres + `redis` + `craig`, puertos 3000 y 5029), **sin modificarlo**: la aplicación no lee la carpeta de grabaciones directamente, sino que consulta la base de datos y pide el audio con `cook.sh` (ver más abajo).

**Siempre en multipista**, nunca mezcla: cada jugador tiene su propio archivo de audio, así que sabemos quién habla sin recurrir a diarización automática, y **los solapamientos dejan de ser un problema** (cada pista contiene una sola voz, hablen a la vez o no).

Alternativas descartadas:

| Alternativa | Por qué se descartó |
|---|---|
| Craig público (el bot oficial) | Obliga a descargar a mano desde el DM; no se puede automatizar sin violar los ToS de Discord |
| Bot de grabación propio | Reinventar la captura de audio por usuario en Discord, que es la parte técnicamente difícil que Craig ya resuelve |
| Grabar el audio del sistema | Da un único stream mezclado; requeriría diarización, que falla justo cuando la gente se pisa — constante en una partida de rol |
| Automatizar `/join` o la descarga del DM | Exigiría simular a un usuario (*self-bot*), prohibido por Discord y motivo de baneo |

### La imagen de Craig hay que reconstruirla tras parchearla

`/app` dentro del contenedor sale de la **imagen**, no del clon del host. El arreglo de Redis se aplica a los archivos del clon, así que mientras la imagen conserve el `redis: {}` original, cada contenedor nuevo revive el fallo: `install.sh` regenera `default.js` desde una plantilla sin parchear y el bot se queda sin conectar, llenando el log de `ECONNREFUSED 127.0.0.1:6379`.

`python -m app.instalar_craig` lo detecta y reconstruye solo. A mano sería `docker compose build craig`.

**Cuidado:** `_default.js` es la *plantilla*; `install.sh` la copia a `default.js` y le sustituye el token y el Application ID. Copiar la plantilla encima del generado borra las credenciales y el bot falla con `Missing required token`. Además el archivo tiene dos `token: ''` y el primero es un ejemplo comentado, así que la sustitución va a partir del bloque `dexare:`.

### Transcripción: `faster-whisper` con `large-v3`

Se usa **`faster-whisper`**, no la biblioteca original de OpenAI. No es otro modelo: ejecuta exactamente los mismos modelos de Whisper, pero sobre CTranslate2 en vez de PyTorch. Es del orden de **4 veces más rápido, con menos consumo de memoria de vídeo**, y sobre todo trae **detección de voz (VAD)** integrada.

El VAD es la razón principal del cambio. La pista de cada jugador es **mayoritariamente silencio** (solo suena cuando esa persona habla), y Whisper alucina justo sobre el silencio. Con VAD, esos tramos ni siquiera se transcriben, en lugar de filtrarlos a posteriori.

Se usa el modelo `large-v3` y no `medium`: en pruebas reales, `medium` **se saltó un párrafo entero de 27 segundos** sin dar ningún error (cerró un segmento de golpe y saltó al final del audio).

### Resumen: Ollama en local

Se usa `qwen3:8b` corriendo en local con Ollama. Descartada la API de Anthropic: es de pago aparte y no está cubierta por una suscripción de Claude Pro. El modelo local es gratuito, funciona sin conexión y la calidad es suficiente para esta tarea.

### Troceado de transcripciones largas

Una sesión de 4 horas son unas 31.000 palabras (**más de 50.000 tokens**) y no cabe en el modelo:

| Dato | Valor |
|---|---|
| Contexto máximo de `qwen3:8b` | 40.960 tokens |
| Por defecto Ollama usa | 4.096 tokens (hay que subirlo) |
| Utilizable en la práctica con 8 GB de VRAM | ~16.000–20.000 tokens |

Estrategia adoptada:

1. **Número de trozos adaptativo.** Se calcula por sesión (la duración es muy variable) y se reparte **equitativamente**, para que el último bloque no quede en dos minutos sueltos.
2. **Corte en pausas naturales.** Se corta en un silencio cercano al punto ideal, aprovechando las marcas de tiempo, en vez de partir una frase por la mitad.
3. **Contexto en cadena.** Al resumir cada bloque se le pasa el resumen del anterior como antecedente, indicándole que solo narre los hechos nuevos.

**Sin solape entre bloques.** El solape daría continuidad, pero duplicaría hechos en la cronología final — justo lo que más estorba en un documento de consulta. Los puntos 2 y 3 cubren el mismo problema sin ese efecto secundario. Si al probar con sesiones reales se pierde continuidad en las fronteras, añadirlo después es trivial.

## Estructura del proyecto

```
rolsumen/
├── README.md
├── .gitignore
├── config.ini              # ÚNICO archivo a configurar (ignorado por git)
│
├── app/
│   ├── main.py             # punto de entrada (GUI, o --consola)
│   ├── gui.py              # ventana: trabajo, estado y configuración
│   ├── config.py           # lee config.ini y define las rutas
│   ├── dependencias.py     # localiza ffmpeg y comprueba la GPU
│   ├── docker_manager.py   # levanta y baja Craig
│   ├── craig_client.py     # consulta grabaciones y ejecuta el "cook"
│   ├── instalar_craig.py   # descarga y prepara Craig (una vez)
│   ├── diagnostico.py      # revisa los requisitos y dice qué falla
│   ├── acceso_directo.py   # crea Rolsumen.lnk con su icono
│   │
│   ├── recursos/           # icono de la aplicación
│   │   ├── rolsumen.ico
│   │   └── generar_icono.py
│   │
│   ├── prompts/            # instrucciones del modelo, editables
│   │   ├── rol/            #   cronologia.txt + cabecera.txt
│   │   ├── conversacion/   #   cronologia.txt + cabecera.txt
│   │   └── LEEME.md
│   │
│   ├── pipeline/
│   │   ├── tipos.py        # Segmento y Bloque
│   │   ├── cola.py         # tareas en serie, con cancelación
│   │   ├── transcriptor.py # Whisper + filtrado de alucinaciones
│   │   ├── combinador.py   # une las pistas en una línea de tiempo
│   │   ├── troceador.py    # troceado adaptativo con corte en pausas
│   │   ├── resumidor.py    # Ollama: crónica en dos fases
│   │   ├── registro.py     # qué se ha procesado ya (idempotencia)
│   │   └── orquestador.py  # encadena todo lo anterior
│   │
│   └── craig/              # Craig self-hosted (ignorado por git)
│
├── datos/                  # generado por la app (ignorado por git)
│   ├── grabaciones/        # ZIP de audio ya procesado
│   ├── transcripciones/    # transcripciones y línea de tiempo
│   ├── resumenes/          # crónicas generadas
│   └── procesadas.json     # registro de idempotencia
│
└── tests/                  # 263 tests, se ejecutan con pytest
```

`app/craig/` no forma parte del repositorio: es un proyecto aparte que se descarga con `python -m app.instalar_craig`, y además contiene los tokens de Discord.

## Configuración

`config.ini`, en la raíz del proyecto, es el único archivo de configuración. Solo la sección `[discord]` es obligatoria; el resto tiene valores por defecto razonables.

| Sección | Para qué |
|---|---|
| `[discord]` | Credenciales de la aplicación de Discord. Se vuelcan solas en la configuración interna de Craig. |
| `[general]` | Carpeta adicional de resúmenes e idioma de las grabaciones. |
| `[modelos]` | Qué modelos se usan y cómo se ejecutan (ver abajo). |
| `[jugadores]` | Nick de Discord → nombre del personaje. Sin mapeo, se usa el nick. |

**Carpeta de resúmenes**: los resúmenes se guardan **siempre** en `datos/resumenes/`; si se indica una ruta en `carpeta_resumenes`, se guarda **además** una copia allí.

**Modelos configurables** (`[modelos]`):

| Ajuste | Por defecto | Alternativas |
|---|---|---|
| `transcripcion` | `large-v3` | `medium`, `small`, `base` (más rápidos, menos precisos) |
| `precision` | `float16` | `int8_float16` (ahorra memoria), `int8` (el más ligero) |
| `dispositivo` | `auto` | `cuda`, `cpu` |
| `resumen` | `qwen3:8b` | cualquier modelo que aparezca en `ollama list` |
| `contexto_resumen` | `8192` | subir si sobra memoria de vídeo, bajar si falta. Medido con qwen3:8b en 8 GB: 8192 cabe entero en la GPU, 12288 ya no y la generación se desploma |

En CPU la precisión `float16` no existe, así que se degrada sola a `int8` en lugar de fallar al cargar el modelo.

Con `large-v3` en `float16`, la transcripción ocupa **casi 8 GB de memoria de vídeo** (medido: 7901 MiB de 8192 en una RTX 3070 Ti). Si aparecen errores de memoria, bajar a `int8_float16` es lo primero que hay que probar.

## Modos de resumen

La aplicación sabe resumir dos cosas distintas, y se elige con una línea de `config.ini`:

```ini
[general]
modo = rol            ; o: conversacion
```

| Modo | Qué hace |
|---|---|
| `rol` | Crónica de partida. Recoge **solo la acción dentro de la ficción** e ignora la charla de la mesa: reglas, tiradas, bromas, temas ajenos. La cabecera lleva sinopsis, personajes y lugares. |
| `conversacion` | Resumen de una conversación normal. Recoge **todo lo que se habló**, sin filtrar nada por ser informal. La cabecera lleva sinopsis, temas tratados y conclusiones. |

El modo `conversacion` es además el que conviene para probar el sistema cuando no hay una partida grabada: con el modo `rol`, una grabación de charla normal produce una crónica casi vacía — que es el filtro funcionando, no un fallo.

Un modo desconocido en `config.ini` no rompe nada: se usa `rol`.

## Prompts

Las instrucciones que recibe el modelo de lenguaje **no están en el código**: viven en `app/prompts/<modo>/`, como archivos de texto que se pueden editar para ajustar el estilo o el nivel de detalle sin tocar Python. Se releen en cada resumen, así que se puede afinar el prompt y volver a probar sin reiniciar.

| Archivo | Qué controla |
|---|---|
| `app/prompts/<modo>/cronologia.txt` | Cómo se convierte cada tramo de transcripción en resumen. Es el que más influye en el resultado. |
| `app/prompts/<modo>/cabecera.txt` | La cabecera del documento. |

Si a un modo le falta un archivo se usa el de `rol/`, y si tampoco está, una versión interna por defecto — así nada se rompe por borrar un archivo. Para probar un cambio sin volver a transcribir, `--rehacer` (ver *Instalación*). Más detalle en `app/prompts/LEEME.md`.

## Requisitos

Entorno verificado en Windows 11:

| Herramienta | Versión |
|---|---|
| Python | 3.10.11 |
| FFmpeg | 9.0 (`winget install Gyan.FFmpeg`) |
| Transcripción | `faster-whisper` 1.2.1 |
| PyTorch | 2.11.0+cu128 (con soporte CUDA) |
| Ollama | 0.31.1 con `qwen3:8b` |
| Docker | 29.4.3 + Compose v5.1.3 |
| GPU | NVIDIA RTX 3070 Ti Laptop (8 GB) |

Instalación de las dependencias de Python:

```
pip install faster-whisper
pip install torch --index-url https://download.pytorch.org/whl/cu128 --upgrade
```

PyTorch solo se usa para detectar si hay GPU disponible; la transcripción corre sobre CTranslate2. La primera transcripción descarga el modelo (unos 3 GB) y lo deja en caché.

## Cuánto tarda

Medido con una sesión real de **1 h 44 min y 3 participantes**, en una RTX 3070 Ti (8 GB):

| Fase | Tiempo | Notas |
|---|---|---|
| Extracción (`cook`) | ~9 min | Produce un ZIP de 196 MB con las tres pistas en FLAC |
| Transcripción pista 1 | ~6 min | 35 MB de audio, 403 segmentos |
| Transcripción pista 2 | ~31 min | 80 MB de audio, 991 segmentos |
| Transcripción pista 3 | ~9 min | 48 MB de audio, 574 segmentos |
| Resumen | pocos minutos | Depende del número de bloques |

La transcripción depende de **cuánto habla cada persona**, no de la duración de la sesión: el detector de voz se salta el silencio, y en una pista de jugador el silencio es la mayor parte. Por eso la pista del que más hablaba tardó cinco veces más que las otras.

Dos avisos:

- **Whisper y Ollama compiten por la memoria de vídeo.** En el pipeline normal no se pisan porque van en fases distintas, pero lanzar un resumen mientras hay una transcripción en curso ralentiza mucho las dos cosas.
- **El nombre de los hablantes afecta al número de bloques.** Las etiquetas se repiten en cada intervención, así que nombres largos consumen tokens: la misma sesión salió en 3 bloques con nombres cortos y en 4 con los nombres de usuario completos.

## Cómo se obtienen las grabaciones de Craig

Craig **no** deja las pistas ya separadas. En `rec/` guarda, por cada grabación:

```
<ID>.ogg.header1   <ID>.ogg.header2   <ID>.ogg.data   ...
```

que son flujos OGG **multiplexados**, con todos los usuarios dentro del mismo archivo. Para obtener una pista por jugador hay que pasar por el proceso *cook* que trae el propio Craig:

```
./cook.sh <ID> flac zip
```

`cook.sh` escribe el ZIP por su **salida estándar**, y ese ZIP contiene exactamente lo mismo que se descarga desde la web de Craig: un `.flac` por jugador más `info.txt` y `raw.dat`. La aplicación lo invoca con `docker compose exec`.

Para saber **qué grabaciones han terminado** se consulta la base de datos: la tabla `Recording` tiene una columna `endedAt` que solo se rellena al finalizar. Esto evita tener que adivinar por el tamaño o la fecha de los archivos.

Consecuencia práctica: **no hace falta montar `rec/` en el host**. La aplicación nunca lee esa carpeta directamente — pregunta a la base de datos y pide el audio por `cook.sh`. Por eso el `docker-compose.yml` de Craig se usa tal cual, sin modificaciones.

## Hallazgos de las pruebas

Cosas que se descubrieron probando y que condicionan el código:

**Whisper alucina sobre el silencio.** Con audio casi mudo, `large-v3` inventa muletillas como `"Gracias."` que ninguna lista de frases conocidas cubre de forma fiable (la gente también da las gracias de verdad). La señal utilizable es la que el propio Whisper adjunta a cada segmento: `no_speech_prob` y `avg_logprob`. Se descarta un segmento solo cuando **fallan ambas**, usando los mismos umbrales que Whisper aplica internamente (`0.6` y `-1.0`). Filtrar por una sola de las dos se cargaría frases cortas legítimas.

**`ffmpeg` fuera del PATH da un error indescifrable.** Whisper lanza `ffmpeg` como proceso aparte; si no está en el PATH, el error es `[WinError 2] El sistema no puede encontrar el archivo especificado`, que no menciona ffmpeg por ningún lado. Pasa con facilidad en Windows: al instalarlo con winget, el PATH del sistema cambia pero los procesos ya abiertos siguen con el antiguo. `app/dependencias.py` lo busca también en las rutas habituales de instalación y lo añade al PATH del proceso, y si de verdad falta, da un mensaje que dice qué instalar.

**El troceado tiene que cortar en pausas.** Ver *Decisiones de diseño*. Además el resumidor traduce mecánica a ficción: sin instrucción explícita, el modelo escribía *"Kaelen sacó un 20 en percepción"* en vez de *"Kaelen distinguió dos figuras junto al portón"*.

**Craig necesita PostgreSQL 16, no la última versión.** Su `docker-compose.yml` pide `image: postgres` sin fijar versión, lo que hoy resuelve a PostgreSQL 18. La 18 cambió dónde espera los datos (`/var/lib/postgresql` en lugar de `/var/lib/postgresql/data`, que es lo que Craig monta), y el contenedor entra en bucle de reinicio. Se corrige con un `docker-compose.override.yml` que fija `postgres:16`; Docker Compose lo fusiona solo, así que los archivos de Craig quedan intactos y la corrección sobrevive a una actualización suya.

**Hay que desactivar el razonamiento del modelo.** `qwen3` y otros modelos de razonamiento generan un bloque `<think>` antes de responder — que aquí se descarta siempre, así que producirlo es tiempo tirado. El coste no es menor: con el mismo prompt trivial, **más de 300 segundos con razonamiento frente a 19 sin él**. Con bloques reales de una sesión larga, eso hacía que el resumen fallara por timeout. Se desactiva con `"think": false` en la llamada a Ollama, con reintento automático para versiones que no admitan ese parámetro.

De paso: un timeout ya no se reporta como *"¿Está Ollama en marcha?"*. Ese mensaje mandaba a comprobar lo que no fallaba; ahora dice que tardó demasiado y sugiere bajar `contexto_resumen` o usar un modelo más pequeño.

**El contenedor necesita el demonio `atd` arrancado.** `cook.sh` usa `at` para programar el borrado de sus archivos temporales dentro de dos horas. La imagen de Craig no arranca `atd`, así que `at` falla, el script aborta **y el ZIP sale vacío con código de salida 0** — es decir, sin ningún síntoma que apunte a la causa. La aplicación arranca `atd` antes de cada extracción, y además trata un ZIP vacío como error explícito en vez de seguir adelante con un archivo inservible.

**Los archivos de configuración deben llevar saltos de línea Unix.** Los genera Python en Windows pero los consume un contenedor Linux; con CRLF, el shell del contenedor falla con `line 4: $'\r': command not found`, que no dice nada de saltos de línea. Ojo: `newline="\n"` al escribir **no basta**, porque no convierte los CRLF que ya vengan en el texto (por ejemplo al releer un archivo editado con el Bloc de notas) — hay que normalizarlos explícitamente.

## Pendiente

- **Arrancar Craig por primera vez.** Requiere los dos secretos de Discord en `install.config`. Hasta entonces no se ha podido comprobar de verdad el arranque de los contenedores ni una grabación real.
- **Probar con una sesión larga de verdad.** El troceado en varios bloques y el contexto en cadena están implementados y cubiertos por tests, pero solo se han ejercitado con transcripciones cortas (un único bloque).
