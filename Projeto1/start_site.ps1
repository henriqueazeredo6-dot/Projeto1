$project = 'C:\Users\crisp\OneDrive\Documentos\Nova pasta\Confie_personal2\Projeto1\Projeto1'
$python = 'C:\Program Files\LibreOffice\program\python.exe'
$logOut = Join-Path $project 'site.out.log'
$logErr = Join-Path $project 'site.err.log'

if (-not (Test-Path -LiteralPath $python)) {
  Write-Error "Python nao encontrado em: $python"
  exit 1
}

# Evita subir duas instancias
$existing = Get-CimInstance Win32_Process | Where-Object {
  $_.CommandLine -like "*runpy.run_path('app.py'*" -and $_.CommandLine -like "*$project*"
}
if ($existing) {
  Write-Output "Servidor ja esta em execucao (PID: $($existing.ProcessId -join ', '))."
  exit 0
}

$arg = "import sys,runpy; sys.path.insert(0, r'$project\\.deps'); runpy.run_path('app.py', run_name='__main__')"
$proc = Start-Process -FilePath $python -ArgumentList '-c', $arg -WorkingDirectory $project -RedirectStandardOutput $logOut -RedirectStandardError $logErr -PassThru
Start-Sleep -Seconds 2

$ok = Test-NetConnection -ComputerName 127.0.0.1 -Port 5000 -InformationLevel Quiet
if ($ok) {
  Write-Output "Servidor iniciado com sucesso em http://127.0.0.1:5000 (PID: $($proc.Id))."
} else {
  Write-Output "Servidor iniciou (PID: $($proc.Id)), mas porta 5000 ainda nao respondeu. Verifique logs: $logErr"
}
