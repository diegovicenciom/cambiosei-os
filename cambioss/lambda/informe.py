"""Lectura de informes médicos (epicrisis, DAU de urgencia, nota clínica) escritos o fotografiados.

Camino principal, determinístico (sin IA generativa):
  1. Foto → Amazon Textract (OCR): texto + confianza de cada línea.
  2. Reglas de palabras clave con detección de negaciones (estilo NegEx) → TODOS los eventos candidatos.
  3. Pydantic (modelos.py) valida cada candidato contra el vocabulario del registro y contra el documento.
  4. El equipo clínico elige y confirma; recién ahí se recalcula la lista.
Respaldo opcional: si las reglas no encuentran nada y hay MODEL_ID, Amazon Bedrock sugiere un evento que pasa por la
MISMA validación y se marca "sugerido por IA: verificar".
"""
import base64
import json
import os
import re
from datetime import date

from pydantic import ValidationError

from modelos import SUBTIPOS, EventoPropuesto, Lectura, LineaLeida, normalizar

# Palabras clave → evento del registro, de lo más grave a lo menos grave
PATRONES = [
    (r"\bUCI\b|\bUTI\b|cuidados intensivos|unidad de paciente cr[ií]tico|\bUPC\b", "hospitalizacion", "ingreso UCI"),
    (r"hospitaliz|se ingresa a (sala|servicio|medicina|cirug|pensionado|hospital)|ingres[oó] a (sala|servicio)|qued[oó] internad",
     "hospitalizacion", "ingreso hospitalario"),
    (r"descompensaci[oó]n grave|descompensad[oa] grave|grave descompensaci", "visita_urgencia", "descompensación grave"),
    (r"\bESI\s*:?\s*2\b|categorizaci[oó]n\s*:?\s*C?2\b|\bC2\b(?=.*(urgencia|categoriz|triage))", "visita_urgencia", "triage ESI 2"),
    (r"descompensa", "visita_urgencia", "descompensación"),
    (r"examen(es)? alterad|resultado(s)? alterad|alterad[oa]s? (el |la |los |las )?(examen|ex[aá]menes|laboratorio)",
     "examen_alterado", "resultado alterado"),
    (r"aument[oóa]\w* (de )?(la )?dosis|sube (la )?dosis|se aumenta", "cambio_farmaco", "aumento dosis"),
    (r"reduc\w* (de )?(la )?dosis|baja (la )?dosis|se disminuye", "cambio_farmaco", "reducción dosis"),
    (r"estabiliz", "control_aps", "estabilización"),
    (r"buena respuesta|responde bien|mejor[ií]a", "control_aps", "buena respuesta"),
]

# Negación en español (estilo NegEx, Chapman 2001; NegEx-MES / SpRadNeg): palabras previas en la misma frase
NEGACION = re.compile(r"\b(no|sin|niega|negativo|negativa|descarta|descartad[oa]|se\s+descarta|ausencia\s+de|no\s+presenta|"
                      r"no\s+requiere|no\s+amerita|no\s+se|tampoco|ni|evita|evitar|sin\s+necesidad\s+de)\b", re.IGNORECASE)
VENTANA_NEGACION = 6

FECHA = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b|\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\b")
LINEA_NACIMIENTO = re.compile(r"nac|edad|naci", re.IGNORECASE)


def _frase(texto, inicio, fin):
    a = max(texto.rfind(".", 0, inicio), texto.rfind("\n", 0, inicio)) + 1
    cands = [i for i in (texto.find(".", fin), texto.find("\n", fin)) if i != -1]
    return texto[a:min(cands) if cands else len(texto)].strip()


def _negado(texto, inicio):
    ini = max(texto.rfind(".", 0, inicio), texto.rfind("\n", 0, inicio), texto.rfind(";", 0, inicio)) + 1
    return bool(NEGACION.search(" ".join(texto[ini:inicio].split()[-VENTANA_NEGACION:])))


def _a_fecha(m):
    try:
        if m.group(1):
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return date(int(m.group(6)), int(m.group(5)), int(m.group(4)))
    except ValueError:
        return None


def _fecha_del_evento(texto, inicio):
    """Fecha del evento: la de la misma línea; si no, la de una línea 'Fecha:' que no sea de nacimiento."""
    ini = texto.rfind("\n", 0, inicio) + 1
    fin = texto.find("\n", inicio)
    linea = texto[ini:fin if fin != -1 else len(texto)]
    for m in FECHA.finditer(linea):
        if (f := _a_fecha(m)):
            return f
    for l in texto.splitlines():
        if LINEA_NACIMIENTO.search(l):
            continue
        if re.search(r"fecha|ingreso|atenci[oó]n", l, re.IGNORECASE):
            for m in FECHA.finditer(l):
                if (f := _a_fecha(m)):
                    return f
    return None


