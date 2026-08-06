# swap_version.ps1 — Switch between Balatro RL mod/nav versions
# Usage: .\swap_version.ps1 lua_nav   (Lua handles blind select, best for training)
#        .\swap_version.ps1 no_nav    (Python mouse handles everything)

param([Parameter(Mandatory)][ValidateSet("lua_nav","no_nav")] [string]$Mode)

$MOD_DST = "$env:APPDATA\Balatro\Mods\BalatroRL\BalatroRL.lua"
$MOD_SRC = "$PSScriptRoot\versions\BalatroRL_$Mode.lua"

Copy-Item $MOD_SRC $MOD_DST -Force
Write-Host "Mod switched to: $Mode"
Write-Host "Restart Balatro to apply."
