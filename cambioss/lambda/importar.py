"""Importación de Excel (.xlsx) o CSV al formato del sistema (perfiles + agenda de box).

Sin librerías externas: un .xlsx es un ZIP con XML, se lee con zipfile + xml.etree de Python.
1) Lee cada archivo (cada hoja de un Excel es una tabla).
2) Reconoce los encabezados aunque vengan con otro nombre, mayúsculas, tildes o espacios.
3) Detecta qué tabla es (pacientes, lista de espera, eventos, mediciones, citaciones, agenda de box).
4) Normaliza fechas, booleanos y categorías, y valida cada fila contra el vocabulario del registro.
Devuelve un informe por tabla (filas válidas, errores con N° de fila, columnas mapeadas) y las filas listas.
"""
import base64
import csv
import io
import re
import unicodedata
import zipfile
from datetime import date, datetime, timedelta
from xml.etree import ElementTree as ET

# ---------- tablas del registro (diccionario_datos.md) ----------
TABLAS = {
    "pacientes": {"nombre": "Pacientes", "requeridas": ["id_paciente", "edad", "sexo"],
                  "campos": ["id_paciente", "nombre_fantasia", "edad", "sexo", "comuna", "prevision", "nivel_socioeconomico",
                             "fallecido", "fecha_defuncion", "grupo_proteccion", "acg"]},
    "lista_espera": {"nombre": "Lista de espera", "requeridas": ["id_paciente", "diagnostico_cie10", "prioridad_inicial", "fecha_ingreso_lista"],
                     "campos": ["id_paciente", "id_solicitud", "especialidad", "sub_especialidad", "diagnostico_cie10", "diagnostico_texto",
                                "prioridad_inicial", "fecha_ingreso_lista", "origen_derivacion", "estado"]},
    "eventos_clinicos": {"nombre": "Eventos clínicos", "requeridas": ["id_paciente", "fecha_evento", "tipo_evento"],
                         "campos": ["id_paciente", "id_evento", "fecha_evento", "tipo_evento", "subtipo", "severidad", "detalle"]},
    "mediciones": {"nombre": "Mediciones", "requeridas": ["id_paciente", "fecha_medicion", "tipo_medicion", "valor"],
                   "campos": ["id_paciente", "fecha_medicion", "tipo_medicion", "valor", "unidad", "fuera_de_rango"]},
    "citaciones": {"nombre": "Citaciones", "requeridas": ["id_paciente", "fecha_cita", "estado_cita"],
                   "campos": ["id_paciente", "id_cita", "id_box", "fecha_cita", "especialidad", "estado_cita", "minutos_atencion_real"]},
    "agenda_box": {"nombre": "Agenda de box", "requeridas": ["id_box", "fecha", "especialidad", "capacidad_cupos"],
                   "campos": ["id_box", "fecha", "especialidad", "bloque_inicio", "bloque_fin", "capacidad_cupos", "cupos_usados",
                              "minutos_sobretiempo"]},
}

