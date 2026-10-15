# Contexto del proyecto — Ambulatorio Dinámico HLF

> Pega este archivo al inicio de una conversación con Claude (o déjalo en la raíz del repo) para que entienda el proyecto
> sin tener que explorarlo desde cero. Estado al 15-10-2026 (tarde).

## 1. Qué es
Proyecto para la hackatón **AWS Breaking Barriers Chile 2026** (14 al 16 de octubre, FCFM UChile). Responde al desafío del
**Hospital Clínico Dra. Eloísa Díaz Inzunza (La Florida, HLF)**: la **priorización clínica evolutiva** de la lista de espera
de consultas de especialidad.

- **Problema:** la prioridad se asigna una vez, al leer la interconsulta (SIC), y queda congelada aunque el paciente empeore
  mientras espera (urgencias, hospitalizaciones, exámenes alterados).
- **Frase del hospital:** "La lista de espera es una foto; la salud de las personas, una película."
- **Qué hace la app:**
  - muestra la lista de espera ordenada con criterios oficiales, en una vista simple (como planilla) y una detallada;
  - recalcula la lista con cada evento clínico y explica por qué cada paciente está en su lugar;
  - avisa qué descompensaciones graves necesitan que el especialista **revise su prioridad** (plazo de 72 h);
  - permite gestionar cada caso: estado, responsable, próxima acción, seguimiento y motivo del pendiente;
  - permite mover a un paciente a mano en la lista, siempre con un motivo explicado;
  - exporta todo a Excel (.xlsx) y mide indicadores de resultado.
- **Usuarios:** quien gestiona la lista (enfermería, administrativos, coordinación), especialistas (revisión de prioridad)
  y jefatura (indicadores).

### Lo que pidió el hospital (15-10, conversación con una persona del HLF)
- **El objetivo principal es la lista de espera y sus prioridades.** Por eso la página principal es la lista.
- **No quieren gestión de box.** Las pantallas "Gestión de box" y "Tengo horas libres" se sacaron del menú (el código
  sigue en `App.jsx` y la API, por si se retoman).
- **No quieren IA predictiva.** Se evaluó y se descartó. Bedrock solo redacta el "Resumen para el equipo" (eso sí lo aceptan).
- **La lista se debe poder operar a mano**, siempre con un motivo previo y explicado.
- **Dos vistas:** una simple, que cualquiera entienda sin capacitación, y otra con toda la información.
- **Todo se debe poder exportar a Excel.**

## 1b. La solución, explicada en simple
**Antes (lista congelada):** al paciente le asignan una prioridad cuando llega la interconsulta y espera en ese lugar,
aunque después termine en urgencia u hospitalizado. Nadie se entera hasta que le toca su turno.

**Con Ambulatorio Dinámico:**
1. **Detecta el cambio.** Cada evento clínico nuevo entra al sistema: urgencia, hospitalización, examen alterado o cambio
   de fármaco. Puede llegar del registro, de un Excel/CSV importado o de la foto de un informe, que se lee con Textract y
   reglas y luego se confirma a mano.
2. **Recalcula la lista en milisegundos** con reglas oficiales: Tabla de priorización SSMSO 2025 del HLF y criterios
   MINSAL Ord. 536/2025. Si el diagnóstico empeoró, el paciente sube a la prioridad que indica la tabla para ese diagnóstico
   descompensado.
3. **Explica el porqué.** Cada paciente muestra el camino de su prioridad con la fuente de cada paso (interconsulta → evento
   → fila de la tabla → lugar en la lista). Bedrock puede redactarlo en lenguaje simple, pero no decide nada.
4. **Pide revisar la prioridad con plazo.** Una descompensación grave genera "revisar prioridad ≤ 72 h" (KPI del hospital:
   reevaluación < 72 h tras un evento). El plazo corre desde que el evento **llega al sistema**. La alerta se cierra solo
   cuando el especialista revisa: decisión clínica, confirmar o ajustar la prioridad, o un ajuste manual. Llamar o citar
   no la cierran. Pasadas 72 h queda "atrasada".
5. **Gestiona cada caso.** Cada fila responde cuánto espera, qué falta y quién se encarga: estado de gestión calculado
   (pendiente de revisión, de contacto o de cita; cita reservada; atendido) + responsable, próxima acción, fecha de
   seguimiento y motivo del pendiente.
