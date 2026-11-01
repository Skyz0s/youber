# Lanzador desprendido del lote nocturno de If I Let Go.
# Lo arranca el cron de las 22:00 (hora de Madrid); sobrevive al cierre de la
# sesion del agente y escribe su propio log con marca de tiempo.
$ErrorActionPreference = 'Stop'
$repo = 'C:\Users\bypau\.openclaw\workspace\youber\projects\barf'
$clips = 'C:\Users\bypau\Videos\youber\IfILetGo\If_I_Let_Go\clips'
$lock = Join-Path $clips 'BATCH_RUNNING'

if (Test-Path $lock) {
    "[{0}] ya hay un lote en marcha (BATCH_RUNNING); no lanzo nada" -f (Get-Date -Format 'HH:mm:ss')
    exit 0
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmm'
$out = Join-Path $repo ("scratch\night_letgo_{0}.out.log" -f $stamp)
$err = Join-Path $repo ("scratch\night_letgo_{0}.err.log" -f $stamp)
$py = Join-Path $repo '.venv\Scripts\python.exe'

Start-Process -FilePath $py `
    -ArgumentList 'scratch\night_letgo.py', '--until', '09:00' `
    -WorkingDirectory $repo `
    -RedirectStandardOutput $out `
    -RedirectStandardError $err `
    -WindowStyle Hidden

"[{0}] lanzado: out={1} err={2}" -f (Get-Date -Format 'HH:mm:ss'), $out, $err
