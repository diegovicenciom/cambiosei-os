# Criterios de priorización y sus fuentes

Regla de oro: **ningún peso ni umbral inventado.** Cada decisión del motor (`lambda/puntaje.py`) cita un documento.

## 1. Categoría: Alta / Media / Baja
- **Base:** la prioridad que el especialista asignó al leer la SIC (`prioridad_inicial`, CUD o Thalamus).
- **Sube** si, después de emitida la SIC, el registro muestra un evento etiquetado en el dataset como
  *descompensación* o de severidad *grave* (urgencia ESI 2, hospitalización, UCI). Esa información es la que
  el especialista "no ve" al priorizar (documento de proceso SIC del HLF, punto 3).
- La categoría nueva es la de la fila "descompensada / no controlada" del diagnóstico en la tabla oficial:
  **SSMSO (2025), *Priorización diagnósticos especialidades médicas y odontológicas No GES*, §11.1 Hospital
  Dra. Eloísa Díaz Inzunza, págs. 84–111.**
  https://redsalud.ssmso.cl/wp-content/uploads/2025/07/PRIORIZACION-SSMSO-02.07.2025-I-ETAPA.pdf

| CIE-10 | Fila de la tabla HLF | Prioridad | Pág. |
|---|---|---|---|
| I50 | Insuficiencia cardíaca descompensada | Alta | 85 |
| I20 | Angina inestable | Alta | 85 |
| J44 | EPOC grave no controlado | Alta | 95 |
| J45 | Asma grave no controlada | Alta | 95 |
| K70 | Cirrosis hepática descompensada | Alta | 95 |
| E11 | DM2 descontrolada | Media | 101 |
| E03 | Hipotiroidismo sintomático | Media | 94 |
| G40 | Epilepsia con crisis mensuales (deja de ser "epilepsia controlada", Baja) | Media | 103 |

I10, K21, F32, F41, G43, E66, M17, M54 y M75 **no tienen** fila de "descompensado" en la tabla del HLF:
mantienen su prioridad y el evento queda visible para revisión clínica (no suponemos una equivalencia).
- **Nunca baja sola:** una estabilización se muestra, pero bajar la prioridad lo decide el equipo clínico
  (`POST /revision` con `categoria_ajustada` y motivo).

## 2. Descompensación grave: requiere evaluación (va primero dentro de su categoría)
Descompensación **grave** sin estabilización posterior en un diagnóstico cuya fila oficial es **Alta**.
MINSAL prioriza la "criticidad / riesgo vital" (Ord. C27 N°373/2021, citado en SSMSO 2025 pág. 4) y el
"impacto en la progresión de la enfermedad y complicaciones" (Ord. 536/2025, criterio 1).
No es una predicción: se avisa con lo que ya ocurrió. **El sistema no declara "riesgo vital"**: pide evaluación médica
dentro de 72 h (KPI del hospital) y muestra los días desde el evento; pasado el plazo queda "atrasada". La alerta se
cierra solo con una decisión clínica registrada (con responsable), una revisión del especialista, una cita reservada o
una derivación a urgencia. Equivalencias CIE-10 a validar con el HLF: K70 → cirrosis, I20 → angina inestable,
G40 → crisis mensuales.

## 2b. Puntaje de riesgo LACE (puntos publicados, no inventados)
van Walraven C, Dhalla IA, Bell C, et al. *Derivation and validation of an index to predict early death or
unplanned readmission after discharge from hospital to the community.* CMAJ 2010;182(6):551-7, Tabla 3.
https://pmc.ncbi.nlm.nih.gov/articles/PMC2845681/

| Letra | Componente | Puntos |
|---|---|---|
| L | Días de estada | <1: 0 · 1: 1 · 2: 2 · 3: 3 · 4–6: 4 · 7–13: 5 · ≥14: 7 — **el registro no lo trae → 0** |
| A | Ingreso de urgencia | 3 (hospitalización en los 6 meses previos al corte) |
| C | Charlson | 0–3 = mismo número · ≥4 = 5. Pesos LACE: insuficiencia cardíaca 2, EPOC/enfermedad pulmonar crónica 2, hepática leve 2, diabetes sin complicaciones 1 (CIE-10 según Quan, Med Care 2005) |
| E | Urgencias en 6 meses | 0–3 = mismo número · ≥4 = 4 |

Uso: **experimental, solo desempate** dentro de la misma categoría, después del grupo de protección y la antigüedad.
No cambia la categoría. LACE está validado para muerte o reingreso tras un alta hospitalaria, no para listas de espera,
y en este registro faltan los días de estada (L = 0).
Validación en el dataset (cortes mensuales feb–jul 2026, evento = urgencia, hospitalización o muerte en 90 días,
n = 2.297): LACE 0 → 11,0% · 1 → 13,5% · 2 → 14,4% · 3 → 16,7% · 4–5 → 50% (n = 6). AUC 0,54 (original: 0,68–0,71).
Gradiente en la dirección esperada pero débil: datos sintéticos; recalibrar con datos reales del HLF.