6. **El equipo clínico decide y queda registro.** El especialista confirma o ajusta la prioridad con un motivo, o mueve al
   paciente a mano con motivo y explicación. Todo queda a nombre de quien lo hizo. Las revisiones alimentan el kappa.
7. **Mide si funciona:** reevaluación tras eventos, trabajo pendiente, espera prolongada, citas por estado,
   contactabilidad, kappa (con su n) y cobertura del 100 % de la lista con el mismo criterio.

**Impacto medido en el dataset sintético:**
- 17 pacientes con descompensación grave (al 13-10-2026): en la lista congelada su lugar mediano era el **N° 171** (16 de
  ellos fuera de los primeros 50); en la lista dinámica es el **N° 9**.
- Fallecidos (`scripts/validar_priorizacion.py`, tomado del PR de agusnoopy3000): 7 días antes de morir, los 15 fallecidos
  estaban en la mediana del **9 % superior** de la lista dinámica vs. **47 %** de la congelada; 8 vs. 3 en el 10 % superior.
- Honestidad: con estos datos ninguna lista anticipa urgencias futuras (mediana 37 % vs 41 %). No se presenta como predicción.

**Por qué es confiable:**
- no hay "caja negra": son reglas con fuente que se pueden auditar;
- el sistema nunca baja la prioridad de nadie por sí solo;
- un ajuste manual pierde efecto si llega un evento clínico nuevo (el deterioro no queda escondido);
- las inasistencias no castigan la prioridad clínica;
- los fallecidos salen de la lista;
- todo es reproducible a cualquier fecha de corte.

**Por qué escala:** la tabla de priorización es un diccionario en `puntaje.py` (`FILA_DESCOMPENSADO`), así que adaptarla
a otro hospital del SSMSO es cambiar ese diccionario, sin tocar el resto. Además importa Excel/CSV del sistema del hospital
y corre sin servidores propios en AWS (Lambda, API Gateway, DynamoDB, S3, Textract, Bedrock y Amplify).

## 2. Plazos (no negociables)
- Miércoles 21:00: todo desplegado de punta a punta. **Hecho.**
- **Jueves 15:00: congelamiento de funcionalidades** (meta del equipo; confirmar si es regla del evento). Después solo se
  pule, se ensaya y se graba un video de respaldo.
- Viernes 10:15: cierre del código. 12:00: pre-evaluación técnica. 15:00: pitch de los finalistas.
- Prioridad absoluta: **que la demo funcione**, por sobre cualquier funcionalidad nueva.

**Rúbrica:** innovación técnica 25 % · impacto social 25 % · factibilidad 20 % · escalabilidad 15 % · presentación 15 %.

**Indicadores (KPI) del hospital** (según el `CLAUDE.md` del equipo):
- reevaluación < 72 h tras un evento (se interpretó como revisar la **prioridad**; pendiente de confirmar con el HLF si
  en cambio significa que un médico evalúe al paciente);
- concordancia con el experto, kappa ≥ 0,70;
- 100 % de la lista con un criterio común.

## 3. Principios de diseño (obligatorios; el usuario insiste mucho en esto)
1. **Las reglas explicables y con fuente oficial ordenan la lista, no un modelo de IA.** Nada de pesos inventados: cada razón
   lleva su `fuente`. El LLM (Amazon Bedrock) solo redacta explicaciones en lenguaje simple. **Sin IA predictiva.**
2. **La herramienta propone y explica; el equipo clínico decide** (confirmar, ajustar o mover, con motivo y trazabilidad).
3. Fallecidos: salen de la lista (causal 9). Atendidos: salen desde su fecha de atención.
4. Las inasistencias **no** bajan la prioridad: solo encienden la bandera `riesgo_inasistencia` (posible causal 8).
5. Todo se calcula a una `fecha_corte`, usando solo registros con fecha anterior o igual.
6. **Fotos de informes sin IA generativa** (decisión del usuario: "un error en el hospital puede ser crítico"). El flujo es
   Amazon Textract (OCR) → reglas con detección de negaciones → validación con Pydantic → confirmación humana con
   verificación de identidad. Bedrock queda solo como respaldo opcional.
7. **No inventar metas ni datos.** Si el hospital no fijó una meta, el indicador dice "Sin meta oficial".