def candidatos_por_reglas(texto):
    """Todos los eventos no negados que aparecen, del más grave al menos grave (uno por subtipo)."""
    out, vistos = [], set()
    for patron, tipo, subtipo in PATRONES:
        for m in re.finditer(patron, texto, re.IGNORECASE):
            if (tipo, subtipo) in vistos or _negado(texto, m.start()):
                continue
            vistos.add((tipo, subtipo))
            f = _fecha_del_evento(texto, m.start())
            out.append({"tipo_evento": tipo, "subtipo": subtipo, "severidad": SUBTIPOS[tipo][subtipo],
                        "fecha_evento": f, "fecha_en_documento": f is not None,
                        "evidencia": _frase(texto, m.start(), m.end()), "detectado_por": "reglas"})
            break
    return out


# ---------- OCR: Amazon Textract ----------
def _region():
    return os.environ.get("TEXTRACT_REGION") or os.environ.get("BEDROCK_REGION") or os.environ.get("AWS_REGION") or "us-east-1"


def leer_foto(imagen_b64):
    """Foto → Lectura con el texto y la confianza de cada línea (Amazon Textract DetectDocumentText)."""
    import boto3
    r = boto3.client("textract", region_name=_region()).detect_document_text(Document={"Bytes": base64.b64decode(imagen_b64)})
    lineas = [LineaLeida(texto=b["Text"], confianza=round(b["Confidence"], 1)) for b in r["Blocks"] if b["BlockType"] == "LINE"]
    if not lineas:
        raise ValueError("no se encontró texto en la imagen")
    return Lectura(origen="foto", motor="textract", texto="\n".join(l.texto for l in lineas), lineas=lineas)


# ---------- Respaldo opcional: Amazon Bedrock ----------
PROMPT = """Lees informes médicos de un hospital público chileno. Extrae como máximo UN evento clínico, usando SOLO este
vocabulario: {vocab}
Responde SOLO un JSON: {{"tipo_evento": "...", "subtipo": "...", "evidencia": "frase textual copiada del informe"}}.
Si no hay ninguno responde {{"tipo_evento": null}}. Un hallazgo negado o descartado NO es un evento. No inventes."""


def sugerencia_bedrock(texto):
    model_id = os.environ.get("MODEL_ID")
    if not model_id:
        return None
    try:
        import boto3
        r = boto3.client("bedrock-runtime", region_name=_region()).converse(
            modelId=model_id, system=[{"text": PROMPT.format(vocab=json.dumps({t: list(s) for t, s in SUBTIPOS.items()}, ensure_ascii=False))}],
            messages=[{"role": "user", "content": [{"text": texto}]}], inferenceConfig={"maxTokens": 300})
        crudo = r["output"]["message"]["content"][0]["text"]
        ev = json.loads(crudo[crudo.find("{"): crudo.rfind("}") + 1])
        if not ev.get("tipo_evento") or ev.get("tipo_evento") not in SUBTIPOS or ev.get("subtipo") not in SUBTIPOS[ev["tipo_evento"]]:
            return None
        i = normalizar(texto).find(normalizar(ev.get("evidencia", "")))
        f = _fecha_del_evento(texto, i) if i >= 0 else None
        return {**ev, "severidad": SUBTIPOS[ev["tipo_evento"]][ev["subtipo"]], "fecha_evento": f,
                "fecha_en_documento": f is not None, "detectado_por": "bedrock"}
    except Exception as e:
        print(f"Bedrock no disponible: {e}")
        return None


# ---------- Análisis completo ----------
def analizar(lectura: Lectura, corte: date):
    """Devuelve (eventos válidos, descartados con motivo, advertencias). Ningún evento pasa sin validación Pydantic."""
    crudos = candidatos_por_reglas(lectura.texto)
    if not crudos and (s := sugerencia_bedrock(lectura.texto)):
        crudos = [s]
    validos, descartados, avisos = [], [], []
    for c in crudos:
        try:
            validos.append(EventoPropuesto.model_validate(c, context={"texto": lectura.texto, "corte": corte}))
        except ValidationError as e:
            descartados.append({"subtipo": c.get("subtipo"), "motivo": "; ".join(x["msg"].replace("Value error, ", "") for x in e.errors())})
    if not lectura.legible:
        avisos.append(f"Foto poco legible (confianza media {lectura.confianza_media}%): repita la foto con buena luz y el documento completo.")
    elif any(l.dudosa for l in lectura.lineas):
        avisos.append("Algunas líneas se leyeron con baja confianza: revíselas en el texto leído.")
    if any(not v.fecha_en_documento for v in validos):
        avisos.append("No se encontró la fecha del evento en el documento: se usa la fecha de hoy, verifíquela.")
    if any(v.detectado_por == "bedrock" for v in validos):
        avisos.append("Evento sugerido por IA (las reglas no encontraron uno): verifique con especial cuidado.")
    return validos, descartados, avisos
