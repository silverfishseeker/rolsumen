"""Una sola ventana de Rolsumen a la vez.

Dos instancias sobre los mismos datos se pisarían: ambas levantarían Craig,
ambas vigilarían grabaciones nuevas y las dos podrían transcribir la misma
sesión a la vez, que es justo lo que la cola evita dentro de una.

Abrir la aplicación por segunda vez no da error: trae al frente la ventana que
ya está abierta, que es lo que se quería al hacer doble clic.

## Por qué hace falta tanto para enfocar una ventana

Windows no deja que un proceso le robe el primer plano a otro, ni siquiera
recién lanzado desde el Explorador (comprobado). Así que el que enfoca no es el
que llega, sino el que ya estaba:

    la segunda instancia   →  concede permiso al proceso de la primera
                              (`AllowSetForegroundWindow`) y avisa por un
                              evento con nombre
    la primera instancia   →  ve el aviso en su bucle de eventos y se trae a sí
                              misma al frente, cosa que ahora sí se le permite

Si algo de eso falla queda el apaño de ponerla encima sin quitarle el teclado a
nadie, y como último recurso un mensaje.
"""

from __future__ import annotations

import sys

# Nombres globales que identifican la aplicación entre procesos del usuario.
NOMBRE_MUTEX = "Rolsumen.InstanciaUnica"
NOMBRE_EVENTO = "Rolsumen.TraerAlFrente"
TITULO_VENTANA = "Rolsumen"

ERROR_ALREADY_EXISTS = 183
ASFW_ANY = -1
WAIT_OBJECT_0 = 0
EVENT_MODIFY_STATE = 0x0002

# Se guardan a nivel de módulo a propósito: si se recolectasen, Windows
# liberaría el mutex y una segunda instancia creería que no hay ninguna.
_mutex = None
_evento = None


def _kernel():
    import ctypes

    return ctypes.windll.kernel32


def _usuario():
    import ctypes

    return ctypes.windll.user32


def reservar(
    nombre: str = NOMBRE_MUTEX, nombre_evento: str = NOMBRE_EVENTO
) -> bool:
    """Reserva el puesto de instancia única. False si ya había otra.

    Los nombres son parámetros para poder probarlo sin depender de que la
    aplicación de verdad esté cerrada.

    Fuera de Windows no se comprueba nada: el mecanismo es un mutex con nombre.
    """
    global _mutex, _evento

    if sys.platform != "win32":
        return True

    try:
        import ctypes
        from ctypes import wintypes

        kernel = _kernel()
        kernel.CreateMutexW.argtypes = [
            ctypes.c_void_p,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        ]
        kernel.CreateMutexW.restype = wintypes.HANDLE

        _mutex = kernel.CreateMutexW(None, True, nombre)
        if kernel.GetLastError() == ERROR_ALREADY_EXISTS:
            return False

        # Por aquí avisará una segunda instancia de que quiere vernos.
        kernel.CreateEventW.argtypes = [
            ctypes.c_void_p,
            wintypes.BOOL,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        ]
        kernel.CreateEventW.restype = wintypes.HANDLE
        _evento = kernel.CreateEventW(None, True, False, nombre_evento)
        return True
    except (AttributeError, OSError):
        # Sin poder comprobarlo, mejor dejar abrir que bloquear la aplicación.
        return True


def hay_peticion_de_frente() -> bool:
    """¿Alguien ha pedido que nos pongamos delante? Consume la petición."""
    if sys.platform != "win32" or _evento is None:
        return False
    try:
        kernel = _kernel()
        if kernel.WaitForSingleObject(_evento, 0) == WAIT_OBJECT_0:
            kernel.ResetEvent(_evento)
            return True
    except (AttributeError, OSError):
        pass
    return False