## 4. Modelo de priorización (`lambda/puntaje.py`)
- **Categoría alta, media o baja:** parte de la `prioridad_inicial` de la SIC. Si después hay una descompensación (evento
  grave), sube a la fila "descompensado / no controlado" de la **Tabla de priorización SSMSO 2025 del HLF** (págs. 84 a 111),
  definida en `FILA_DESCOMPENSADO`:
  - pasan a alta: I50, I20, J44, J45 y K70;
  - pasan a media: E11, E03 y G40.

  **El sistema nunca baja una categoría por sí solo.** Las equivalencias K70, I20 y G40 están marcadas "a validar".
- **Orden** (MINSAL Ord. 536/2025), en `clave_orden`:
  1. categoría;
  2. descompensación grave (`riesgo_vital`);
  3. grupo de especial protección;
  4. antigüedad mayor a 1 año;
  5. **LACE** (experimental, solo desempata);
  6. días de espera;
  7. id del paciente.

  Después se aplican los **ajustes manuales** vigentes (`_aplicar_ajustes` en `app.py`).
- **Descompensación grave (`riesgo_vital`, nombre interno):** un evento grave sin registro posterior de estabilización, en un
  diagnóstico cuya fila de la tabla es alta. Su **prioridad debe revisarse en 72 h** desde que el evento llegó al sistema
  (`evaluacion.llego_al_sistema`: fecha de registro en la app o `REGISTRO_AL` = 2026-10-13 para el registro cargado).
  `evaluacion.estado`: `pendiente` (nueva, en plazo), `atrasada` o `evaluada`. El sistema **no** declara "riesgo vital".

  La alerta (`contactar_hoy`) se cierra solo con una revisión del especialista registrada después del evento:
  - una decisión clínica (`/decision`);
  - confirmar o ajustar la prioridad (`/revision`);
  - un ajuste manual de la posición (`/orden`).

  Llamar, citar o derivar quedan registrados, pero **no** cierran la alerta.
- **Banderas** (no cambian el orden):
  - GES "posible incumplimiento: verificar": el plazo se cuenta desde el ingreso a la lista, porque el registro no trae el
    hito real;
  - 2 inasistencias consecutivas;
  - medición fuera de rango;
  - revisión sugerida (exámenes alterados, aumento de dosis).
- **Vigencia:** un evento posterior invalida la confirmación, el ajuste de categoría o el ajuste manual de posición, y pide
  revisar de nuevo.
- Las fuentes están en `docs/criterios_oficiales.md`.

## 5. Arquitectura (todo en AWS)
- `front/`: React + Vite + framer-motion + Tailwind (por CDN), con el logo y los colores del HLF, **tema claro/oscuro**
  (botón sol/luna; colores como variables CSS en `front/src/styles/tokens.css`). Se publica en **AWS Amplify** (deploy
  manual con zip mediante el script). Sin `VITE_API_URL`, funciona en modo mock con `front/src/mock.json` (sin los campos
  de gestión).
- `lambda/`: Python 3.12 (arm64), una sola Lambda detrás de **API Gateway HTTP API**. Se despliega con CloudFormation/SAM
  (`template.yaml`).
  - Datos: `perfiles.json` y `box.json` en **S3**.
  - Registros del equipo (eventos, revisiones, contactos, decisiones, citas, gestión, ajustes de orden, novedades e
    importaciones) en **DynamoDB**, con `pk=id_paciente` y `sk=tipo#fecha` (se guarda todo el historial).
  - **Textract** lee fotos; **Bedrock** (`us.anthropic.claude-sonnet-5`) redacta explicaciones. No enviar `temperature`:
    el modelo lo rechaza.
- **Fecha:** la variable `FECHA_REFERENCIA=hoy` usa la fecha real de Chile (así está publicado). Con `AAAA-MM-DD` se simula
  una fecha; por defecto es 2026-10-13, que es la fecha del dataset.

**Archivos clave**