# Otros nombres con que suelen venir las columnas (ya normalizados: minúsculas, sin tildes, "_" en vez de espacios)
SINONIMOS = {
    "id_paciente": ["id", "paciente", "id_pac", "codigo_paciente", "rut", "run", "rut_paciente", "n_paciente", "ficha"],
    "nombre_fantasia": ["nombre", "nombre_paciente", "nombres", "nombre_completo", "paciente_nombre"],
    "edad": ["anos", "edad_anos"],
    "sexo": ["genero", "sexo_registral"],
    "prevision": ["prevision_salud", "seguro", "aseguradora"],
    "nivel_socioeconomico": ["nse", "nivel_socio_economico"],
    "fallecido": ["falleci", "defuncion", "fallecido_si_no"],
    "fecha_defuncion": ["fecha_fallecimiento", "f_defuncion", "fecha_muerte"],
    "grupo_proteccion": ["grupo_especial", "grupo_especial_proteccion", "prais", "programa_proteccion"],
    "acg": ["estratificacion", "estratificacion_acg", "riesgo_acg", "acg_riesgo", "grupo_riesgo"],
    "id_solicitud": ["sic", "id_sic", "interconsulta", "n_interconsulta", "folio", "id_ic"],
    "especialidad": ["especialidad_destino", "servicio", "esp"],
    "sub_especialidad": ["subespecialidad", "sub_esp"],
    "diagnostico_cie10": ["cie10", "cie_10", "codigo_cie10", "cod_diagnostico", "diagnostico_codigo", "codigo_diagnostico", "dg_cie10"],
    "diagnostico_texto": ["diagnostico", "glosa_diagnostico", "descripcion_diagnostico", "hipotesis_diagnostica", "dg"],
    "prioridad_inicial": ["prioridad", "priorizacion", "prioridad_clinica", "categoria"],
    "fecha_ingreso_lista": ["fecha_ingreso", "f_ingreso", "fecha_sic", "fecha_emision", "fecha_derivacion", "ingreso"],
    "origen_derivacion": ["origen", "derivado_desde", "procedencia", "establecimiento_origen"],
    "estado": ["estado_lista", "estado_sic"],
    "id_evento": ["evento_id"],
    "fecha_evento": ["fecha", "f_evento"],
    "tipo_evento": ["tipo", "evento"],
    "subtipo": ["sub_tipo", "detalle_tipo", "motivo"],
    "severidad": ["gravedad"],
    "detalle": ["descripcion", "observacion", "observaciones", "comentario"],
    "fecha_medicion": ["fecha", "f_medicion", "fecha_examen"],
    "tipo_medicion": ["medicion", "examen", "parametro", "tipo"],
    "valor": ["resultado", "valor_medicion"],
    "unidad": ["unidades", "um"],
    "fuera_de_rango": ["alterado", "fuera_rango", "anormal"],
    "id_cita": ["cita", "cita_id"],
    "id_box": ["box", "n_box", "sala", "box_atencion"],
    "fecha_cita": ["fecha", "f_cita", "fecha_hora_cita", "fecha_citacion"],
    "estado_cita": ["estado", "resultado_cita", "asistencia"],
    "minutos_atencion_real": ["minutos_atencion", "duracion", "duracion_min"],
    "bloque_inicio": ["inicio", "hora_inicio"],
    "bloque_fin": ["fin", "termino", "hora_fin", "hora_termino"],
    "capacidad_cupos": ["capacidad", "cupos", "cupos_totales", "cupos_ofertados"],
    "cupos_usados": ["usados", "ocupados", "cupos_ocupados", "atendidos"],
    "minutos_sobretiempo": ["sobretiempo", "atraso", "minutos_atraso"],
}

VOCAB = {
    "sexo": {"f": "F", "femenino": "F", "mujer": "F", "m": "M", "masculino": "M", "hombre": "M"},
    "prioridad_inicial": {"alta": "alta", "a": "alta", "1": "alta", "inmediata": "alta", "prioritaria": "alta",
                          "media": "media", "mediana": "media", "m": "media", "2": "media",
                          "baja": "baja", "b": "baja", "3": "baja"},
    "tipo_evento": {"visita_urgencia": "visita_urgencia", "urgencia": "visita_urgencia", "consulta_urgencia": "visita_urgencia",
                    "hospitalizacion": "hospitalizacion", "hospitalizado": "hospitalizacion", "ingreso_hospitalario": "hospitalizacion",
                    "examen_alterado": "examen_alterado", "examen": "examen_alterado", "cambio_farmaco": "cambio_farmaco",
                    "cambio_de_farmaco": "cambio_farmaco", "farmaco": "cambio_farmaco", "control_aps": "control_aps", "control": "control_aps"},
    "severidad": {"leve": "leve", "moderada": "moderada", "moderado": "moderada", "grave": "grave", "severa": "grave", "severo": "grave"},
    "estado_cita": {"asistio": "asistio", "si": "asistio", "atendido": "asistio", "no_asistio": "no_asistio", "no": "no_asistio",
                    "nsp": "no_asistio", "inasistencia": "no_asistio", "reprogramo": "reprogramo", "reprogramada": "reprogramo",
                    "cancelo": "cancelo", "cancelada": "cancelo"},
    "estado": {"en_espera": "en_espera", "espera": "en_espera", "citado": "citado", "atendido": "atendido",
               "egresado": "egresado", "fallecido": "fallecido"},
    "grupo_proteccion": {"prais": "PRAIS", "si": "PRAIS", "nna": "NNA bajo protección del Estado", "nna_bajo_proteccion_del_estado":
                         "NNA bajo protección del Estado", "mejor_ninez": "NNA bajo protección del Estado", "sename": "NNA bajo protección del Estado",
                         "valech": "Valech", "rettig": "Rettig"},
    "acg": {"g0": "G0", "g1": "G1", "g2": "G2", "g3": "G3", "0": "G0", "1": "G1", "2": "G2", "3": "G3"},
}
SI = {"si", "s", "true", "verdadero", "1", "x", "yes"}
NO = {"no", "n", "false", "falso", "0", "", "none"}


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().strip().lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


