# Local validation for Windows PowerShell. Run from the repository root:
#   powershell -ExecutionPolicy Bypass -File scripts/validate.ps1
# Every external command is wrapped in Invoke-Checked, which tests $LASTEXITCODE explicitly.
# ($ErrorActionPreference = 'Stop' alone does NOT stop on a failing native command.)
$ErrorActionPreference = 'Stop'

function Invoke-Checked {
    param([string]$Description, [scriptblock]$Command)
    Write-Host "==> $Description"
    $global:LASTEXITCODE = 0
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'   # native stderr text must not abort before we test the exit code
    try { & $Command 2>&1 | Out-Host } finally { $ErrorActionPreference = $previous }
    if ($LASTEXITCODE -ne 0) { throw "FAILED (exit code $LASTEXITCODE): $Description" }
}

Invoke-Checked "Python 3.12 available" { python -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)" }
if (-not (Test-Path .venv)) { Invoke-Checked "Create virtual environment" { python -m venv .venv } }
$py = Join-Path $PWD ".venv\Scripts\python.exe"
Invoke-Checked "Upgrade pip" { & $py -m pip install --upgrade pip }
Invoke-Checked "Install project (dev extras)" { & $py -m pip install -e ".[dev]" }
Invoke-Checked "Import package" { & $py -c "import tmc_access; print(tmc_access.__version__)" }
Invoke-Checked "Ruff lint" { & $py -m ruff check . }
Invoke-Checked "Ruff format check" { & $py -m ruff format --check . }
Invoke-Checked "Workflow validation" { & $py scripts/check_workflow.py }
Invoke-Checked "Secret scan" { & $py scripts/scan_secrets.py }
Invoke-Checked "Tests" { & $py -m pytest }
Write-Host "ALL VALIDATION STEPS PASSED (skipped tests are PENDING functionality, not successes)."
