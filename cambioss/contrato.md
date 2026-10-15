# Contrato — Ambulatorio Dinámico HLF

Fuente de datos: `perfiles.json` (500 pacientes, ya consolidado) en S3. **Nunca en el repo.**
Fecha de referencia del dataset: 2026-10-13. Todo cálculo usa una `fecha_corte`: solo registros con fecha ≤ corte.
Sin `fecha_corte`, la API usa `FECHA_REFERENCIA` (variable de entorno): `hoy` = fecha real de Chile (versión publicada) o
`AAAA-MM-DD` para simular (por defecto 2026-10-13). `/health` informa `fecha_hoy` y `modo` (`tiempo_real | simulacion`).

## Reglas de negocio (todas con fuente; detalle en `docs/criterios_oficiales.md`)
- **Categoría** `alta | media | baja`: parte de `prioridad_inicial` (la que asignó el especialista a la SIC). Si después de la SIC
  hay un evento de descompensación o severidad grave, sube a la fila "descompensada / no controlada" de la
  **Tabla SSMSO 2025 del HLF** (págs. 84–111). El sistema **nunca baja** una categoría: eso lo hace el equipo clínico con motivo.
- **Orden** (MINSAL Ord. 536/2025): categoría → descompensación grave (`riesgo_vital`) → grupo de especial protección →
  antigüedad > 1 año → LACE (experimental, solo desempate) → orden de llegada.
- **Descompensación grave** (`riesgo_vital` = true, nombre interno): requiere evaluación médica dentro de 72 h. El sistema no
  declara "riesgo vital"; lo decide el médico. `evaluacion.estado`: `pendiente | atrasada (> 72 h) | evaluada`. Se cierra solo con
  una decisión clínica (`/decision`), una revisión del especialista, una cita reservada o una derivación a urgencia.
- **Banderas** (no cambian el orden): `ges.vencida` / `ges.verificar` = posible incumplimiento GES a verificar (el plazo se cuenta
  desde el ingreso a la lista porque el registro no trae el hito real) · `riesgo_inasistencia` = 2 inasistencias
  consecutivas, posible causal 8 · `medicion_alerta` = última medición fuera de rango.
- `estado = atendido` → no aparece. Fallecido con `fecha_defuncion <= corte` → `excluidos` (causal 9).
- No hay pesos inventados: el orden lo dan reglas con fuente. Las fotos se leen con Amazon Textract + reglas + Pydantic;
  el LLM (Bedrock) solo redacta explicaciones y es respaldo opcional para proponer eventos, siempre con confirmación humana.

## Objeto Paciente (respuesta de la API)
```json
{
  "id_paciente": "PAC-HLF-00002", "nombre_fantasia": "Paciente Violeta 002", "edad": 49, "sexo": "M", "comuna": "Puente Alto",
  "especialidad": "Cardiología", "diagnostico_cie10": "I20", "diagnostico_texto": "Angina de pecho",
  "prioridad_inicial": "baja", "fecha_ingreso_lista": "2025-11-08", "dias_espera": 275,
  "categoria": "alta",
  "categoria_sistema": "alta",
  "estado_clinico": "descompensado",
  "antiguedad_mayor_1_anio": false,
  "ges": null,
  "medicion_alerta": true,
  "posicion": 41, "posicion_anterior": 313,
  "riesgo_inasistencia": false, "no_shows": 0,
  "razones": [
    {"factor": "prioridad_inicial", "valor": "baja (asignada por el especialista al priorizar la SIC)", "fuente": "Priorización de la SIC (CUD / Thalamus)"},
    {"factor": "evento", "valor": "hospitalizacion: ingreso hospitalario (grave, 2026-08-06)", "fuente": "Registro clínico posterior a la SIC"},
    {"factor": "tabla_oficial", "valor": "\"Angina inestable\" → prioridad alta", "fuente": "Tabla SSMSO 2025, HLF, pág. 85"},
    {"factor": "dias_espera", "valor": "275 días en lista", "fuente": "MINSAL Ord. 536/2025: antigüedad > 1 año"}
  ],
  "explicacion_ia": null,
  "estado_revision": "pendiente"
}
```
- `categoria` = la vigente (si el equipo ajustó, la ajustada). `categoria_sistema` = la que proponen las reglas.
- `estado_clinico`: `sin_cambios | descompensado | estabilizado` (eventos posteriores al ingreso a la lista).
- `ges`: `null` o `{"problema": 34, "nombre": "Depresión", "plazo_dias": 30, "vencida": true}`.
- `razones[].factor`: `prioridad_inicial | evento | tabla_oficial | dias_espera | ges | medicion`. Cada razón trae su `fuente`.
- `estado_revision`: `pendiente | confirmado | ajustado | requiere_revision`.
- `evaluacion` (solo si `riesgo_vital`): `{"estado", "dias_desde_evento", "fecha_evento", "plazo_dias": 3, "cierre": null | {"por", "texto", "responsable", "fecha"}}`.
- `decision`: última decisión clínica o `null`. `contacto`: última llamada o `null` (con `intentos_sin_respuesta`).
- `gestion`: `{estado (pendiente_revision · pendiente_contacto · pendiente_cita · cita_reservada · atendido), texto, proxima_accion, responsable, seguimiento, seguimiento_vencido, motivo_pendiente, motivo_texto, nota, actualizado_por, actualizado, reserva}`. El estado se calcula con lo registrado.
- `evaluacion` (descompensación grave): el plazo de 72 h es para **revisar la prioridad** y corre desde `llego_al_sistema` (registro en la app o `REGISTRO_AL` del registro cargado); `dias_en_revision`. Se cierra con decisión clínica, revisión o ajuste manual (llamar o citar no la cierran).
- `prevision` del paciente.
- `posicion_sistema` (orden de las reglas), `posicion` y `posicion_especialidad` (con ajustes manuales), `ajuste_manual` y `ajuste_manual_vencido`.
- `lace`: `{"total", "partes", "experimental": true, "datos_faltantes": [...], "uso"}`.

