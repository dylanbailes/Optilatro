# Parallel Training Setup Guide

## Overview

Run multiple Balatro instances simultaneously for faster training.
With your Ryzen 9 7950X (16 cores), you can run 8-12 instances.

## Quick Start (Recommended: 4 instances first)

### Step 1: Create Game Copies

```powershell
# Run from balatro-rl directory
$source = "C:\Program Files (x86)\Steam\steamapps\common\Balatro"
$dest = "C:\BalatroParallel"

# Create parallel game folders
for ($i = 1; $i -le 4; $i++) {
    $target = "$dest\Balatro_$i"
    if (-not (Test-Path $target)) {
        Write-Host "Copying to $target..."
        Copy-Item -Path $source -Destination $target -Recurse
    }
}
```

### Step 2: Deploy Instance-Specific Mods

```powershell
cd C:\Users\Taggart\clawd\balatro-rl

# For each instance, create mod with unique INSTANCE_ID
for ($i = 1; $i -le 4; $i++) {
    $modContent = Get-Content "mod_v2\BalatroRL_parallel.lua" -Raw
    $modContent = $modContent -replace "local INSTANCE_ID = 1", "local INSTANCE_ID = $i"
    
    # Each game copy needs its own Mods folder in AppData
    # OR we put mod directly in game folder
    $modDir = "C:\BalatroParallel\Balatro_$i\Mods\BalatroRL"
    New-Item -ItemType Directory -Path $modDir -Force | Out-Null
    $modContent | Set-Content "$modDir\BalatroRL.lua" -Encoding UTF8
    
    # Copy metadata
    Copy-Item "$env:APPDATA\Balatro\Mods\BalatroRL\metadata.json" "$modDir\" -Force
    
    Write-Host "Deployed mod for instance $i"
}
```

### Step 3: Create State Directories

```powershell
for ($i = 1; $i -le 4; $i++) {
    $stateDir = "$env:APPDATA\Balatro\balatro_rl_$i"
    New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
    Write-Host "Created $stateDir"
}
```

### Step 4: Launch Instances

```powershell
# Kill any existing
Get-Process Balatro -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep 2

# Launch each copy
for ($i = 1; $i -le 4; $i++) {
    $exe = "C:\BalatroParallel\Balatro_$i\Balatro.exe"
    Start-Process $exe -WindowStyle Minimized
    Write-Host "Launched instance $i"
    Start-Sleep 2
}
```

### Step 5: Start Training

```powershell
cd C:\Users\Taggart\clawd\balatro-rl
python train_parallel.py --instances 4 --resume
```

---

## Files Created

| File | Purpose |
|------|---------|
| `balatro_rl/env_parallel.py` | Environment with instance_id support |
| `train_parallel.py` | SubprocVecEnv training script |
| `setup_parallel.ps1` | PowerShell setup helper |
| `mod_v2/BalatroRL_parallel.lua` | Instance-aware mod (already exists) |

---

## Troubleshooting

### Steam blocks multiple instances
- Close Steam completely before launching
- Or use game folder copies (recommended)

### Instances share state files
- Each instance MUST have unique INSTANCE_ID in mod
- Check that `balatro_rl_1/`, `balatro_rl_2/` etc. exist separately

### One instance crashes others
- Use separate game folder copies
- Each has isolated save data

### Training is slow despite multiple instances
- Check CPU usage - should be ~10-15% per instance
- Check that all instances are actually running
- Verify state.json files are updating for each instance

---

## Expected Performance

| Instances | Eps/hr | Time to 25k eps |
|-----------|--------|-----------------|
| 1 | 135 | 185 hrs (7.7 days) |
| 4 | 500 | 50 hrs (2.1 days) |
| 8 | 900 | 28 hrs (1.2 days) |
| 12 | 1200 | 21 hrs |

---

## Scaling Up

Once 4 instances work:
1. Create more game copies (Balatro_5, Balatro_6, etc.)
2. Deploy mods with higher INSTANCE_IDs
3. Increase `--instances` parameter
4. Monitor CPU usage - stop adding when >90% utilized