# ---------- lectura de archivos ----------
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


def _col(ref):
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group():
        n = n * 26 + ord(ch) - 64
    return n - 1


def leer_xlsx(datos):
    """Devuelve [(nombre_hoja, filas)] con filas como listas de valores (texto o número)."""
    z = zipfile.ZipFile(io.BytesIO(datos))
    compartidos = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
            compartidos.append("".join(t.text or "" for t in si.iter("{%s}t" % NS["m"])))
    libro = ET.fromstring(z.read("xl/workbook.xml"))
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    hojas = []
    for h in libro.find("m:sheets", NS):
        destino = rels[h.get("{%s}id" % NS["r"])].lstrip("/")
        ruta = destino if destino.startswith("xl/") else "xl/" + destino
        filas = []
        for fila in ET.fromstring(z.read(ruta)).iter("{%s}row" % NS["m"]):
            valores = {}
            for c in fila.findall("m:c", NS):
                t, v = c.get("t"), c.find("m:v", NS)
                if t == "s" and v is not None:
                    val = compartidos[int(v.text)]
                elif t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter("{%s}t" % NS["m"]))
                elif t == "b" and v is not None:
                    val = "si" if v.text == "1" else "no"
                elif v is not None:
                    val = float(v.text) if re.fullmatch(r"-?\d+(\.\d+)?(E-?\d+)?", v.text or "") else v.text
                else:
                    val = ""
                valores[_col(c.get("r"))] = val
            if valores:
                filas.append([valores.get(i, "") for i in range(max(valores) + 1)])
        hojas.append((h.get("name"), filas))
    return hojas


def leer_csv(datos):
    for enc in ("utf-8-sig", "latin-1"):
        try:
            texto = datos.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    muestra = texto[:4096]
    delim = ";" if muestra.count(";") > muestra.count(",") else ("\t" if muestra.count("\t") > muestra.count(",") else ",")
    return [("hoja", [r for r in csv.reader(io.StringIO(texto), delimiter=delim)])]


def leer(nombre, contenido_b64):
    datos = base64.b64decode(contenido_b64)
    if nombre.lower().endswith((".xlsx", ".xlsm")) or datos[:2] == b"PK":
        return leer_xlsx(datos)
    return leer_csv(datos)


# ---------- conversión de valores ----------
def a_fecha(v):
    if v in ("", None):
        return None
    if isinstance(v, float) or re.fullmatch(r"\d{5}(\.\d+)?", str(v)):  # fecha interna de Excel
        return (date(1899, 12, 30) + timedelta(days=int(float(v)))).isoformat()
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%d.%m.%Y", "%d-%m-%y", "%d/%m/%y"):
        try:
            return datetime.strptime(s[:10] if fmt.startswith("%Y") else s.split(" ")[0], fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"fecha no reconocida: '{v}'")


def a_entero(v):
    if v in ("", None):
        return None
    return int(round(float(str(v).replace(",", "."))))


def a_numero(v):
    return float(str(v).replace(",", "."))


def a_bool(v):
    s = norm(v)
    if s in SI:
        return True
    if s in NO:
        return False
    raise ValueError(f"valor sí/no no reconocido: '{v}'")


def a_vocab(campo, v):
    s = norm(v)
    if s in VOCAB[campo]:
        return VOCAB[campo][s]
    raise ValueError(f"{campo} no reconocido: '{v}' (válidos: {', '.join(sorted(set(VOCAB[campo].values())))})")


def a_id_paciente(v):
    s = str(v).strip()
    if isinstance(v, float) and v.is_integer():
        s = str(int(v))
    return s


CONVERSORES = {
    "edad": a_entero, "capacidad_cupos": a_entero, "cupos_usados": a_entero, "minutos_sobretiempo": a_entero,
    "minutos_atencion_real": a_entero, "valor": a_numero,
    "fallecido": a_bool, "fuera_de_rango": a_bool,
    "fecha_defuncion": a_fecha, "fecha_ingreso_lista": a_fecha, "fecha_evento": a_fecha, "fecha_medicion": a_fecha,
    "fecha_cita": a_fecha, "fecha": a_fecha,
    "sexo": lambda v: a_vocab("sexo", v), "prioridad_inicial": lambda v: a_vocab("prioridad_inicial", v),
    "tipo_evento": lambda v: a_vocab("tipo_evento", v), "severidad": lambda v: a_vocab("severidad", v),
    "estado_cita": lambda v: a_vocab("estado_cita", v), "estado": lambda v: a_vocab("estado", v),
    "grupo_proteccion": lambda v: None if norm(v) in NO else a_vocab("grupo_proteccion", v),
    "acg": lambda v: a_vocab("acg", str(int(v)) if isinstance(v, float) else v),
    "id_paciente": a_id_paciente,
    "diagnostico_cie10": lambda v: str(v).strip().upper().split(".")[0][:3],
}


