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
3. `/leave` en Discord → Craig termina la grabación.
4. La aplicación detecta la grabación y procesa todo sola: transcribe, combina y resume.
5. Cierras la aplicación → baja Craig.

Los pasos 2 y 3 se hacen en Discord y son necesariamente manuales (ver *Decisiones de diseño*). Todo lo demás es automático.

## Instalación y puesta en marcha

```bash
# 1. Descargar y preparar Craig (una sola vez)
python -m app.instalar_craig

# 2. Rellenar las credenciales de Discord en app/config.ini, sección [discord]
#    (el identificador de la aplicación ya viene puesto)

# 3. Abrir la aplicación
python -m app.main
```

`app/config.ini` es el **único** archivo que hay que tocar. Las credenciales van ahí:

```ini
[discord]
token_bot =            ; pestaña "Bot" -> "Reset Token"
secreto_cliente =      ; pestaña "OAuth2" -> "Reset Secret"
id_aplicacion = 1539028879342047263   ; "General Information" -> Application ID
```

La aplicación las copia sola al `install.config` interno de Craig antes de arrancarlo, así que ese archivo es un detalle de implementación que no hay que mantener a mano. `config.ini` está en el `.gitignore`, de modo que los secretos no acaban en el repositorio.

Al hacerlo, se aplican también los ajustes que Craig necesita para funcionar dentro de Docker: su `install.config.example` apunta la base de datos a `localhost:5432`, que **no funciona** dentro de un contenedor, y debe ser `db:5432` (el nombre del servicio en `docker-compose.yml`). Lo mismo con Redis.

Modo consola, útil para depurar sin la ventana de por medio:

```bash
python -m app.main --consola
```

Tests:

```bash
python -m pytest tests/ -q
```

## Arquitectura

```
┌─────────────────────────────────────────────┐
│  Aplicación orquestadora (Python + tkinter) │
│  · GUI informativa: estado y progreso       │
│  · Trabajo pesado en hilo aparte            │
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

La aplicación ejecuta `docker compose up -d` al abrirse y `docker compose down` al cerrarse, para no tener Craig corriendo permanentemente. Los datos (base de datos, grabaciones) sobreviven entre sesiones.

## Decisiones de diseño

### Grabación: Craig self-hosted

Se usa [Craig](https://github.com/CraigChat/craig) auto-alojado vía su `docker-compose.yml` oficial (servicios `db` Postgres + `redis` + `craig`, puertos 3000 y 5029). El volumen de grabaciones se monta a una carpeta local para que la aplicación pueda vigilarla.

**Siempre en multipista**, nunca mezcla: cada jugador tiene su propio archivo de audio, así que sabemos quién habla sin recurrir a diarización automática, y **los solapamientos dejan de ser un problema** (cada pista contiene una sola voz, hablen a la vez o no).

Alternativas descartadas:

| Alternativa | Por qué se descartó |
|---|---|
| Craig público (el bot oficial) | Obliga a descargar a mano desde el DM; no se puede automatizar sin violar los ToS de Discord |
| Bot de grabación propio | Reinventar la captura de audio por usuario en Discord, que es la parte técnicamente difícil que Craig ya resuelve |
| Grabar el audio del sistema | Da un único stream mezclado; requeriría diarización, que falla justo cuando la gente se pisa — constante en una partida de rol |
| Automatizar `/join` o la descarga del DM | Exigiría simular a un usuario (*self-bot*), prohibido por Discord y motivo de baneo |

### Transcripción: Whisper `large-v3`

Se usa `large-v3` y no `medium`. En pruebas reales, `medium` **se saltó un párrafo entero de 27 segundos** sin dar ningún error (fallo de decodificación: cerró un segmento de golpe y saltó al final del audio).

`large-v3` transcribió todo correctamente, pero tiene su propio defecto: **alucina texto repetido al final del audio**, con marcas de tiempo que superan la duración real del archivo. Por eso hay que **descartar los segmentos cuya marca de tiempo final exceda la duración real** (comprobable con `ffprobe`).

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
│
├── app/
│   ├── main.py             # punto de entrada (GUI, o --consola)
│   ├── gui.py              # ventana: estado de servicios y progreso
│   ├── config.py           # configuración y rutas del proyecto
│   ├── dependencias.py     # localiza ffmpeg y comprueba la GPU
│   ├── docker_manager.py   # levanta y baja Craig
│   ├── craig_client.py     # consulta grabaciones y ejecuta el "cook"
│   ├── instalar_craig.py   # descarga y prepara Craig (una vez)
│   │
│   ├── pipeline/
│   │   ├── tipos.py        # Segmento y Bloque
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
├── tests/                  # 125 tests, se ejecutan con pytest
└── pruebas/                # material de prueba suelto (ignorado por git)
```

`app/craig/` no forma parte del repositorio: es un proyecto aparte que se descarga con `python -m app.instalar_craig`, y además contiene los tokens de Discord.

## Configuración

`app/config.ini` es el único archivo de configuración. Solo la sección `[discord]` es obligatoria; el resto tiene valores por defecto razonables.

- **`[discord]`** — credenciales de la aplicación de Discord (ver *Instalación*). Se vuelcan solas en la configuración interna de Craig.
- **Carpeta de resúmenes** (opcional). Los resúmenes se guardan **siempre** en `datos/resumenes/`; si se indica una ruta aquí, se guarda **además** una copia allí.
- **Mapeo de jugadores** (opcional). Asocia cada usuario de Discord con el nombre de su personaje. Por defecto se usan los nicks de Discord tal cual.
- **Modelos** (opcional). `modelo_whisper` (por defecto `large-v3`) y `modelo_ollama` (por defecto `qwen3:8b`).

## Requisitos

Entorno verificado en Windows 11:

| Herramienta | Versión |
|---|---|
| Python | 3.10.11 |
| FFmpeg | 9.0 (`winget install Gyan.FFmpeg`) |
| Whisper | `openai-whisper` 20250625 |
| PyTorch | 2.11.0+cu128 (con soporte CUDA) |
| Ollama | 0.31.1 con `qwen3:8b` |
| Docker | 29.4.3 + Compose v5.1.3 |
| GPU | NVIDIA RTX 3070 Ti Laptop (8 GB) |

Para Whisper con GPU hay que instalar PyTorch con CUDA explícitamente:

```
pip install torch --index-url https://download.pytorch.org/whl/cu128 --upgrade
```

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

## Pendiente

- **Arrancar Craig por primera vez.** Requiere los dos secretos de Discord en `install.config`. Hasta entonces no se ha podido comprobar de verdad el arranque de los contenedores ni una grabación real.
- **Probar con una sesión larga de verdad.** El troceado en varios bloques y el contexto en cadena están implementados y cubiertos por tests, pero solo se han ejercitado con transcripciones cortas (un único bloque).
