# launch_parallel.ps1 - Launch N Balatro instances in a tiled grid
param(
    [int]$Instances = 8,
    [switch]$SkipMain  # Don't count main training instance
)

Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32 {
    [DllImport("user32.dll")]
    public static extern bool MoveWindow(IntPtr hWnd, int X, int Y, int nWidth, int nHeight, bool bRepaint);
    [DllImport("user32.dll")]
    public static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int X, int Y, int cx, int cy, uint uFlags);
    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    // SW_SHOWMINNOACTIVE = 7: minimize without stealing focus
    public const int SW_SHOWMINNOACTIVE = 7;
}
"@

# Screen dimensions
Add-Type -AssemblyName System.Windows.Forms
$screen = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$width = $screen.Width
$height = $screen.Height

# Grid layout (4x2 for 8 instances)
$cols = 4
$rows = 2
$tileW = [math]::Floor($width / $cols)
$tileH = [math]::Floor($height / $rows)

Write-Host "Launching $Instances Balatro instances..."
Write-Host "Grid: $cols x $rows, Tile: $tileW x $tileH"
Write-Host ""

$processes = @()

# Launch instances 2-N (instance 1 is main training)
for ($i = 2; $i -le $Instances; $i++) {
    $exe = "C:\BalatroParallel\Balatro_$i\Balatro.exe"
    if (-not (Test-Path $exe)) {
        Write-Host "  Skipping instance $i - not found"
        continue
    }
    
    Write-Host "  Launching instance $i..."
    $env:BALATRO_INSTANCE = "$i"
    $proc = Start-Process $exe -PassThru -WindowStyle Minimized
    $processes += @{id=$i; proc=$proc}
    $env:BALATRO_INSTANCE = $null

    # Wait briefly for window to appear, then suppress focus steal
    Start-Sleep -Milliseconds 800
    $hwnd = $proc.MainWindowHandle
    if ($hwnd -ne [IntPtr]::Zero) {
        [Win32]::ShowWindow($hwnd, [Win32]::SW_SHOWMINNOACTIVE) | Out-Null
    }
}

Write-Host ""
Write-Host "Waiting for windows to initialize..."
Start-Sleep 5

# Position windows in grid
Write-Host "Positioning windows..."
$index = 0
foreach ($p in $processes) {
    $proc = $p.proc
    $id = $p.id
    
    # Calculate grid position (0-indexed, skipping position 0 for main)
    $gridPos = $index
    $col = $gridPos % $cols
    $row = [math]::Floor($gridPos / $cols)
    
    $x = $col * $tileW
    $y = $row * $tileH
    
    # Get window handle
    $hwnd = $proc.MainWindowHandle
    if ($hwnd -ne [IntPtr]::Zero) {
        [Win32]::MoveWindow($hwnd, $x, $y, $tileW, $tileH, $true) | Out-Null
        Write-Host "  Instance $id -> ($col, $row) at ($x, $y)"
    } else {
        Write-Host "  Instance $id - no window handle yet"
    }
    
    $index++
}

Write-Host ""
Write-Host "Done. $($processes.Count) instances launched."
Write-Host ""
Write-Host "Running instances:"
Get-Process Balatro | Select-Object Id, MainWindowTitle
