$project = Split-Path -Parent $MyInvocation.MyCommand.Path

$targets = Get-CimInstance Win32_Process | Where-Object {
  $_.CommandLine -like "*app.py*" -and $_.CommandLine -like "*$project*"
}

if (-not $targets) {
  Write-Output 'Nenhum servidor em execucao encontrado.'
  exit 0
}

$targets | ForEach-Object {
  Stop-Process -Id $_.ProcessId -Force
  Write-Output "Servidor encerrado (PID: $($_.ProcessId))."
}