| Archivo | Qué contiene |
|---|---|
| `lambda/app.py` | Todas las rutas y la lógica de negocio: enriquecer pacientes, gestión, ajustes manuales, KPIs, informes, RUT |
| `lambda/puntaje.py` | Motor de reglas |
| `lambda/informe.py`, `lambda/modelos.py` | Lectura de informes (Textract + reglas) y modelos Pydantic |
| `lambda/importar.py` | Importación de Excel/CSV solo con la librería estándar |
| `lambda/explicar.py` | Explicación con Bedrock, o con plantilla si no hay modelo |
| `lambda/local_server.py` | Servidor local (puerto 3001) |
| `front/src/App.jsx` | Toda la interfaz |
| `front/src/excel.js` | Genera .xlsx reales en el navegador, sin librerías |
| `front/src/api.js` | Llamadas a la API (agrega `usuario` a cada POST) |
| `contrato.md` | **Contrato de la API y del JSON. No cambiar campos sin avisar al equipo.** |
| `tests/test_api.py` | 54 tests (estilo pytest) |
| `scripts/deploy_aws.ps1` | Publica backend, datos y página |
| `scripts/limpiar_demo.py` | Borra lo registrado desde la app (deja la demo en su estado inicial) |
| `scripts/validar_priorizacion.py` | Validación con fallecidos y eventos graves |
| `scripts/generar_mock.py` | Regenera `mock.json` |

## 6. Rutas principales de la API (el detalle está en `contrato.md`)

| Método y ruta | Qué hace |
|---|---|
| `GET /pacientes?fecha_corte=&especialidad=` | Lista priorizada, con `excluidos`. Cada paciente trae `gestion`, `rut`, `prevision`, `posicion_sistema`, `posicion_especialidad` |
| `GET /pacientes/{id}` | Detalle del paciente |
| `GET /pacientes/{id}/historia` | Posición del paciente cada 14 días |
| `POST /pacientes` | Ingresa una interconsulta. `rut` opcional, validado con dígito verificador (400 si es inválido, 409 si ya existe por ese diagnóstico) |
| `POST /eventos` | Registra un evento clínico y recalcula la lista |
| `POST /pacientes/{id}/informe` | Lee texto o foto y **propone** eventos; no guarda nada |
| `POST /pacientes/{id}/revision` | Confirmar o ajustar la categoría, con motivo |
| `POST /pacientes/{id}/gestion` | Responsable, próxima acción, seguimiento y motivo del pendiente. `usuario` obligatorio |
| `POST /pacientes/{id}/orden` | Mover a una posición de la lista de su especialidad: `motivo` + `explicacion` (20+ caracteres) + `usuario`. `{quitar: true}` lo deshace |
| `POST /pacientes/{id}/contacto` | Llamada: `citado`, `derivado_urgencia`, `contactado` o `no_contesta` |
| `POST /pacientes/{id}/decision` | Decisión clínica: `citar_prioritario`, `derivar_urgencia`, `adelantar_control` o `mantener`. `responsable` es obligatorio |
| `POST /pacientes/{id}/novedad` | Comorbilidad, cambio de diagnóstico, datos de riesgo, fallecimiento o atendido |
| `GET /kpis` | Reevaluación, trabajo pendiente, espera prolongada, citas por estado, contactabilidad, ajustes manuales y kappa con su n |
| `POST /importar`, `GET /plantillas/{tabla}` | Carga de Excel/CSV |
| `GET /catalogo` | Diagnósticos, comunas, previsiones, motivos y otros valores para los formularios |
| `GET /health` | Estado de la API: `fecha_hoy`, `modo`, `datos_hasta`, `registro_al`, `datos: "sinteticos"` |
| `GET /boxes`, `GET /disponible`, `POST /pacientes/{id}/cita` | Gestión de box (siguen funcionando, pero ya no están en el menú) |

## 7. Pantallas del front
- **Lista de espera** (página principal): simple, como una planilla. Columnas: N°, Nombre, RUT/ID, Edad, Sexo, Comuna,
  Previsión, Especialidad, Diagnóstico, Prioridad, Ingreso y Días de espera. Buscador, filtros de especialidad y prioridad,
  "Descargar en Excel". Un clic en un paciente abre su detalle en "Lista detallada". Los datos sintéticos no traen RUT:
  se muestra el ID en gris; los pacientes ingresados con RUT muestran el RUT.
