# setup_parallel.ps1
# Setup and launch parallel Balatro instances for training
#
# Usage:
#   .\setup_parallel.ps1 -Instances 4 -Deploy   # Deploy mods only
#   .\setup_parallel.ps1 -Instances 4 -Launch   # Launch instances only
#   .\setup_parallel.ps1 -Instances 4           # Both deploy and launch

param(
    [int]$Instances = 4,
    [switch]$Deploy,
    [switch]$Launch,
    [switch]$Kill
)

$BalatroExe = "C:\Program Files (x86)\Steam\steamapps\common\Balatro\Balatro.exe"
$ModSource = ".\mod_v2\BalatroRL_parallel.lua"
$ModDest = "$env:APPDATA\Balatro\Mods\BalatroRL"
$StateBase = "$env:APPDATA\Balatro"

# Kill all Balatro instances
if ($Kill) {
    Write-Host "Killing all Balatro instances..."
    Get-Process Balatro -ErrorAction SilentlyContinue | Stop-Process -Force
    Write-Host "Done."
    exit
}

# If neither -Deploy nor -Launch specified, do both
if (-not $Deploy -and -not $Launch) {
    $Deploy = $true
    $Launch = $true
}

# Deploy mods
if ($Deploy) {
    Write-Host "Deploying mods for $Instances instances..."
    
    # Read template
    $template = Get-Content $ModSource -Raw -Encoding UTF8
    
    # For single mod folder approach: we'll use env var or config file
    # For now, create state directories and use instance 1 mod
    # The parallel training will need separate game folders for true parallelism
    
    for ($i = 1; $i -le $Instances; $i++) {
        # Create state directory for this instance
        $stateDir = "$StateBase\balatro_rl_$i"
        if (-not (Test-Path $stateDir)) {
            New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
        }
        Write-Host "  Instance $i : $stateDir"
    }
    
    # Deploy main mod (instance 1 for now)
    # For true parallel, we need separate game installations
    $modContent = $template -replace "local INSTANCE_ID = 1", "local INSTANCE_ID = 1"
    $modContent | Set-Content "$ModDest\BalatroRL.lua" -Encoding UTF8
    
    Write-Host ""
    Write-Host "NOTE: For true parallel training, you need separate Balatro installations."
    Write-Host "Options:"
    Write-Host "  1. Copy game folder multiple times"
    Write-Host "  2. Use Sandboxie for isolation"
    Write-Host "  3. Run single instance with faster speed (current setup)"
    Write-Host ""
}

# Launch instances
if ($Launch) {
    Write-Host "Launching $Instances Balatro instances..."
    Write-Host "(Note: Steam may only allow 1 instance without workarounds)"
    Write-Host ""
    
    # Kill existing instances first
    Get-Process Balatro -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 2
    
    # Try launching multiple instances
    for ($i = 1; $i -le $Instances; $i++) {
        Write-Host "  Starting instance $i..."
        
        # Launch directly from exe (bypassing Steam if possible)
        $proc = Start-Process -FilePath $BalatroExe -PassThru -WindowStyle Minimized
        
        if ($proc) {
            Write-Host "    PID: $($proc.Id)"
        }
        
        # Stagger launches
        Start-Sleep -Seconds 3
    }
    
    Write-Host ""
    Write-Host "Waiting for instances to initialize..."
    Start-Sleep -Seconds 10
    
    # Check what's running
    $running = Get-Process Balatro -ErrorAction SilentlyContinue
    Write-Host ""
    Write-Host "Running Balatro instances: $($running.Count)"
    
    if ($running.Count -lt $Instances) {
        Write-Host ""
        Write-Host "WARNING: Only $($running.Count) instance(s) running."
        Write-Host "Steam likely blocked additional instances."
        Write-Host ""
        Write-Host "To run multiple instances, try:"
        Write-Host "  1. Close Steam completely, then run Balatro.exe directly"
        Write-Host "  2. Use Sandboxie-Plus (free) to isolate instances"
        Write-Host "  3. Copy game folder to Balatro2/, Balatro3/, etc."
    }
}

Write-Host ""
Write-Host "Setup complete."
Write-Host ""
Write-Host "To start training:"
Write-Host "  python train_parallel.py --instances $Instances --resume"
