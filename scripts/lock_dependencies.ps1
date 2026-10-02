param([string]$PythonVersion = '3.11', [string]$Platform = 'windows')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectRoot
try {
    uv pip compile requirements.in --python-version $PythonVersion --python-platform $Platform --only-binary ':all:' --generate-hashes --output-file requirements.txt --no-header
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao resolver dependências do aplicativo.' }
    uv pip compile requirements-dev.in --constraint requirements.txt --python-version $PythonVersion --python-platform $Platform --only-binary ':all:' --generate-hashes --output-file requirements-dev.txt --no-header
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao resolver dependências de desenvolvimento.' }
} finally {
    Pop-Location
}