## Endpoints
| Método | Ruta | Qué hace |
|---|---|---|
| GET | `/pacientes?especialidad=X&fecha_corte=AAAA-MM-DD` | Lista priorizada + `excluidos` |
| GET | `/pacientes/{id}` | Perfil completo con línea de tiempo (eventos, mediciones, citas) |
| POST | `/pacientes/{id}/informe` | Lee un informe (`texto` o `imagen_base64` + `media_type`) y **propone** un evento. No guarda nada |
| POST | `/eventos` | Agrega un evento confirmado → recalcula → devuelve la lista nueva |
| POST | `/pacientes` | Ingresa una interconsulta nueva (`nombre, edad, sexo, diagnostico_cie10, prioridad_inicial`, opcionales comuna, previsión, origen)  · `rut` opcional: se valida el dígito verificador (400 si es inválido) y se guarda como `12.345.678-5`; 409 si ese RUT ya tiene una interconsulta por el mismo diagnóstico |
| POST | `/pacientes/{id}/novedad` | `tipo`: `comorbilidad` (`condicion` de Charlson o `cie10`), `diagnostico` (`cie10`), `fallecimiento` o `atendido` (`fecha`). Queda registro `novedad#` |
| GET | `/pacientes/{id}/historia?fecha_corte=` | Posición y categoría cada 14 días (gráfico de evolución) |
| POST | `/pacientes/{id}/contacto` | Llamada: `resultado` citado · derivado_urgencia · contactado · no_contesta (+ `nota`). `citado` con `hora`, `hora_fin`, `id_box` reserva la hora (409 si ya está reservada). Solo citado y derivado_urgencia cierran la alerta. **Cambio:** `se_mantiene` pasó a `/decision` (`mantener`) |
| POST | `/pacientes/{id}/decision` | Decisión clínica: `decision` citar_prioritario · derivar_urgencia · adelantar_control · mantener; `responsable` (obligatorio), `nota`, `seguimiento` (AAAA-MM-DD). Cierra la alerta |
| POST | `/pacientes/{id}/gestion` | Gestión del caso: `responsable`, `proxima_accion`, `seguimiento` (AAAA-MM-DD, no anterior a hoy), `motivo_pendiente` (falta_cupo · contacto · antecedentes · revision · paciente · otro; "otro" exige `nota` de 20+ caracteres) y `usuario` obligatorio |
| POST | `/pacientes/{id}/orden` | Ajuste manual de la posición: `posicion` (en la lista de su especialidad), `motivo` (criterio_clinico · informacion_no_registrada · comite · error_registro · otro), `explicacion` (mín. 20 caracteres) y `usuario` obligatorios. `{quitar: true, explicacion, usuario}` lo deshace. Un evento posterior lo deja sin efecto (`ajuste_manual_vencido`) |
| POST | `/pacientes/{id}/cita` | Estado de la cita reservada hoy: `estado` confirmada · atendida · no_asistio · cancelada (libera la hora). 404 si no hay reserva |
| GET | `/disponible?especialidad=X&desde=HH:MM&hasta=HH:MM` (o `&cupos=N`) | Médico con horas libres: a quiénes atender, en el orden de la lista, con hora sugerida (duración promedio de la especialidad), sin repetir a quienes ya tienen cita reservada; los que solo están propuestos en un box vienen con `propuesto_en_box`; + 3 reservas |
| GET | `/kpis?fecha_corte=&especialidad=` | Indicadores de todo el hospital o de una especialidad: `reevaluacion`, `concordancia` (n, acuerdo %, kappa), `cobertura`, `espera`, `trabajo_pendiente`, `contactabilidad`, `ajustes_manuales`, `egresos`, `por_especialidad` (tabla resumen), `total_hospital` y `tramos_espera` (≤90, 90–180, 180–365, 365–500, >500 días) |
| GET | `/estadisticas?fecha_corte=&especialidad=` | Serie cada 14 días desde el 01-04-2026 (`total, alta, media, baja, graves, egresos, atendidos, fallecidos`), `causas` y `evento_causa` por paciente (tipo exacto del evento grave que explica el cambio) |
| GET | `/catalogo` | Diagnósticos, comunas, previsiones, orígenes y condiciones de Charlson con su peso |
| POST | `/importar` | `{archivos:[{nombre, contenido_base64}], confirmar}`: lee Excel/CSV, detecta la tabla, normaliza y valida. Sin `confirmar` solo revisa |
| GET | `/plantillas/{tabla}` | CSV de ejemplo: pacientes, lista_espera, eventos_clinicos, mediciones, citaciones, agenda_box |
| POST | `/pacientes/{id}/revision` | `{"accion":"confirmar"}` o `{"accion":"ajustar","categoria_ajustada":"alta|media|baja","motivo":"..."}` |
| POST | `/pacientes/{id}/explicar` | Bedrock redacta `explicacion_ia` desde `razones` |
| GET | `/boxes?fecha_corte=AAAA-MM-DD` | Ocupación de box por especialidad + pacientes sugeridos para horas libres. Cada fila trae `estado_cita` (propuesta · reservada · confirmada · atendida · no_asistio); por especialidad `conteo_citas` y `descompensados`. `agenda_referencia: true` si la fecha no tiene agenda propia y se usa la última del registro (`dia_agenda`) |
| GET | `/health` | `{ok, pacientes, fecha_hoy, modo, datos: "sinteticos", datos_hasta, registro_al}` para verificar el deploy |

