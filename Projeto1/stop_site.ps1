$project = 'C:\Users\crisp\OneDrive\Documentos\Nova pasta\Confie_personal2\Projeto1\Projeto1'

$targets = Get-CimInstance Win32_Process | Where-Object {
  $_.CommandLine -like "*runpy.run_path('app.py'*" -and $_.CommandLine -like "*$project*"
}

if (-not $targets) {
  Write-Output 'Nenhum servidor em execucao encontrado.'
  exit 0
}

$targets | ForEach-Object {
  Stop-Process -Id $_.ProcessId -Force
  Write-Output "Servidor encerrado (PID: $($_.ProcessId))."
}
