$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$env:UV_CACHE_DIR = Join-Path $projectRoot '.cache\uv'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $projectRoot '.python'
$env:UV_PYTHON_BIN_DIR = Join-Path $projectRoot '.python\bin'
$env:MPLCONFIGDIR = Join-Path $projectRoot '.cache\matplotlib'
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
$uvCommand = Get-Command uv -ErrorAction SilentlyContinue
$uvExe = if ($uvCommand) { $uvCommand.Source } else { Join-Path $env:USERPROFILE '.local\bin\uv.exe' }
if (-not (Test-Path -LiteralPath $uvExe)) {
    throw 'O instalador requer uv. Instale-o de https://docs.astral.sh/uv/getting-started/installation/ e tente novamente. A instalacao pronta nao precisa de uv para abrir.'
}
if (-not (Test-Path -LiteralPath $pythonExe)) {
    & $uvExe python install 3.12.13 --no-bin
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao obter Python 3.12.13.' }
    & $uvExe venv --python 3.12.13 (Join-Path $projectRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao criar ambiente virtual.' }
}
& $uvExe pip sync --python $pythonExe (Join-Path $projectRoot 'requirements.lock.txt')
if ($LASTEXITCODE -ne 0) { throw 'Falha ao instalar dependencias. Verifique a internet.' }
$modelDir = Join-Path $projectRoot 'models'
New-Item -ItemType Directory -Path $modelDir -Force | Out-Null
$models = @(
    @{
        Name = 'hand_landmarker'
        Sha256 = 'fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1'
    },
    @{
        Name = 'face_landmarker'
        Sha256 = '64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff'
    }
)
foreach ($model in $models) {
    $modelPath = Join-Path $modelDir ($model.Name + '.task')
    if (-not (Test-Path -LiteralPath $modelPath) -or (Get-FileHash -LiteralPath $modelPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $model.Sha256) {
        $temporaryModel = Join-Path $modelDir ($model.Name + '.download')
        $modelUrl = 'https://storage.googleapis.com/mediapipe-models/{0}/{0}/float16/1/{0}.task' -f $model.Name
        Invoke-WebRequest -UseBasicParsing -Uri $modelUrl -OutFile $temporaryModel
        if ((Get-FileHash -LiteralPath $temporaryModel -Algorithm SHA256).Hash.ToLowerInvariant() -ne $model.Sha256) {
            throw ('O modelo {0} nao passou na verificacao SHA256.' -f $model.Name)
        }
        Move-Item -LiteralPath $temporaryModel -Destination $modelPath -Force
    }
}
& $pythonExe -c "import tkinter, cv2, mediapipe, PIL; print('Bibliotecas carregadas com sucesso.')"
if ($LASTEXITCODE -ne 0) { throw 'Falha ao carregar bibliotecas. Consulte LEIA-ME.md.' }
Write-Host 'Instalacao conferida. Seus desenhos foram preservados.'
