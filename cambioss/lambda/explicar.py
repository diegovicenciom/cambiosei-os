"""Explicación de la prioridad con Amazon Bedrock (Converse API).

El LLM NO decide la prioridad: solo redacta, en lenguaje clínico claro, las 'razones'
que ya calculó puntaje.py. Si Bedrock falla, devuelve una explicación por plantilla
para que el demo nunca se caiga.
Variables de entorno: MODEL_ID (obligatoria para usar Bedrock), BEDROCK_REGION (opcional).
"""
import json
import os

PROMPT_SISTEMA = """Eres un asistente de gestión de listas de espera de un hospital público chileno.
Redactas para un gestor de salud y el equipo clínico.

Reglas estrictas:
- Usa SOLO los datos entregados. No inventes síntomas, exámenes, fechas ni diagnósticos.
- No decides la prioridad ni recomiendas tratamientos: explicas por qué el sistema propone esa categoría.
- Máximo 3 frases cortas, en español de Chile, sin markdown ni viñetas.
- Menciona el evento que cambió la categoría (con su fecha) y la fuente oficial que se aplicó, si las hay.
- Termina siempre con: "Propuesta sujeta a validación clínica."
"""


def _datos(p):
    return {
        "edad": p.get("edad"),
        "especialidad": p.get("especialidad"),
        "diagnostico": f'{p.get("diagnostico_cie10")} {p.get("diagnostico_texto")}',
        "prioridad_inicial": p.get("prioridad_inicial"),
        "categoria": p.get("categoria"),
        "estado_clinico": p.get("estado_clinico"),
        "posicion_actual": p.get("posicion"),
        "posicion_hace_14_dias": p.get("posicion_anterior"),
        "riesgo_inasistencia": p.get("riesgo_inasistencia"),
        "evaluacion_descompensacion": p.get("evaluacion"),
        "razones": p.get("razones"),
    }


def plantilla(p):
    rz = {r["factor"]: r for r in p.get("razones", [])}
    partes = [f'Prioridad {p.get("categoria")} para {p.get("diagnostico_texto")} '
              f'(inicial {p.get("prioridad_inicial")}).']
    if "evento" in rz:
        partes.append(f'Evento posterior a la interconsulta: {rz["evento"]["valor"]}.')
    if "tabla_oficial" in rz:
        partes.append(f'Según {rz["tabla_oficial"]["fuente"]}: {rz["tabla_oficial"]["valor"]}.')
    if "riesgo_vital" in rz:
        partes.append(f'{rz["riesgo_vital"]["valor"]}.')
    if p.get("antiguedad_mayor_1_anio"):
        partes.append("Lleva más de 1 año en lista (criterio MINSAL).")
    if "ges" in rz and (p.get("ges") or {}).get("vencida"):
        partes.append(f'{rz["ges"]["valor"]}.')
    if p.get("riesgo_inasistencia"):
        partes.append("Tiene 2 inasistencias consecutivas: confirmar asistencia por teléfono.")
    return " ".join(partes) + " Propuesta sujeta a validación clínica."


def explicar(paciente):
    """Devuelve (texto, fuente) donde fuente es 'bedrock' o 'plantilla'."""
    model_id = os.environ.get("MODEL_ID")
    if not model_id:
        return plantilla(paciente), "plantilla"
    try:
        import boto3
        kw = {"region_name": os.environ["BEDROCK_REGION"]} if os.environ.get("BEDROCK_REGION") else {}
        client = boto3.client("bedrock-runtime", **kw)
        r = client.converse(
            modelId=model_id,
            system=[{"text": PROMPT_SISTEMA}],
            messages=[{"role": "user", "content": [{"text": "Datos del paciente:\n" + json.dumps(_datos(paciente), ensure_ascii=False)}]}],
            inferenceConfig={"maxTokens": 300},  # los modelos Claude recientes no aceptan 'temperature'
        )
        texto = r["output"]["message"]["content"][0]["text"].strip()
        if "validación clínica" not in texto:
            texto += " Propuesta sujeta a validación clínica."
        return texto, "bedrock"
    except Exception as e:
        print(f"Bedrock falló, uso plantilla: {e}")
        return plantilla(paciente), "plantilla"
