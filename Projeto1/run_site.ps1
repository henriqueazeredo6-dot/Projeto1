$project = 'C:\Users\crisp\OneDrive\Documentos\Nova pasta\Confie_personal2\Projeto1\Projeto1'
$python = 'C:\Program Files\LibreOffice\program\python.exe'

Set-Location $project
$env:PYTHONPATH = (Join-Path $project '.deps')

& $python app.py