- **Lista detallada:** tarjetas que filtran (prioridad alta, pendientes de revisión, más de 1 año, GES…), filtros por
  estado de gestión y espera prolongada, "Limpiar filtros", "Exportar a Excel" (5 hojas). Columnas: N°, prioridad
  (propuesta del sistema / asignada en la SIC / confirmada / ajustada), paciente y marcas, espera destacada, estado de
  gestión, próxima acción y responsable. La ficha del paciente tiene 5 pestañas:
  - *Resumen:* cómo se decidió su lugar, revisión de la prioridad y resumen para el equipo (Bedrock);
  - *Gestión:* gestión del caso, decisión del especialista, llamada y "Mover en la lista";
  - *Registrar:* informe con cámara, novedades y simulación de eventos;
  - *Fundamento:* razones con fuentes y LACE;
  - *Historia:* gráfico de posición en la lista y línea de tiempo.
- **Alertas pendientes:** descompensaciones graves para revisar la prioridad (nuevas vs. atrasadas), agrupadas por
  especialidad, y "Avisar al especialista". Selector de especialidad y exportación a Excel.
- **Indicadores** (una sola especialidad elegida para toda la página, "Exportar todo a Excel"): metas del hospital (reevaluación
  < 72 h, kappa ≥ 0,70, cobertura 100 %), situación de la lista hoy, resumen por especialidad (clic filtra), evolución de la
  lista (gráficos aportados por Diego: composición por prioridad y descompensaciones graves con su propia escala), tiempos de
  espera por tramo, por qué cambió la lista, mayores saltos, trabajo pendiente y evolución de cada paciente (plegada).
- **Ficha del paciente → Resumen:** "Por qué está en el N° X y cómo se ha movido": gráfico de subidas y bajadas en la lista
  y paso a paso con fuentes (prioridad inicial, eventos, tabla HLF, decisión del equipo, ajuste manual, GES, espera).
- **Cargar datos** (Excel/CSV) y **Criterios** (fuentes con enlaces).
- **Explorar fechas anteriores:** un control deslizante muestra la lista en fechas pasadas (cada 14 días, desde abril).
- Arriba: campo **"Su nombre y cargo"** (queda en cada registro), botón de tema y franja fija con "Datos sintéticos" y las
  fechas (lista calculada al X · registro del hospital al 13-10 · último dato clínico 10-10).
- Funciona en celular (revisado a 390 px de ancho): la cabecera se apila, el menú y la tabla detallada se desplazan hacia el
  lado y al tocar un paciente la página baja hasta su ficha.

## 8. Datos
- Dataset **sintético** del hospital: 500 pacientes, 7 especialidades, registro al 2026-10-13 (último dato clínico
  2026-10-10). El archivo principal es `data/perfiles.json`, con un objeto por paciente que incluye `lista_espera`,
  `eventos_clinicos`, `mediciones` y `citaciones`. No trae RUT.
- **`data/` nunca va al repo** (está en `.gitignore`), igual que los CSV, `box.json` y `.env`. Los dos archivos de datos se
  pasan por fuera de GitHub (Drive).
- La app publicada **no tiene autenticación**: no se deben subir datos reales de pacientes. Cualquiera con el link puede
  registrar cosas: antes de una demo, correr `python scripts/limpiar_demo.py --borrar`.
- **Pacientes de demo:**
  - 00002: angina; sube a alta tras una urgencia y una hospitalización;
  - 00001: deterioro progresivo; PHQ-9 de 4 a 19;
  - 00028: mejora; el sistema no le baja la prioridad solo;
  - 00020: 2 inasistencias;
  - 00009: fallece y sale de la lista.
- Con la fecha real aparecen 17 descompensaciones graves "nuevas, en plazo" (llegaron al sistema el 13-10). Desde el 17-10
  pasan a "atrasadas" si nadie las revisa.