def _ventanas_visibles():
    """(handle, título) de cada ventana de nivel superior visible."""
    import ctypes
    from ctypes import wintypes

    usuario = _usuario()
    encontradas: list[tuple[int, str]] = []
    PROTOTIPO = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visitar(handle, _extra):
        if usuario.IsWindowVisible(handle):
            largo = usuario.GetWindowTextLengthW(handle)
            if largo:
                texto = ctypes.create_unicode_buffer(largo + 1)
                usuario.GetWindowTextW(handle, texto, largo + 1)
                encontradas.append((handle, texto.value))
        return True

    usuario.EnumWindows(PROTOTIPO(visitar), 0)
    return encontradas


def _buscar_ventana(titulo: str) -> int | None:
    for handle, texto in _ventanas_visibles():
        if texto == titulo:
            return handle
    return None


def _proceso_de(handle: int) -> int:
    import ctypes
    from ctypes import wintypes

    pid = wintypes.DWORD()
    _usuario().GetWindowThreadProcessId(handle, ctypes.byref(pid))
    return pid.value


def ponerse_al_frente(handle: int) -> bool:
    """La usa la instancia que YA estaba abierta, sobre su propia ventana."""
    if sys.platform != "win32":
        return False
    try:
        usuario = _usuario()
        if usuario.IsIconic(handle):
            usuario.ShowWindow(handle, 9)  # SW_RESTORE
        usuario.SetForegroundWindow(handle)
        return usuario.GetForegroundWindow() == handle
    except (AttributeError, OSError):
        return False


def empujar(handle: int) -> bool:
    """Muestra la ventana sin quitarle el teclado a nadie.

    No hace falta ser el proceso en primer plano para esto, así que funciona
    siempre. No es lo ideal —el foco se queda donde estaba— pero la ventana se
    ve, que es lo que buscaba quien hizo doble clic.
    """
    usuario = _usuario()
    HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
    BANDERAS = 0x0002 | 0x0001 | 0x0040  # NOMOVE | NOSIZE | SHOWWINDOW

    try:
        if usuario.IsIconic(handle):
            usuario.ShowWindow(handle, 9)
        usuario.SetWindowPos(handle, HWND_TOPMOST, 0, 0, 0, 0, BANDERAS)
        usuario.SetWindowPos(handle, HWND_NOTOPMOST, 0, 0, 0, 0, BANDERAS)
        usuario.FlashWindow(handle, True)
        return True
    except (AttributeError, OSError):
        return False


def traer_al_frente(titulo: str = TITULO_VENTANA) -> bool:
    """La usa la instancia nueva: pide a la primera que se muestre."""
    if sys.platform != "win32":
        return False

    try:
        handle = _buscar_ventana(titulo)
        if handle is None:
            return False

        usuario = _usuario()
        kernel = _kernel()

        # Permiso para que el otro proceso tome el primer plano; sin esto
        # Windows le deniega la petición aunque sea su propia ventana.
        usuario.AllowSetForegroundWindow(_proceso_de(handle) or ASFW_ANY)

        evento = kernel.OpenEventW(EVENT_MODIFY_STATE, False, NOMBRE_EVENTO)
        if evento:
            avisado = bool(kernel.SetEvent(evento))
            kernel.CloseHandle(evento)
            if avisado:
                return True

        # La otra instancia no dejó el evento: se hace lo que se pueda desde aquí.
        return empujar(handle)
    except (AttributeError, OSError):
        return False


def avisar_de_que_ya_esta_abierta() -> None:
    """Último recurso: decirlo, si ni siquiera se pudo mostrar la ventana."""
    mensaje = (
        "Rolsumen ya está abierto.\n\n"
        "No se encontró su ventana para traerla al frente; búscala en la barra "
        "de tareas."
    )
    if sys.platform == "win32":
        try:
            MB_ICONINFORMATION = 0x40
            _usuario().MessageBoxW(None, mensaje, TITULO_VENTANA, MB_ICONINFORMATION)
            return
        except (AttributeError, OSError):
            pass
    print(mensaje, file=sys.stderr)
