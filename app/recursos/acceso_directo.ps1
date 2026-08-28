# Crea el acceso directo de Rolsumen.
#
# Aparte de las propiedades normales (destino, icono, carpeta de trabajo), le
# escribe la propiedad System.AppUserModel.ID. Sin ella Windows identifica la
# ventana por su ejecutable —pythonw.exe— y la barra de tareas muestra el icono
# de Python por mucho que la ventana tenga el suyo. Esa propiedad no se puede
# poner con WScript.Shell, hace falta IPropertyStore.

param(
  [Parameter(Mandatory = $true)][string]$Destino,
  [Parameter(Mandatory = $true)][string]$Interprete,
  [Parameter(Mandatory = $true)][string]$Argumentos,
  [Parameter(Mandatory = $true)][string]$Carpeta,
  [Parameter(Mandatory = $true)][string]$Icono,
  [Parameter(Mandatory = $true)][string]$Id,
  [string]$Descripcion = "Cronicas automaticas de partidas grabadas en Discord"
)

$ErrorActionPreference = "Stop"

$enlace = (New-Object -ComObject WScript.Shell).CreateShortcut($Destino)
$enlace.TargetPath = $Interprete
$enlace.Arguments = $Argumentos
$enlace.WorkingDirectory = $Carpeta
$enlace.IconLocation = $Icono
$enlace.Description = $Descripcion
$enlace.Save()

Add-Type @'
using System;
using System.Runtime.InteropServices;

[StructLayout(LayoutKind.Sequential, Pack = 4)]
public struct PROPERTYKEY { public Guid fmtid; public uint pid; }

[StructLayout(LayoutKind.Sequential)]
public struct PROPVARIANT {
  public ushort vt; public ushort r1; public ushort r2; public ushort r3;
  public IntPtr p; public int p2;
}

[ComImport, Guid("00021401-0000-0000-C000-000000000046")]
public class ShellLink { }

[ComImport, Guid("0000010b-0000-0000-C000-000000000046"),
 InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IPersistFile {
  void GetClassID(out Guid pClassID);
  [PreserveSig] int IsDirty();
  void Load([MarshalAs(UnmanagedType.LPWStr)] string f, uint mode);
  void Save([MarshalAs(UnmanagedType.LPWStr)] string f, [MarshalAs(UnmanagedType.Bool)] bool remember);
  void SaveCompleted([MarshalAs(UnmanagedType.LPWStr)] string f);
  void GetCurFile([MarshalAs(UnmanagedType.LPWStr)] out string f);
}

[ComImport, Guid("886d8eeb-8cf2-4446-8d02-cdba1dbdcf99"),
 InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IPropertyStore {
  void GetCount(out uint c);
  void GetAt(uint i, out PROPERTYKEY k);
  void GetValue(ref PROPERTYKEY k, out PROPVARIANT v);
  void SetValue(ref PROPERTYKEY k, ref PROPVARIANT v);
  void Commit();
}

public static class Aumid {
  static PROPERTYKEY Clave() {
    return new PROPERTYKEY {
      fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), pid = 5 };
  }
  public static void Poner(string lnk, string id) {
    var enlace = new ShellLink();
    ((IPersistFile)enlace).Load(lnk, 2 /* STGM_READWRITE */);
    var almacen = (IPropertyStore)enlace;
    var clave = Clave();
    var valor = new PROPVARIANT { vt = 31 /* VT_LPWSTR */,
                                  p = Marshal.StringToCoTaskMemUni(id) };
    almacen.SetValue(ref clave, ref valor);
    almacen.Commit();
    ((IPersistFile)enlace).Save(lnk, true);
    Marshal.FreeCoTaskMem(valor.p);
  }
  public static string Leer(string lnk) {
    var enlace = new ShellLink();
    ((IPersistFile)enlace).Load(lnk, 0);
    var almacen = (IPropertyStore)enlace;
    var clave = Clave();
    PROPVARIANT v; almacen.GetValue(ref clave, out v);
    return v.vt == 31 ? Marshal.PtrToStringUni(v.p) : "";
  }
}
'@

[Aumid]::Poner($Destino, $Id)

# Se relee para no dar por hecho que se guardó.
$puesto = [Aumid]::Leer($Destino)
if ($puesto -ne $Id) {
  Write-Error "El identificador no se guardó (se leyó '$puesto')."
  exit 1
}
Write-Output "OK $puesto"