# ---------- mapeo de columnas y detección de tabla ----------
def mapear(encabezados, tabla):
    """{índice de columna: campo} usando nombre exacto o sinónimos."""
    campos = TABLAS[tabla]["campos"]
    out, usados = {}, set()
    for i, h in enumerate(encabezados):
        n = norm(h)
        if n in campos and n not in usados:
            out[i] = n; usados.add(n)
    for i, h in enumerate(encabezados):
        if i in out:
            continue
        n = norm(h)
        for campo in campos:
            if campo not in usados and n in SINONIMOS.get(campo, []):
                out[i] = campo; usados.add(campo)
                break
    return out


def detectar(encabezados, nombre=""):
    """La tabla cuyas columnas requeridas calzan mejor; el nombre del archivo/hoja desempata."""
    mejor, puntaje = None, -1
    n_arch = norm(nombre)
    for t, info in TABLAS.items():
        m = set(mapear(encabezados, t).values())
        if not all(r in m for r in info["requeridas"]):
            continue
        s = len(m) + (5 if t in n_arch or norm(info["nombre"]) in n_arch else 0)
        if s > puntaje:
            mejor, puntaje = t, s
    return mejor


def procesar(archivos):
    """archivos: [{"nombre", "contenido_base64"}] → (informe, datos por tabla)."""
    informe, datos = [], {t: [] for t in TABLAS}
    for a in archivos:
        try:
            hojas = leer(a["nombre"], a["contenido_base64"])
        except Exception as e:
            informe.append({"archivo": a["nombre"], "hoja": None, "tabla": None, "error": f"No se pudo leer el archivo: {e}"})
            continue
        for hoja, filas in hojas:
            filas = [f for f in filas if any(str(x).strip() for x in f)]
            if not filas:
                continue
            enc = filas[0]
            tabla = detectar(enc, f'{a["nombre"]} {hoja}')
            item = {"archivo": a["nombre"], "hoja": hoja, "tabla": tabla, "nombre_tabla": TABLAS[tabla]["nombre"] if tabla else None,
                    "filas": len(filas) - 1, "validas": 0, "errores": [], "columnas": [], "ignoradas": []}
            if not tabla:
                item["error"] = ("No se reconoció qué tabla es. Debe traer al menos las columnas de alguna tabla: " +
                                 "; ".join(f'{v["nombre"]}: {", ".join(v["requeridas"])}' for v in TABLAS.values()))
                informe.append(item)
                continue
            m = mapear(enc, tabla)
            item["columnas"] = [{"original": str(enc[i]), "campo": c} for i, c in sorted(m.items())]
            item["ignoradas"] = [str(h) for i, h in enumerate(enc) if i not in m and str(h).strip()]
            for n_fila, f in enumerate(filas[1:], start=2):
                reg, problemas = {}, []
                for i, campo in m.items():
                    v = f[i] if i < len(f) else ""
                    try:
                        reg[campo] = CONVERSORES[campo](v) if campo in CONVERSORES and v not in ("", None) else (
                            None if v in ("", None) else str(v).strip())
                    except (ValueError, TypeError) as e:
                        problemas.append(str(e))
                faltan = [r for r in TABLAS[tabla]["requeridas"] if reg.get(r) in (None, "")]
                if faltan:
                    problemas.append("falta " + ", ".join(faltan))
                if problemas:
                    if len(item["errores"]) < 15:
                        item["errores"].append({"fila": n_fila, "motivo": "; ".join(problemas)})
                    item.setdefault("n_errores", 0)
                    item["n_errores"] += 1
                    continue
                datos[tabla].append(reg)
                item["validas"] += 1
            informe.append(item)
    return informe, datos


# Rangos normales de referencia del diccionario de datos (para calcular fuera_de_rango si no viene)
RANGOS = {"presion_sistolica": (90, 139), "presion_diastolica": (60, 89), "HbA1c": (4.0, 6.4), "glicemia": (70, 140),
          "saturacion_o2": (95, 100), "peak_flow": (350, 600), "escala_dolor_eva": (0, 3), "PHQ9": (0, 9)}
