param(
    [ValidateRange(1, 65535)][int]$Port = 8000,
    [switch]$SetupOnly,
    [switch]$NoBrowser,
    [switch]$Repair
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$previousLocation = Get-Location
try {
    Set-Location -LiteralPath $projectRoot
    $env:UV_UNMANAGED_INSTALL = Join-Path $projectRoot '.runtime\bin'
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $projectRoot '.runtime\python'
    $env:UV_CACHE_DIR = Join-Path $projectRoot '.runtime\cache'
    New-Item -ItemType Directory -Force -Path $env:UV_UNMANAGED_INSTALL | Out-Null
    $uvExecutable = Join-Path $env:UV_UNMANAGED_INSTALL 'uv.exe'
    if (-not (Test-Path -LiteralPath $uvExecutable)) {
        Write-Host 'Preparing Avenor runtime...'
        $installerPath = Join-Path $projectRoot '.runtime\install-uv.ps1'
        Invoke-WebRequest -Uri 'https://astral.sh/uv/install.ps1' -OutFile $installerPath -UseBasicParsing
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installerPath
        if ($LASTEXITCODE -ne 0) { throw 'Runtime installation failed.' }
    }
    $pythonChoice = '3.12'
    $pythonOptions = @('--managed-python')
    $existingPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $existingPython) {
        & $existingPython -c 'import sys; sys.exit(sys.version_info < (3, 12))'
        if ($LASTEXITCODE -eq 0) {
            $pythonChoice = $existingPython
            $pythonOptions = @()
        }
    }
    $bootstrapPath = Join-Path $projectRoot 'scripts\bootstrap.py'
    $launchArguments = @('run', '--no-project') + $pythonOptions + @('--python', $pythonChoice, 'python', $bootstrapPath, '--uv', $uvExecutable, '--port', "$Port")
    if ($SetupOnly) { $launchArguments += '--setup-only' }
    if ($NoBrowser) { $launchArguments += '--no-browser' }
    if ($Repair) { $launchArguments += '--repair' }
    & $uvExecutable @launchArguments
    exit $LASTEXITCODE
} catch {
    Write-Error "Avenor startup failed: $($_.Exception.Message)"
    exit 1
} finally {
    Set-Location -LiteralPath $previousLocation
}
