$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $project '.venv\Scripts\python.exe'

if (Test-Path -LiteralPath $venvPython) {
  $python = $venvPython
} else {
  $python = 'python'
}

Set-Location $project
& $python app.py
