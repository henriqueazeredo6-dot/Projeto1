$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $project '.venv\Scripts\python.exe'
$script = Join-Path $project 'scripts\check_portability.py'

if (Test-Path -LiteralPath $venvPython) {
  $python = $venvPython
} else {
  $python = 'python'
}

Set-Location $project
& $python $script
