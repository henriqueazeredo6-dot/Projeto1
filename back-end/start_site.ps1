$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $project '.venv\Scripts\python.exe'
$python = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { 'python' }
$logOut = Join-Path $project 'site.out.log'
$logErr = Join-Path $project 'site.err.log'

if ($python -ne 'python' -and -not (Test-Path -LiteralPath $python)) {
  Write-Error "Python nao encontrado em: $python"
  exit 1
}

$existing = Get-CimInstance Win32_Process | Where-Object {
  $_.CommandLine -like "*app.py*" -and $_.CommandLine -like "*$project*"
}
if ($existing) {
  Write-Output "Servidor ja esta em execucao (PID: $($existing.ProcessId -join ', '))."
  exit 0
}

$proc = Start-Process -FilePath $python -ArgumentList 'app.py' -WorkingDirectory $project -RedirectStandardOutput $logOut -RedirectStandardError $logErr -PassThru
$deadline = (Get-Date).AddSeconds(30)
$ok = $false

while ((Get-Date) -lt $deadline) {
  if ($proc.HasExited) {
    break
  }

  if (Test-NetConnection -ComputerName 127.0.0.1 -Port 5000 -InformationLevel Quiet) {
    $ok = $true
    break
  }

  Start-Sleep -Seconds 1
}

if ($ok) {
  Write-Output "Servidor iniciado com sucesso em http://127.0.0.1:5000 (PID: $($proc.Id))."
} elseif ($proc.HasExited) {
  Write-Output "Servidor encerrou antes de responder na porta 5000 (PID: $($proc.Id)). Verifique logs: $logErr"
} else {
  Write-Output "Servidor iniciou (PID: $($proc.Id)), mas porta 5000 nao respondeu em 30 segundos. Verifique logs: $logErr"
}