## Respuesta POST /pacientes/{id}/informe
```json
{ "id_paciente": "PAC-HLF-00020", "fuente": "bedrock | reglas", "transcripcion": "texto leído de la foto o null",
  "evento": {"tipo_evento": "hospitalizacion", "subtipo": "ingreso hospitalario", "severidad": "grave",
             "fecha_evento": "2026-10-12", "evidencia": "Se hospitaliza en cardiología"},
  "categoria_actual": "media", "categoria_propuesta": "alta",
  "razones_propuestas": [{"factor": "tabla_oficial", "valor": "\"Angina inestable\" → prioridad alta", "fuente": "Tabla SSMSO 2025, HLF, pág. 85"}] }
```
Si no se detecta evento: `"evento": null` y `"mensaje"`. Leer fotos requiere `MODEL_ID` (Bedrock con visión).
Para confirmar, el front envía ese `evento` a `POST /eventos`.

## Respuesta POST /eventos
```json
{ "evento": {...}, "paciente": { ...objeto Paciente... }, "posicion_antes": 231, "posicion_despues": 49,
  "reevaluado_en_ms": 11, "lista": { ...misma forma que GET /pacientes, sin filtro de especialidad... } }
```
Body: `id_paciente`, `tipo_evento`, `subtipo`, `severidad`, `detalle` y opcionales `fecha_corte` (default 2026-10-13), `fecha_evento` (default = fecha_corte).
`tipo_evento`: cambio_farmaco · control_aps · examen_alterado · hospitalizacion · visita_urgencia

## Pacientes de demo (del dataset)
| ID | Historia | Qué muestra |
|---|---|---|
| PAC-HLF-00002 | Angina, baja → urgencia ESI 2 (20-jul) + hospitalización | Puesto 313 → 45: pasa a Alta por "Angina inestable" (pág. 85) y se mantiene |
| PAC-HLF-00001 | Depresión, PHQ-9 de 4 a 19 | Alta desde el inicio; GES N°34 vencida; medición fuera de rango |
| PAC-HLF-00028 | Buena respuesta + reducción de dosis | Estabilizado al fondo; el sistema no la baja solo |
| PAC-HLF-00020 | 2 inasistencias consecutivas | Bandera causal 8 sin bajar su prioridad |
| PAC-HLF-00009 | Fallece 2026-09-08 | Sale de la lista (causal 9) |
