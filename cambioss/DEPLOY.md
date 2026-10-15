# Cómo correr y deployar (Windows / PowerShell)

## 0. Estructura
```
ambulatorio/
├── data/            ← CSV del hospital + perfiles.json + box.json (NO van a git)
├── lambda/          ← app.py (API), puntaje.py (reglas), explicar.py (Bedrock), local_server.py
├── front/           ← React + Vite
├── tests/           ← pytest
├── template.yaml    ← infraestructura AWS SAM
└── amplify.yml      ← build del front en Amplify
```

## 1. Probar TODO en local (sin AWS) — 5 min
Terminal 1 (raíz del proyecto):
```powershell
python scripts/generar_box.py data          # crea data/box.json (una vez)
pip install pytest; python -m pytest -q tests   # deben pasar 9 tests
$env:LOCAL="1"; $env:DATA_DIR="data"; python lambda/local_server.py
```
Terminal 2:
```powershell
cd front
"VITE_API_URL=http://localhost:3001" | Out-File -Encoding ascii .env.local
npm install
npm run dev
```
Abrir http://localhost:5173 → debe decir **"API conectada"**. Probar: elegir paciente → Explicar con IA → Simular evento → Confirmar → pestaña Uso de box.
(Sin `.env.local` el front corre en modo mock: solo lectura.)

## 2. Credenciales AWS (una persona, la que deploya)
Instalar **AWS CLI v2** y **AWS SAM CLI** (instaladores MSI oficiales de AWS). Luego:
```powershell
aws configure sso
#   SSO start URL:  https://d-906663fcf7.awsapps.com/start   (la del evento; confirmar con mentor)
#   SSO region:     sa-east-1
#   elegir cuenta y rol, región por defecto: sa-east-1, nombre de perfil: hack
$env:AWS_PROFILE="hack"
aws sts get-caller-identity     # debe mostrar la cuenta
```

## 3. Bedrock: elegir modelo
Consola AWS → **Amazon Bedrock** → **Model catalog / Model access** → confirmar qué modelo está habilitado en `sa-east-1`.
Copiar su **Model ID** (o el ID del *inference profile*). Si no hay modelos en sa-east-1, preguntar al mentor cuál región usar y pasarla como `BedrockRegion`.
Si no hay Bedrock aún, deployar con `ModelId` vacío: las explicaciones salen por plantilla y todo lo demás funciona.

## 4. Deploy del backend
```powershell
sam build
sam deploy --guided
#   Stack name: ambulatorio-hlf     Region: sa-east-1
#   Parameter ModelId: <model id de Bedrock o vacío>
#   Parameter BedrockRegion: <vacío o región>
#   Confirm changes: y   Allow SAM CLI IAM role creation: y
#   ApiFunction has no authentication. Is this okay?: y
#   Save arguments to samconfig.toml: y
```
Al final muestra **Outputs**: `ApiUrl` y `BucketName`. Subir los datos:
```powershell
aws s3 cp data/perfiles.json s3://<BucketName>/perfiles.json
aws s3 cp data/box.json      s3://<BucketName>/box.json
curl.exe "<ApiUrl>/health"     # {"ok": true, "pacientes": 500}
```
Para redeployar cambios de la Lambda: `sam build; sam deploy`.

## 5. Deploy del front (Amplify Hosting)
1. Subir el repo a GitHub (privado). Verificar que `data/` NO se subió.
2. Consola AWS → **AWS Amplify** → *Create new app* → GitHub → repo → rama `main`.
3. Marcar **"My app is a monorepo"** → carpeta `front` (usa `amplify.yml` de la raíz).
4. En *Advanced settings* → variable de entorno `VITE_API_URL` = `<ApiUrl>` (sin `/` final).
5. Deploy. Cada `git push` a `main` redeploya solo.

## 6. Si algo falla
| Síntoma | Causa probable |
|---|---|
| Front dice "Error: Failed to fetch" | `VITE_API_URL` mal escrita o API caída (`curl /health`) |
| API responde `{"error": "...NoSuchKey..."}` | Falta subir perfiles.json al bucket |
| Explicación dice "Fuente: plantilla" | `ModelId` vacío, sin acceso al modelo o región equivocada (ver logs en CloudWatch) |
| `sam deploy` AccessDenied | Rol SSO sin permisos: pedir al mentor |