## 9. Cómo correrlo
```powershell
# API local (desde ambulatorio-dinamico/)
$env:LOCAL="1"; $env:DATA_DIR="$PWD\data"; $env:FECHA_REFERENCIA="hoy"   # opcional: AWS_PROFILE, MODEL_ID, BEDROCK_REGION
python -X utf8 lambda\local_server.py          # http://localhost:3001

# Front
cd front; $env:VITE_API_URL="http://localhost:3001"; npm run dev -- --port 5174

# Tests (pytest no está instalado: las funciones test_* se pueden correr con un runner simple o instalando pytest)
python -X utf8 -m pytest tests -q

# Publicar en AWS (perfil "hack" con credenciales temporales vigentes)
powershell -ExecutionPolicy Bypass -File scripts\deploy_aws.ps1           # backend + datos + página
powershell -ExecutionPolicy Bypass -File scripts\deploy_aws.ps1 -SoloFront

# Dejar la demo publicada en su estado inicial (borra lo registrado desde la app en DynamoDB)
python scripts\limpiar_demo.py            # solo muestra cuántos registros hay
python scripts\limpiar_demo.py --borrar   # borra todo
```
- **Producción:** página en https://main.d2jvqnf67i4lks.amplifyapp.com y API en https://prpq37get4.execute-api.us-east-1.amazonaws.com
  (región us-east-1, cuenta del evento en AWS Workshop Studio, rol `WSParticipantRole`). La cuenta probablemente se borre
  al terminar la hackatón.
- **Credenciales:** son temporales (vencen en horas). Se sacan de la página del evento en **AWS Workshop Studio**
  ("Get AWS CLI credentials"), **no** del portal SSO (ese portal es para Kiro y no muestra la cuenta). Se guardan en
  `~/.aws/credentials` como perfil `[hack]`. **Nunca se pegan en el chat ni se suben al repo.**
- Si AWS rechaza con "Signature not yet current", el reloj del computador está desfasado: sincronizarlo en Windows.
- El script de deploy arma siempre un paquete limpio de la Lambda en una carpeta nueva (incluye Pydantic para Linux ARM).

## 10. Reglas para trabajar en el código
- Responde en **español chileno**, directo y sin relleno.
- Haz cambios chicos que no rompan lo que funciona. Si propones algo grande, avisa antes.
- **No agregues librerías nuevas sin preguntar.**
- Explica brevemente cada cambio: el equipo tiene que poder defender el código en la pre-evaluación técnica.
- No cambies los campos de `contrato.md` sin avisar.
- Después de cambiar algo: corre los tests y compila el front (`npx vite build`). Si cambió el motor, regenera el mock
  (`python scripts/generar_mock.py data`).
- Para PowerShell 5.1: no uses `&&`; escribe el YAML **sin BOM**; arma los zip con `/` y no con `\`.
- Trabajen en ramas y junten con Pull Request: `App.jsx` es un archivo grande y dos personas editándolo a la vez chocan.

## 11. Historial reciente
**14-10:** una revisión externa criticó la primera versión y se corrigió (commit `6d07669`): fecha real de Chile y franja
de datos sintéticos; "riesgo vital" → "descompensación grave"; llamada separada de la decisión clínica; estados de cita;
GES como "verificar"; LACE experimental; equivalencias "a validar"; indicadores de resultado.

**15-10:**
- Tema claro/oscuro tomado del PR #1 de agusnoopy3000 (solo los colores; el resto del PR no se juntó).
- Pedidos del hospital: lista de espera como página principal, fuera la gestión de box, sin IA predictiva.
- Ajuste manual de la posición con motivo y explicación (`/orden`).
- Exportación a Excel (.xlsx real) de la lista, las alertas y los indicadores.
- Segunda revisión externa: estado de gestión por paciente (`/gestion`), 72 h como revisión de la prioridad desde que el
  evento llega, prioridad propuesta vs. confirmada, filtros, tarjetas que filtran, textos más claros.
- Dos pestañas: "Lista de espera" (simple) y "Lista detallada" (todo).
- RUT con dígito verificador al ingresar pacientes y vista en celular.

## 12. Pendiente
1. **Confirmar con el hospital** si las 72 h son para revisar la prioridad (como quedó) o para que un médico evalúe al paciente.
2. **Guion de la demo** de punta a punta: paciente con 500+ días → se ve qué lo bloquea → se asigna responsable y próxima
   acción → llamada "Citado" → atendido y sale de la lista; más el momento fuerte: llega un informe de hospitalización,
   el paciente sube y aparece la alerta de 72 h. Números: N° 171 → N° 9; fallecidos 9 % vs 47 %.
3. **Video de respaldo** y ensayo. Antes del pitch: `limpiar_demo.py --borrar` y abrir la página una vez para "calentarla".
4. Siguiente etapa (para decir en el pitch, no para construir ahora): inicio de sesión con Amazon Cognito y roles,
   control de edición simultánea, varias solicitudes por paciente.