TIPO_MEDICION = {"presion_sistolica": "presion_sistolica", "pas": "presion_sistolica", "pa_sistolica": "presion_sistolica",
                 "presion_diastolica": "presion_diastolica", "pad": "presion_diastolica", "pa_diastolica": "presion_diastolica",
                 "hba1c": "HbA1c", "hemoglobina_glicosilada": "HbA1c", "glicemia": "glicemia", "glucosa": "glicemia",
                 "saturacion_o2": "saturacion_o2", "saturacion": "saturacion_o2", "sato2": "saturacion_o2", "spo2": "saturacion_o2",
                 "peak_flow": "peak_flow", "pef": "peak_flow", "escala_dolor_eva": "escala_dolor_eva", "eva": "escala_dolor_eva",
                 "dolor_eva": "escala_dolor_eva", "phq9": "PHQ9", "phq_9": "PHQ9"}


def combinar(datos, existentes, catalogo):
    """Une lo importado con los perfiles existentes (sin duplicar). Devuelve (perfiles_tocados, agenda, resumen, avisos)."""
    import copy
    perfs, avisos = {}, []
    res = {"pacientes_nuevos": 0, "pacientes_actualizados": 0, "eventos": 0, "mediciones": 0, "citaciones": 0, "bloques_agenda": 0}

    def perfil(pid, crear=False):
        if pid in perfs:
            return perfs[pid]
        if pid in existentes:
            perfs[pid] = copy.deepcopy(existentes[pid]); res["pacientes_actualizados"] += 1
            return perfs[pid]
        if crear:
            perfs[pid] = {"id_paciente": pid, "paciente": {}, "lista_espera": {}, "eventos_clinicos": [], "mediciones": [], "citaciones": []}
            res["pacientes_nuevos"] += 1
            return perfs[pid]
        return None

    for r in datos["pacientes"]:
        p = perfil(r["id_paciente"], crear=True)
        p["paciente"].update({k: v for k, v in r.items() if k != "id_paciente" and v is not None})
    for r in datos["lista_espera"]:
        p = perfil(r["id_paciente"], crear=True)
        le = {k: v for k, v in r.items() if k != "id_paciente" and v is not None}
        dx = catalogo.get(le.get("diagnostico_cie10"))
        if dx:
            for k in ("especialidad", "sub_especialidad", "diagnostico_texto"):
                le.setdefault(k, dx[k])
        p["lista_espera"].update(le)
    for pid, p in list(perfs.items()):  # completar y validar pacientes nuevos
        pa, le = p["paciente"], p["lista_espera"]
        pa.setdefault("nombre_fantasia", pid); pa.setdefault("comuna", ""); pa.setdefault("prevision", "")
        pa.setdefault("nivel_socioeconomico", ""); pa.setdefault("fallecido", bool(pa.get("fecha_defuncion")))
        pa.setdefault("fecha_defuncion", None)
        le.setdefault("id_solicitud", "IC-" + pid); le.setdefault("sub_especialidad", le.get("especialidad", ""))
        le.setdefault("diagnostico_texto", le.get("diagnostico_cie10", "")); le.setdefault("origen_derivacion", "")
        le.setdefault("estado", "fallecido" if pa["fallecido"] else "en_espera")
        falta = [c for c in ("edad", "sexo") if pa.get(c) is None] + \
                [c for c in ("especialidad", "diagnostico_cie10", "prioridad_inicial", "fecha_ingreso_lista") if not le.get(c)]
        if falta:
            avisos.append(f"{pid}: no se puede ingresar a la lista, falta {', '.join(falta)} (venga en Pacientes / Lista de espera)")
            del perfs[pid]; res["pacientes_nuevos"] -= 1

    def agregar(tabla, clave_lista, clave, nuevo):
        sin = 0
        for r in datos[tabla]:
            p = perfil(r["id_paciente"])
            if not p:
                sin += 1
                continue
            item = nuevo(r, p)
            if item is not None and clave(item) not in {clave(x) for x in p[clave_lista]}:
                p[clave_lista].append(item); res[tabla if tabla != "eventos_clinicos" else "eventos"] += 1
        if sin:
            avisos.append(f"{TABLAS[tabla]['nombre']}: {sin} fila(s) de pacientes que no están en la lista ni en el archivo de pacientes")

    def nuevo_evento(r, p):
        """Normaliza el subtipo al vocabulario del registro y toma la severidad que le corresponde (no la del archivo):
        así una hospitalización importada sin severidad igual cuenta como descompensación."""
        from informe import candidatos_por_reglas
        from modelos import SUBTIPOS
        tipo, sub = r["tipo_evento"], (r.get("subtipo") or "").strip()
        vocab = SUBTIPOS[tipo]
        if sub not in vocab:
            sub = next((sk for sk in vocab if norm(sk) == norm(sub)), None) or next(
                (c["subtipo"] for c in candidatos_por_reglas(f'{sub}. {r.get("detalle") or ""}') if c["tipo_evento"] == tipo), None)
        if sub is None:
            sub = {"hospitalizacion": "ingreso hospitalario", "control_aps": "control"}.get(tipo)
        if sub is None:
            avisos.append(f'{r["id_paciente"]} {r["fecha_evento"]}: no se reconoció el subtipo "{r.get("subtipo")}" de {tipo}; '
                          f'use uno de: {", ".join(vocab)}')
            return None
        return {"id_evento": r.get("id_evento") or f'EV-IMP-{r["id_paciente"]}-{r["fecha_evento"]}-{tipo}-{sub}',
                "fecha_evento": r["fecha_evento"], "tipo_evento": tipo, "subtipo": sub, "severidad": vocab[sub],
                "detalle": r.get("detalle") or ""}

    agregar("eventos_clinicos", "eventos_clinicos", lambda e: (e["fecha_evento"], e["tipo_evento"], e["subtipo"]), nuevo_evento)

    def nueva_medicion(r, p):
        tipo = TIPO_MEDICION.get(norm(r["tipo_medicion"]), r["tipo_medicion"])
        fuera = r.get("fuera_de_rango")
        if fuera is None and tipo in RANGOS:
            fuera = not (RANGOS[tipo][0] <= r["valor"] <= RANGOS[tipo][1])
        return {"fecha_medicion": r["fecha_medicion"], "tipo_medicion": tipo, "valor": r["valor"],
                "unidad": r.get("unidad") or "", "fuera_de_rango": bool(fuera)}
    agregar("mediciones", "mediciones", lambda m: (m["fecha_medicion"], m["tipo_medicion"], m["valor"]), nueva_medicion)
    agregar("citaciones", "citaciones", lambda c: (c["fecha_cita"], c["id_box"], c["estado_cita"]),
            lambda r, p: {"id_cita": r.get("id_cita") or "", "id_box": r.get("id_box") or "", "fecha_cita": r["fecha_cita"],
                          "especialidad": r.get("especialidad") or p["lista_espera"].get("especialidad", ""),
                          "estado_cita": r["estado_cita"], "minutos_atencion_real": r.get("minutos_atencion_real")})

    agenda = []
    for r in datos["agenda_box"]:
        agenda.append({"fecha": r["fecha"], "id_box": r["id_box"], "especialidad": r["especialidad"],
                       "bloque": f'{r.get("bloque_inicio") or ""}-{r.get("bloque_fin") or ""}'.strip("-"),
                       "capacidad": r["capacidad_cupos"], "usados": r.get("cupos_usados") or 0,
                       "sobretiempo_min": r.get("minutos_sobretiempo") or 0})
    res["bloques_agenda"] = len(agenda)
    return perfs, agenda, res, avisos


def plantilla_csv(tabla):
    """Encabezados + una fila de ejemplo, separados por ';' para que Excel en español los abra en columnas."""
    ejemplos = {
        "pacientes": ["PAC-0001", "Juan Pérez", "64", "M", "La Florida", "FONASA B", "medio", "no", "", "PRAIS", "G3"],
        "lista_espera": ["PAC-0001", "IC-0001", "Cardiología", "Cardiología adulto", "I50", "Insuficiencia cardíaca", "media",
                         "15-03-2026", "CESFAM/APS", "en_espera"],
        "eventos_clinicos": ["PAC-0001", "EV-0001", "02-10-2026", "hospitalizacion", "ingreso hospitalario", "grave", "Descompensación IC"],
        "mediciones": ["PAC-0001", "02-10-2026", "presion_sistolica", "165", "mmHg", "si"],
        "citaciones": ["PAC-0001", "CT-0001", "BOX-12", "21-09-2026", "Cardiología", "no_asistio", ""],
        "agenda_box": ["BOX-12", "13-10-2026", "Cardiología", "08:30", "13:30", "10", "7", "0"],
    }
    return "﻿" + ";".join(TABLAS[tabla]["campos"]) + "\n" + ";".join(ejemplos[tabla]) + "\n"
