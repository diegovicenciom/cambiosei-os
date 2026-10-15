# Lectura de informes y uso de IA

Prioridad de diseño: **un error en el hospital puede ser crítico.** Por eso la lectura de informes es determinística y
la IA generativa solo es un respaldo opcional, siempre validado y confirmado por una persona.

## Flujo (lambda/informe.py + lambda/modelos.py)
| Paso | Herramienta | Tipo |
|---|---|---|
| 1. Foto → texto | **Amazon Textract** `DetectDocumentText` (OCR), con confianza por línea | Determinístico (no generativo) |
| 2. Texto → eventos | **Reglas** de palabras clave + negación estilo NegEx; devuelve **todos** los eventos, del más grave al menos grave | Determinístico |
| 3. Validación | **Pydantic** (`EventoPropuesto`): tipo/subtipo del registro, severidad coherente, frase de evidencia textual en el documento, fecha no futura | Determinístico |
| 4. Respaldo opcional | **Amazon Bedrock** solo si las reglas no encuentran nada y hay `MODEL_ID`; pasa por la MISMA validación y se marca "sugerido por IA" | Generativo, acotado |
| 5. Decisión | La enfermera elige el evento y confirma que el documento es del paciente | Humano |

## Salvaguardas contra errores críticos
- **Paciente equivocado:** si el documento menciona otro ID de paciente, se bloquea el registro; si no menciona al paciente, se advierte. Siempre hay que marcar "confirmo que el documento corresponde a …".
- **Foto ilegible:** confianza media < 80 % → se pide repetir la foto y se bloquea el registro; líneas < 90 % se marcan.
- **Fecha:** se toma de la línea del evento o de una línea "Fecha"; nunca de una línea de nacimiento/edad. Si no hay, se avisa.
- **Negaciones:** "se descarta…", "no requiere…", "niega…" no generan eventos.
- **Nada se guarda** hasta que la persona confirma; cada evento queda con quién y cuándo lo registró.

## Resumen para el equipo (lambda/explicar.py)
Plantilla fija por defecto. Si hay `MODEL_ID`, Bedrock redacta el mismo fundamento en lenguaje simple. No cambia la prioridad.
