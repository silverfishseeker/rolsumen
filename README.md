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
├── app/                    # código e infraestructura
│   ├── main.py             # punto de entrada (abre la GUI)
│   ├── gui.py              # ventana: estado y progreso
│   ├── orchestrator.py     # coordina el pipeline
│   ├── docker_manager.py   # docker compose up/down
│   ├── config.py           # lee/escribe config.ini
│   ├── config.ini          # ajustes de usuario
│   │
│   └── craig/              # Craig self-hosted
│       ├── docker-compose.yml
│       ├── install.config  # tokens de Discord (ignorado por git)
│       └── rec/            # grabaciones (ignorado por git)
│
├── datos/                  # generado por la app (ignorado por git)
│   ├── grabaciones/
│   ├── transcripciones/
│   └── resumenes/
│
├── tests/                  # tests a ejecutar durante el desarrollo
└── pruebas/                # pruebas manuales sueltas (ignorado por git)
```

Los nombres de los `.py` son orientativos: se ajustan al programar, y una parte solo pasa a subcarpeta si necesita más de un archivo.

## Configuración

`app/config.ini` — pensado para requerir el mínimo posible:

- **Carpeta de resúmenes** (opcional). Los resúmenes se guardan **siempre** en `datos/resumenes/`; si se indica una ruta aquí, se guarda **además** una copia allí.
- **Mapeo de jugadores** (opcional). Asocia cada usuario de Discord con el nombre de su personaje. Por defecto se usan los nicks de Discord tal cual.

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

## Pendiente

- **Formato de las grabaciones de Craig.** Craig guarda audio crudo en OGG dentro de `rec/`, no FLAC multipista listo: existe un proceso *cook* (`cook/`, `cook.sh`) que convierte al formato descargable. Al montar Craig hay que hacer una grabación de prueba y comprobar qué aparece realmente en `rec/`, para decidir entre invocar el *cook* o transcribir los OGG directamente.
- Implementación de la aplicación.