## 2c. Revisión clínica, alertas y trazabilidad
- **Una revisión vale hasta el próximo evento.** Si después de confirmar o ajustar llega una descompensación, un examen
  alterado o un aumento de dosis, el ajuste deja de aplicarse y el paciente queda en "requiere nueva revisión".
  (Evita que un ajuste a "baja" oculte una hospitalización posterior.)
- **Revisión sugerida** (no cambia el orden): examen alterado y aumento de dosis — las señales que el documento de proceso
  del HLF dice que el especialista no ve al priorizar la SIC — y descompensaciones sin fila oficial en la tabla.
- **Llamada y decisión clínica están separadas.** La llamada (citado, derivado a urgencia, informado, no contesta) la
  registra quien llama; solo "citado" con hora reservada y "derivado a urgencia" cierran la alerta. La decisión clínica
  (citar prioritario, derivar, adelantar control, mantener) la registra un profesional identificado, con seguimiento.
  Las alertas repetidas sobre el mismo paciente bajan su aceptación ~30% por alerta (Ancker et al., BMC Med Inform
  Decis Mak 2017), por eso cada alerta se cierra con un motivo registrado.
- **Grupos de especial protección** (PRAIS, NNA bajo protección del Estado, Valech, Rettig): criterio 2 de MINSAL, ordena
  después del criterio médico. **ACG G0–G3** (estratificación SSMSO, ficha Rayen): se muestra, no reordena.
- **Lectura de informes con negación** estilo NegEx (Chapman 2001; adaptaciones al español NegEx-MES / SpRadNeg):
  "se descarta hospitalización" no se propone como hospitalización.
- **Atendidos** salen de la lista desde la fecha de su consulta nueva (no antes), igual que los fallecidos desde su
  fecha de defunción: se respeta la fecha de corte.

## 2d. KPIs del hospital (pestaña Indicadores)
Se miden resultados, no capacidades:
- **Reevaluación < 72 h:** horas entre el registro de un evento grave y la primera evaluación clínica (mediana, cuántos
  en menos de 72 h, cuántos sin evaluar) y descompensaciones pendientes, atrasadas y evaluadas. (El recálculo de la
  lista es inmediato, pero eso no es una evaluación clínica.)
- **Concordancia:** kappa de Cohen entre la categoría propuesta y la decisión del especialista (confirmar = acuerdo;
  cambiar = desacuerdo), informado junto con n y el % de acuerdo. Meta kappa ≥ 0,70; con menos de 50 revisiones es
  solo orientativo.
- **Cobertura** con criterio común (100%), **citas por estado**, **horas recuperadas** (sin meta oficial) y
  **contactabilidad** (llamadas con respuesta y reintentos).

## 3. Orden dentro de la categoría
MINSAL Ord. C N°536 (21-03-2025), recogido en el Manual de Gestión de la Demanda SSMSO 2025 (RE 2679), pág. 13:
1. Criterio médico (categoría y descompensación grave).
2. Grupos de especial protección (NNA bajo protección del Estado, PRAIS, Valech, Rettig): el dataset no los trae; se
   registran desde la ficha.
3. Antigüedad en la lista mayor a 1 año.
4. LACE (experimental, solo desempate).
5. Luego, orden de llegada (fecha de ingreso).

## 4. Banderas (no cambian el orden)
- **GES: posible incumplimiento, verificar.** Plazo de atención por especialista (auge.minsal.cl): Depresión N°34 30 días ·
  Hipertensión N°21 45 · EPOC N°38 45 · Diabetes tipo 2 N°7 60 · Asma N°61 60 · Epilepsia N°60 60 · Artrosis de rodilla
  (55+) N°41 120. El plazo corre desde la derivación con sospecha o confirmación diagnóstica; el registro solo trae el
  ingreso a la lista, por eso no se afirma "vencida".
- **Inasistencia:** 2 inasistencias consecutivas = posible causal 8 "Inasistencias reiteradas" (Manual SSMSO, Anexo 4).
  No baja la prioridad clínica; en box se sugiere confirmar por teléfono.
- **Medición:** última medición fuera de los rangos de referencia del diccionario de datos.

## 5. Exclusión
Fallecimiento = causal 9 (Manual SSMSO, Anexo 4), desde `fecha_defuncion`. Atendidos salen de la lista.

## 6. Box (vista para enfermería)
Los cupos libres de cada box del día (`agenda_box`) se asignan en el orden de la lista de su especialidad.
Cada paciente trae su motivo y la alternativa explica por qué va después, con los mismos criterios.

## 7. IA (Amazon Bedrock)
Solo: transcribir fotos de informes, extraer un evento con el vocabulario del registro (citando la frase) y
redactar explicaciones. Nunca asigna prioridad. El equipo clínico confirma cada evento antes de recalcular.
