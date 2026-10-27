# Creates Start-menu (and optionally Desktop) shortcuts for Luminary.
# The shortcut carries the same AppUserModelID the app sets on its window, so the
# running window and a pinned taskbar icon are one and the same.
param([switch]$Desktop)

$ErrorActionPreference = 'Stop'
$AppDir  = Split-Path -Parent $PSScriptRoot
$Pythonw = Join-Path $AppDir '.venv\Scripts\pythonw.exe'
$Main    = Join-Path $AppDir 'main.py'
$Icon    = Join-Path $AppDir 'assets\luminary.ico'
$Aumid   = 'Luminary.MediaLibrary'

if (-not (Test-Path $Pythonw)) { throw "Missing $Pythonw - run run_luminary.bat once first." }
if (-not (Test-Path $Icon)) {
    & (Join-Path $AppDir '.venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'make_icon.py') $Icon | Out-Null
}

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class LuminaryAumid {
    [StructLayout(LayoutKind.Sequential, Pack = 4)]
    public struct PROPERTYKEY { public Guid fmtid; public uint pid; }
    [StructLayout(LayoutKind.Explicit)]
    public struct PROPVARIANT { [FieldOffset(0)] public ushort vt; [FieldOffset(8)] public IntPtr p; [FieldOffset(16)] public IntPtr p2; }
    [ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown), Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")]
    interface IPropertyStore {
        void GetCount(out uint c);
        void GetAt(uint i, out PROPERTYKEY k);
        void GetValue(ref PROPERTYKEY k, out PROPVARIANT v);
        void SetValue(ref PROPERTYKEY k, ref PROPVARIANT v);
        void Commit();
    }
    [DllImport("shell32.dll", CharSet = CharSet.Unicode, PreserveSig = false)]
    static extern void SHGetPropertyStoreFromParsingName(string path, IntPtr pbc, int flags, ref Guid iid,
        [MarshalAs(UnmanagedType.Interface)] out IPropertyStore store);
    public static void Set(string lnk, string id) {
        Guid iid = new Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99");
        IPropertyStore s;
        SHGetPropertyStoreFromParsingName(lnk, IntPtr.Zero, 2, ref iid, out s);
        PROPERTYKEY key = new PROPERTYKEY { fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), pid = 5 };
        PROPVARIANT pv = new PROPVARIANT { vt = 31, p = Marshal.StringToCoTaskMemUni(id) };
        try { s.SetValue(ref key, ref pv); s.Commit(); }
        finally { Marshal.FreeCoTaskMem(pv.p); Marshal.ReleaseComObject(s); }
    }
}
"@

function New-LuminaryShortcut([string]$Path) {
    $ws = New-Object -ComObject WScript.Shell
    $sc = $ws.CreateShortcut($Path)
    $sc.TargetPath = $Pythonw
    $sc.Arguments = "`"$Main`""
    $sc.WorkingDirectory = $AppDir
    $sc.IconLocation = "$Icon,0"
    $sc.Description = 'Luminary - your local movie, TV and anime library'
    $sc.Save()
    [LuminaryAumid]::Set($Path, $Aumid)
    Write-Output "Created $Path"
}

$startMenu = Join-Path ([Environment]::GetFolderPath('Programs')) 'Luminary.lnk'
New-LuminaryShortcut $startMenu
if ($Desktop) {
    New-LuminaryShortcut (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Luminary.lnk')
}
