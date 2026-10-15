# Publica todo en AWS: API (Lambda + API Gateway + DynamoDB + S3) con CloudFormation y la página en Amplify.
# Uso, desde la raíz del repo (perfil AWS "hack" con credenciales vigentes):
#   powershell -ExecutionPolicy Bypass -File scripts\deploy_aws.ps1            # backend + datos + página
#   powershell -ExecutionPolicy Bypass -File scripts\deploy_aws.ps1 -SoloFront
param([switch]$SoloFront, [string]$Perfil = "hack", [string]$Region = "us-east-1",
      [string]$Modelo = "us.anthropic.claude-sonnet-5", [string]$Stack = "ambulatorio-hlf", [string]$AppAmplify = "")
$ErrorActionPreference = "Stop"
$aws = "C:\Program Files\Amazon\AWSCLIV2\aws.exe"
$raiz = Split-Path -Parent $PSScriptRoot
$cuenta = & $aws sts get-caller-identity --profile $Perfil --query Account --output text
if (-not $cuenta) { throw "Credenciales del perfil '$Perfil' vencidas: renuévalas en el portal del evento." }
$art = "ambulatorio-hlf-artefactos-$cuenta"

if (-not $SoloFront) {
    # 1) Paquete limpio de la Lambda: código + Pydantic para Linux ARM (Lambda arm64, Python 3.12)
    # carpeta nueva en cada publicación (Windows a veces bloquea borrar la anterior)
    $b = Join-Path $env:TEMP ("hlf_build_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
    New-Item -ItemType Directory -Force "$b\lambda_pkg" | Out-Null
    Get-ChildItem "$raiz\lambda\*.py" | Where-Object Name -ne "local_server.py" | Copy-Item -Destination "$b\lambda_pkg\"
    python -m pip install -q -r "$raiz\lambda\requirements.txt" --platform manylinux2014_aarch64 --python-version 3.12 `
        --implementation cp --only-binary=:all: --target "$b\lambda_pkg"
    [IO.File]::WriteAllText("$b\template.yaml", (Get-Content "$raiz\template.yaml" -Raw).Replace("CodeUri: lambda/", "CodeUri: lambda_pkg/"),
        [Text.UTF8Encoding]::new($false))
    & $aws s3 mb "s3://$art" --profile $Perfil --region $Region 2>$null | Out-Null
    & $aws cloudformation package --template-file "$b\template.yaml" --s3-bucket $art --output-template-file "$b\empaquetado.yaml" --profile $Perfil --region $Region | Out-Null
    & $aws cloudformation deploy --template-file "$b\empaquetado.yaml" --stack-name $Stack --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND `
        --parameter-overrides ModelId=$Modelo BedrockRegion=$Region --profile $Perfil --region $Region
}
$api = & $aws cloudformation describe-stacks --stack-name $Stack --profile $Perfil --region $Region --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text
$bucket = & $aws cloudformation describe-stacks --stack-name $Stack --profile $Perfil --region $Region --query "Stacks[0].Outputs[?OutputKey=='BucketName'].OutputValue" --output text
if (-not $SoloFront) {
    # 2) Datos (no van a git): perfiles.json y box.json al bucket privado
    & $aws s3 cp "$raiz\data\perfiles.json" "s3://$bucket/perfiles.json" --profile $Perfil --region $Region | Out-Null
    & $aws s3 cp "$raiz\data\box.json" "s3://$bucket/box.json" --profile $Perfil --region $Region | Out-Null
    $salud = curl.exe -s "$api/health"
    if ($salud -notmatch '"ok": true') { throw "La API no responde bien: $salud" }
    Write-Host "API OK: $api" -ForegroundColor Green
}

# 3) Página: build apuntando a la API de AWS y publicación en Amplify (sin Git)
$env:VITE_API_URL = $api
$dist = Join-Path $env:TEMP "hlf_dist"; if (Test-Path $dist) { Remove-Item $dist -Recurse -Force }
Push-Location "$raiz\front"; npx vite build --outDir $dist | Out-Null; Pop-Location
$zip = Join-Path $env:TEMP "hlf_dist.zip"
python -X utf8 -c "import zipfile,os,sys; s,z=sys.argv[1],zipfile.ZipFile(sys.argv[2],'w',zipfile.ZIP_DEFLATED); [z.write(os.path.join(r,f),os.path.relpath(os.path.join(r,f),s).replace(os.sep,'/')) for r,_,fs in os.walk(s) for f in fs]; z.close()" $dist $zip
if (-not $AppAmplify) {
    $AppAmplify = & $aws amplify list-apps --profile $Perfil --region $Region --query "apps[?name=='ambulatorio-dinamico-hlf'].appId | [0]" --output text
}
if (-not $AppAmplify -or $AppAmplify -eq "None") {
    $AppAmplify = & $aws amplify create-app --name ambulatorio-dinamico-hlf --platform WEB --profile $Perfil --region $Region --query "app.appId" --output text
    & $aws amplify create-branch --app-id $AppAmplify --branch-name main --stage PRODUCTION --profile $Perfil --region $Region | Out-Null
}
$dep = & $aws amplify create-deployment --app-id $AppAmplify --branch-name main --profile $Perfil --region $Region --output json | ConvertFrom-Json
curl.exe -s -o NUL -X PUT -H "Content-Type: application/zip" --data-binary "@$zip" $dep.zipUploadUrl
& $aws amplify start-deployment --app-id $AppAmplify --branch-name main --job-id $dep.jobId --profile $Perfil --region $Region | Out-Null
for ($i = 0; $i -lt 30; $i++) {
    $s = & $aws amplify get-job --app-id $AppAmplify --branch-name main --job-id $dep.jobId --profile $Perfil --region $Region --query "job.summary.status" --output text
    if ($s -in "SUCCEED", "FAILED", "CANCELLED") { break }; Start-Sleep 5
}
Write-Host "Página ($s): https://main.$AppAmplify.amplifyapp.com" -ForegroundColor Green
