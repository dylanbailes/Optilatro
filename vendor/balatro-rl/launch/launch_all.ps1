# launch_all.ps1 - Launch all 8 Balatro instances without stealing focus
# Uses SW_SHOWMINNOACTIVE so windows appear minimized and never yank your screen

param([int]$Instances = 8)

Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32NoFocus {
    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    public const int SW_SHOWMINNOACTIVE = 7;
}
"@

$exes = @{
    1 = "C:\Program Files (x86)\Steam\steamapps\common\Balatro\Balatro.exe"
}
for ($i = 2; $i -le 8; $i++) { $exes[$i] = "C:\BalatroParallel\Balatro_$i\Balatro.exe" }

$procs = @()
foreach ($i in 1..$Instances) {
    $env:BALATRO_INSTANCE = "$i"
    $proc = Start-Process $exes[$i] -PassThru -WindowStyle Minimized
    $env:BALATRO_INSTANCE = $null
    $procs += @{id=$i; proc=$proc}
    Start-Sleep -Milliseconds 800

    # Immediately suppress focus steal
    $hwnd = $proc.MainWindowHandle
    if ($hwnd -ne [IntPtr]::Zero) {
        [Win32NoFocus]::ShowWindow($hwnd, [Win32NoFocus]::SW_SHOWMINNOACTIVE) | Out-Null
    }
    Write-Host "Instance $i launched (no-focus)"
}

Write-Host "Waiting for sockets..."
Start-Sleep 20
$up = @(1..8 | Where-Object { netstat -ano | Select-String ":$(5000+$_) " | Select-String "LISTENING" }).Count
Write-Host "$up/$Instances ports listening"
