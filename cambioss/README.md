# Ambulatorio Dinámico HLF

**AWS Breaking Barriers Chile 2026 · Desafío Hospital Clínico Dra. Eloísa Díaz Inzunza (La Florida)**

> "La lista de espera es una foto; la salud de las personas, una película."

Lista de espera de consultas de especialidad que **se reprioriza sola cuando el paciente empeora** (urgencias,
hospitalizaciones, exámenes alterados) usando **solo reglas oficiales**: tabla de priorización SSMSO 2025 del HLF,
criterios MINSAL Ord. 536/2025 y garantías GES (LACE solo como desempate experimental). Las fotos de informes se leen
con Amazon Textract + reglas + Pydantic; Bedrock solo redacta. **El equipo clínico decide** y todo queda trazado.

En el dataset del hospital (13-10-2026): los 17 pacientes con descompensación grave estaban en la **posición mediana
N° 171** de la lista congelada (16 fuera de los primeros 50); con este sistema quedan en la **mediana N° 9** y con
evaluación médica exigida en 72 h.

## Estructura
```
ambulatorio-dinamico/
├── lambda/                API (una Lambda Python; única dependencia: pydantic)
│   ├── app.py             rutas HTTP, revisiones, contactos, box, KPIs, importación
│   ├── puntaje.py         motor de priorización (reglas oficiales + LACE)
│   ├── informe.py         lectura de informes / fotos (Bedrock) con negación
│   ├── explicar.py        resumen para el equipo (Bedrock o plantilla)
│   ├── importar.py        Excel/CSV → formato del sistema (sin librerías)
│   └── local_server.py    corre la API en localhost:3001 sin AWS
├── front/                 React + Vite + Tailwind (pantallas Hoy, Lista, Indicadores, Cargar datos, Criterios)
│   └── src/               App.jsx (interfaz), api.js (llamadas), mock.json (demo sin API)
├── tests/test_api.py      30 pruebas de punta a punta
├── scripts/               generar_box.py (agenda de box) · generar_mock.py (datos de demo del front)
├── docs/                  criterios_oficiales.md (todas las fuentes) · arquitectura.md · prompts_bedrock.md
├── data/                  perfiles.json, box.json y CSV (NO van a git)
├── template.yaml          infraestructura AWS (SAM): Lambda, API Gateway, S3, DynamoDB, permisos Bedrock
├── amplify.yml            build del front en AWS Amplify
├── contrato.md            contrato de la API
└── DEPLOY.md              cómo correr en local y deployar
```

## Probar en local
```powershell
python scripts/generar_box.py data
python -m pytest -q tests
$env:LOCAL="1"; $env:DATA_DIR="data"; python lambda/local_server.py      # API en localhost:3001
cd front; npm install; npm run dev                                         # app en localhost:5173
```
(con `front/.env.local` → `VITE_API_URL=http://localhost:3001`; sin él, el front usa `mock.json`)

## KPIs del hospital
| KPI | Cómo se cubre |
|---|---|
| Reevaluación < 72 h tras un evento | Cada evento recalcula la lista al registrarse (~0,1 s) |
| Cobertura 100% con criterio común | Toda la lista con la misma tabla oficial y el mismo orden MINSAL |
| Concordancia κ ≥ 0,70 | Kappa calculado en vivo entre la propuesta y las revisiones del especialista (pestaña Indicadores) |

Datos: dataset sintético entregado por el HLF (500 pacientes, sin RUT ni nombres reales).
