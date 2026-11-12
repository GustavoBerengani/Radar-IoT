$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    py -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Instale o Python 3.10 ou superior para Windows.' }
}

& $python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Falha ao instalar as dependencias.' }

Write-Host 'Portas seriais detectadas:'
& $python -m serial.tools.list_ports -v
Write-Host 'Feche o Monitor Serial da Arduino IDE antes de continuar.'
$port = (Read-Host 'Digite a porta do Arduino (exemplo COM3)').Trim()
if ($port -notmatch '^COM[1-9][0-9]*$') { throw 'Porta COM invalida.' }

$api = (Read-Host 'Cole a URL HTTPS da API, sem /api').Trim().TrimEnd('/')
$uri = $null
if (-not [Uri]::TryCreate($api, [UriKind]::Absolute, [ref]$uri) -or
    $uri.Scheme -ne 'https' -or $uri.AbsolutePath -ne '/' -or
    $uri.Query -or $uri.Fragment -or $uri.UserInfo) {
    throw 'Informe apenas a origem HTTPS da API.'
}

Write-Host 'Verificando a API. Uma instancia gratuita pode demorar para iniciar.'
Invoke-RestMethod -Uri "$api/api/status" -TimeoutSec 120 | Out-Null
$secret = Read-Host 'Digite a chave RADAR_API_KEY do Render' -AsSecureString
if ($secret.Length -eq 0) { throw 'A chave da API e obrigatoria.' }

$oldKey = $env:RADAR_API_KEY
try {
    $env:RADAR_API_KEY = [System.Net.NetworkCredential]::new('', $secret).Password
    & $python coletor.py --porta $port --baud 115200 --api $api --fila fila_apresentacao.sqlite3
    if ($LASTEXITCODE -ne 0) { throw 'O coletor encerrou com erro.' }
} finally {
    $env:RADAR_API_KEY = $oldKey
    $secret.Dispose()
}
