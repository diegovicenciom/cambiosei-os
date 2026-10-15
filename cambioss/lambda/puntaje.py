"""Priorización clínica evolutiva HLF — solo reglas con fuente oficial (sin pesos inventados, sin LLM).

Capa 1 · Categoría (Alta / Media / Baja)
  - Base: la prioridad que asignó el especialista al leer la SIC (prioridad_inicial).
  - Si DESPUÉS de emitida la SIC el paciente se descompensa (evento posterior que el especialista no vio),
    la categoría sube a la fila "descompensada / no controlada" de la tabla oficial del HLF:
    SSMSO (2025) "Priorización diagnósticos especialidades médicas y odontológicas No GES", §11.1
    Hospital Dra. Eloísa Díaz Inzunza, págs. 84-111.
  - El sistema nunca baja una categoría solo: eso lo decide el equipo clínico (revisión con motivo).
Capa 2 · Orden dentro de la categoría — MINSAL Ord. C N°536 (21-03-2025), recogido en el Manual de Gestión
  de la Demanda SSMSO 2025 (RE 2679), pág. 13: 1) criterio médico (la categoría), 2) grupos de especial
  protección (el dataset no los trae), 3) antigüedad en lista > 1 año. Luego LACE (experimental, solo desempata)
  y orden de llegada (fecha de ingreso).
Capa 3 · Banderas (no cambian el orden)
  - Posible incumplimiento GES: verificar (el plazo corre desde un hito que el registro no trae).
  - Posible causal 8 "inasistencias reiteradas": 2 inasistencias consecutivas (Manual SSMSO, Anexo 4).
  - Última medición fuera de rango (rangos de referencia del diccionario de datos).
Exclusión: causal 9 "fallecimiento" (Manual SSMSO, Anexo 4) desde fecha_defuncion; atendidos salen de la lista.

Uso: python puntaje.py perfiles.json [fecha_corte AAAA-MM-DD]
"""
import json, sys
from datetime import date

FUENTE_TABLA = "Tabla SSMSO 2025, HLF"
ORDEN_CAT = {"alta": 3, "media": 2, "baja": 1}

# Fila oficial de la tabla del HLF que describe el diagnóstico descompensado / no controlado.
# cie10: (fila tal como aparece en el documento, prioridad oficial, página).
# Solo se incluyen filas cuyo texto expresa descompensación o falta de control. Los diagnósticos sin esa fila
# (I10 HTA, K21 ERGE, F32, F41, G43, E66, M17, M54, M75) mantienen su prioridad y quedan marcados para revisión.
FILA_DESCOMPENSADO = {
    "I50": ("Insuficiencia cardíaca descompensada", "alta", 85),
    "I20": ("Angina inestable", "alta", 85),
    "J44": ("EPOC grave no controlado", "alta", 95),
    "J45": ("Asma grave no controlada", "alta", 95),
    "K70": ("Cirrosis hepática descompensada", "alta", 95),
    "E11": ("DM2 descontrolada", "media", 101),
    "E03": ("Hipotiroidismo sintomático", "media", 94),
    "G40": ("Epilepsia con crisis mensuales (deja de ser 'epilepsia controlada', baja)", "media", 103),
}
# Equivalencias CIE-10 → fila de la tabla que son interpretación del equipo y deben validarse con el especialista.
EQUIVALENCIA_A_VALIDAR = {
    "K70": "K70 es enfermedad hepática alcohólica; se asimila a la fila de cirrosis",
    "I20": "I20 incluye toda angina de pecho; la fila oficial es solo angina inestable",
    "G40": "la tabla no tiene fila 'epilepsia descompensada'; se usa 'crisis mensuales'",
}
DIAS_EVALUACION = 3  # KPI del hospital: reevaluación clínica < 72 h tras un evento

# Garantía GES de oportunidad: atención por especialista (días). auge.minsal.cl/problemasdesalud/index/<N°>
# cie10: (N° problema GES, nombre, días, edad mínima)
GES_ESPECIALISTA = {
    "F32": (34, "Depresión", 30, 15),
    "I10": (21, "Hipertensión arterial", 45, 15),
    "J44": (38, "EPOC", 45, 0),
    "E11": (7, "Diabetes mellitus tipo 2", 60, 0),
    "J45": (61, "Asma bronquial", 60, 15),
    "G40": (60, "Epilepsia", 60, 15),
    "M17": (41, "Artrosis de rodilla", 120, 55),
}

DIAS_ANTIGUEDAD = 365  # MINSAL Ord. 536/2025: "antigüedad en la lista de espera mayor a un año"

# Índice LACE — van Walraven C, et al. CMAJ 2010;182(6):551-7, Tabla 3 (riesgo de muerte o reingreso no planificado).
# L: días de estada (el dataset no los trae → 0) · A: ingreso de urgencia = 3 · C: Charlson → 0,1,2,3, ≥4 = 5
# · E: consultas en urgencia en los 6 meses previos → 0,1,2,3, ≥4 = 4.
LACE_FUENTE = "Índice LACE (van Walraven et al., CMAJ 2010)"
LACE_VENTANA_DIAS = 182  # "previous 6 months" del índice LACE
# Pesos de Charlson usados por el índice LACE (nota de la Tabla 3); CIE-10 según Quan et al., Med Care 2005.
CHARLSON_LACE = {
    "I50": (2, "insuficiencia cardíaca congestiva"),
    "J44": (2, "enfermedad pulmonar crónica"),
    "J45": (2, "enfermedad pulmonar crónica"),
    "K70": (2, "enfermedad hepática leve"),
    "E11": (1, "diabetes sin complicaciones"),
}
# Condiciones de Charlson con su peso en el índice LACE (nota de la Tabla 3, van Walraven 2010), para registrar comorbilidades.
CONDICIONES_CHARLSON = [
    ("infarto agudo al miocardio", 1), ("enfermedad vascular periférica", 1), ("enfermedad cerebrovascular", 1),
    ("diabetes sin complicaciones", 1), ("insuficiencia cardíaca congestiva", 2), ("enfermedad pulmonar crónica", 2),
    ("enfermedad hepática leve", 2), ("cáncer", 2), ("demencia", 3), ("enfermedad del tejido conectivo", 3),
    ("enfermedad hepática moderada a severa", 4), ("infección por VIH", 4), ("cáncer metastásico", 6),
]
PESO_CHARLSON = dict(CONDICIONES_CHARLSON)


def charlson(perfil):
    """Suma de pesos Charlson (LACE) del diagnóstico de la SIC + comorbilidades registradas, cada condición una vez."""
    conds = {}
    peso, nombre = CHARLSON_LACE.get(perfil["lista_espera"]["diagnostico_cie10"], (0, None))
    if nombre:
        conds[nombre] = peso
    for c in perfil["paciente"].get("comorbilidades", []):
        if c.get("condicion") in PESO_CHARLSON:
            conds[c["condicion"]] = PESO_CHARLSON[c["condicion"]]
        elif c.get("cie10") in CHARLSON_LACE:
            p, n = CHARLSON_LACE[c["cie10"]]
            conds[n] = p
    return sum(conds.values()), conds


def indice_lace(perfil, corte):
    """Devuelve el desglose LACE con los eventos con fecha ≤ corte."""
    desde = corte.toordinal() - LACE_VENTANA_DIAS
    evs = [e for e in perfil.get("eventos_clinicos", []) if desde <= d(e["fecha_evento"]).toordinal() <= corte.toordinal()]
    hosp = [e for e in evs if e["tipo_evento"] == "hospitalizacion"]
    urg = sum(1 for e in evs if e["tipo_evento"] == "visita_urgencia")
    total_c, conds = charlson(perfil)
    cond = ", ".join(f"{n} ({p})" for n, p in conds.items())
    otras = [c.get("nombre") for c in perfil["paciente"].get("comorbilidades", []) if c.get("condicion") not in PESO_CHARLSON
             and c.get("cie10") not in CHARLSON_LACE]
    if otras:
        cond = (cond + "; " if cond else "") + "sin peso Charlson: " + ", ".join(otras)
    partes = [
        {"letra": "L", "nombre": "Días de estada", "valor": "sin dato en el registro", "puntos": 0},
        {"letra": "A", "nombre": "Ingreso de urgencia (6 meses)", "valor": f'{len(hosp)} hospitalización(es)' if hosp else "no", "puntos": 3 if hosp else 0},
        {"letra": "C", "nombre": "Comorbilidad (Charlson)", "valor": f"Charlson {total_c}: {cond}" if cond else "sin condición de Charlson",
         "puntos": total_c if total_c < 4 else 5},
        {"letra": "E", "nombre": "Consultas en urgencia (6 meses)", "valor": str(urg), "puntos": min(urg, 4)},
    ]
    return {"total": sum(p["puntos"] for p in partes), "partes": partes, "fuente": LACE_FUENTE, "experimental": True,
            "datos_faltantes": ["días de estada (L): no vienen en el registro",
                                "comorbilidades: solo el diagnóstico de la SIC y las registradas por el equipo"],
            "uso": "solo desempata dentro de la misma categoría, después de la antigüedad; validado para reingreso o "
                   "muerte tras alta hospitalaria, no para listas de espera"}


def d(s): return date.fromisoformat(s)


def descompensa(ev):
    """Evento que el propio dataset etiqueta como descompensación o severidad grave
    (urgencia ESI 2, descompensación, hospitalización, UCI)."""
    return ev.get("severidad") == "grave" or "descompensaci" in (ev.get("subtipo") or "").lower()


def estabiliza(ev):
    """Evento que el dataset etiqueta como estabilización o buena respuesta."""
    return ev.get("tipo_evento") == "control_aps" and ev.get("subtipo") in ("estabilización", "buena respuesta")


def senal_revision(ev):
    """Señal de deterioro que no cambia la categoría pero pide revisión del especialista (planteamiento del HLF:
    exámenes alterados y cambios en el tratamiento farmacológico que el especialista no ve al priorizar la SIC)."""
    if ev.get("tipo_evento") == "examen_alterado":
        return "examen alterado"
    if ev.get("tipo_evento") == "cambio_farmaco" and "aument" in (ev.get("subtipo") or "").lower():
        return "aumento de dosis"
    return None


GRUPOS_PROTECCION = {"PRAIS", "NNA bajo protección del Estado", "Valech", "Rettig"}  # MINSAL Ord. 536/2025, criterio 2
ACG_NIVELES = {"G0": "sin clasificación", "G1": "bajo riesgo", "G2": "riesgo intermedio", "G3": "alto riesgo"}  # SSMSO (PDF HLF §4)


def fecha_atencion(perfil):
    """Fecha en que se resolvió la SIC: registrada por el equipo o la primera cita a la que asistió."""
    le = perfil["lista_espera"]
    if le.get("fecha_atencion"):
        return le["fecha_atencion"]
    asistio = sorted(c["fecha_cita"] for c in perfil.get("citaciones", []) if c["estado_cita"] == "asistio")
    return asistio[0] if asistio else None


def inasistencias_consecutivas(citas):
    """Máximo de inasistencias en citas consecutivas (causal 8: 'dos inasistencias consecutivas').
    Cualquier otra cita entre medio (asistió, reprogramó, canceló) corta la racha."""
    racha = mejor = 0
    for c in sorted(citas, key=lambda c: c["fecha_cita"]):
        racha = racha + 1 if c["estado_cita"] == "no_asistio" else 0
        mejor = max(mejor, racha)
    return mejor


def puntuar(perfil, corte):
    pac, le = perfil["paciente"], perfil["lista_espera"]
    if pac.get("fallecido") and pac.get("fecha_defuncion") and d(pac["fecha_defuncion"]) <= corte:
        return {"id_paciente": perfil["id_paciente"], "excluido": True, "motivo": "fallecido", "fecha": pac["fecha_defuncion"], "razones": []}
    ingreso = d(le["fecha_ingreso_lista"])
    if ingreso > corte:
        return None  # aún no ingresaba a la lista
    if le.get("estado") == "atendido":  # sale de la lista solo desde la fecha de atención (principio de fecha de corte)
        fa = fecha_atencion(perfil)
        if not fa or d(fa) <= corte:
            return {"id_paciente": perfil["id_paciente"], "excluido": True, "motivo": "atendido", "fecha": fa, "razones": []}

    cie = le["diagnostico_cie10"]
    inicial = le["prioridad_inicial"]
    dias_espera = (corte - ingreso).days
    razones = [{"factor": "prioridad_inicial", "valor": f"{inicial} (asignada por el especialista al priorizar la SIC)",
                "fuente": "Priorización de la SIC (CUD / Thalamus)"}]

    # --- Capa 1: estado clínico posterior a la SIC --------------------------------
    eventos = sorted([e for e in perfil.get("eventos_clinicos", []) if ingreso <= d(e["fecha_evento"]) <= corte],
                     key=lambda e: e["fecha_evento"])
    ult_desc = next((e for e in reversed(eventos) if descompensa(e)), None)
    ult_estab = next((e for e in reversed(eventos) if estabiliza(e)), None)
    estado = "sin_cambios"
    if ult_desc:
        estado = "estabilizado" if ult_estab and ult_estab["fecha_evento"] > ult_desc["fecha_evento"] else "descompensado"
    elif ult_estab:
        estado = "estabilizado"

    categoria = inicial
    fila = FILA_DESCOMPENSADO.get(cie)
    # Riesgo vital: descompensación grave sin estabilización posterior, en un diagnóstico cuya fila oficial es Alta.
    # MINSAL prioriza primero la "criticidad / riesgo vital" (Ord. C27 N°373/2021, citado en SSMSO 2025 pág. 4)
    # y el "impacto en la progresión de la enfermedad y complicaciones" (Ord. 536/2025, criterio 1).
    riesgo_vital = bool(estado == "descompensado" and fila and fila[1] == "alta" and ult_desc["severidad"] == "grave")
    if ult_desc:
        razones.append({"factor": "evento", "valor": f'{ult_desc["tipo_evento"].replace("_", " ")}: {ult_desc["subtipo"]} '
                                                    f'({ult_desc["severidad"]}, {ult_desc["fecha_evento"]})',
                        "fuente": "Registro clínico posterior a la SIC"})
    validar = f' · equivalencia a validar: {EQUIVALENCIA_A_VALIDAR[cie]}' if cie in EQUIVALENCIA_A_VALIDAR else ""
    if estado == "descompensado":
        if fila and ORDEN_CAT[fila[1]] > ORDEN_CAT[inicial]:
            categoria = fila[1]
            razones.append({"factor": "tabla_oficial", "valor": f'"{fila[0]}" → prioridad {fila[1]}{validar}',
                            "fuente": f"{FUENTE_TABLA}, pág. {fila[2]}"})
        elif fila:
            razones.append({"factor": "tabla_oficial", "valor": f'"{fila[0]}" → prioridad {fila[1]} (no supera la actual){validar}',
                            "fuente": f"{FUENTE_TABLA}, pág. {fila[2]}"})
        else:
            razones.append({"factor": "tabla_oficial", "valor": "la tabla del HLF no tiene fila para este diagnóstico descompensado: "
                                                                "se mantiene la prioridad y se sugiere revisión clínica",
                            "fuente": FUENTE_TABLA})
    if riesgo_vital:
        razones.insert(0, {"factor": "riesgo_vital",
                           "valor": f'Descompensación grave ({fila[0]}) sin registro posterior de estabilización: su prioridad '
                                    f'debe revisarse dentro de 72 h desde que el evento llega al sistema; el especialista decide',
                           "fuente": "MINSAL: criticidad / riesgo vital (SSMSO 2025, pág. 4) · " f"{FUENTE_TABLA}, pág. {fila[2]}"})
    elif estado == "estabilizado":
        razones.append({"factor": "evento", "valor": f'{ult_estab["subtipo"]} ({ult_estab["fecha_evento"]}): '
                                                    "el sistema no baja la prioridad solo; puede ajustarla el equipo clínico",
                        "fuente": "Principio de diseño: la herramienta propone, el equipo clínico decide"})

    # --- LACE: componente EXPERIMENTAL (validado para muerte/reingreso tras alta hospitalaria, no para ordenar
    # consultas de especialidad). Solo desempata al final; datos faltantes (días de estada) se informan. ---
    lace = indice_lace(perfil, corte)
    if lace["total"]:
        razones.append({"factor": "lace", "valor": f'{lace["total"]} puntos (' + ", ".join(
            f'{p["letra"]} {p["puntos"]}' for p in lace["partes"] if p["puntos"]) + ") · experimental, solo desempata",
            "fuente": LACE_FUENTE + " — adaptado; requiere validación local"})

    # --- Capa 2: criterios de orden MINSAL ----------------------------------------
    antiguo = dias_espera > DIAS_ANTIGUEDAD
    razones.append({"factor": "dias_espera", "valor": f"{dias_espera} días en lista" + (" (más de 1 año)" if antiguo else ""),
                    "fuente": "MINSAL Ord. 536/2025: antigüedad > 1 año"})

    # --- Capa 3: banderas ---------------------------------------------------------
    # GES: la garantía corre desde un hito clínico (p. ej. la derivación con confirmación diagnóstica) que el registro
    # no trae; se usa el ingreso a la lista como aproximación → se informa "posible incumplimiento: verificar".
    ges = GES_ESPECIALISTA.get(cie)
    ges_info = None
    if ges and pac["edad"] >= ges[3]:
        vencida = dias_espera > ges[2]
        ges_info = {"problema": ges[0], "nombre": ges[1], "plazo_dias": ges[2], "vencida": vencida, "verificar": vencida}
        razones.append({"factor": "ges", "valor": f"GES N°{ges[0]} {ges[1]}: especialista en {ges[2]} días desde la derivación" +
                        (f" — posible incumplimiento: {dias_espera} días desde el ingreso a la lista (verificar el hito real)"
                         if vencida else ""),
                        "fuente": f"auge.minsal.cl, problema de salud N°{ges[0]}"})

    # Señales que piden revisión del especialista (no cambian el orden): fecha y momento de registro para compararlas
    # con la última revisión clínica.
    senales = [{"motivo": senal_revision(e), "fecha": e["fecha_evento"], "registrado": e.get("registrado")}
               for e in eventos if senal_revision(e)]
    if estado == "descompensado" and not fila:
        senales.append({"motivo": "descompensación sin fila oficial en la tabla HLF", "fecha": ult_desc["fecha_evento"],
                        "registrado": ult_desc.get("registrado")})
    if estado == "descompensado" and fila:
        senales.append({"motivo": "descompensación (prioridad ajustada por tabla HLF)", "fecha": ult_desc["fecha_evento"],
                        "registrado": ult_desc.get("registrado")})

    grupo = pac.get("grupo_proteccion") if pac.get("grupo_proteccion") in GRUPOS_PROTECCION else None
    if grupo:
        razones.append({"factor": "grupo_proteccion", "valor": grupo, "fuente": "MINSAL Ord. 536/2025, criterio 2: grupos de especial protección"})
    acg = pac.get("acg") if pac.get("acg") in ACG_NIVELES else None
    if acg:
        razones.append({"factor": "acg", "valor": f"{acg} · {ACG_NIVELES[acg]}", "fuente": "Estratificación de riesgo ACG (SSMSO, ficha Rayen)"})

    citas = [c for c in perfil.get("citaciones", []) if d(c["fecha_cita"]) <= corte]
    no_show = sum(1 for c in citas if c["estado_cita"] == "no_asistio")
    consecutivas = inasistencias_consecutivas(citas)

    meds = sorted([m for m in perfil.get("mediciones", []) if d(m["fecha_medicion"]) <= corte], key=lambda m: m["fecha_medicion"])
    ult_med = meds[-1] if meds else None
    medicion_alerta = bool(ult_med and ult_med["fuera_de_rango"])
    if medicion_alerta:
        razones.append({"factor": "medicion", "valor": f'{ult_med["tipo_medicion"]} = {ult_med["valor"]:g} {ult_med["unidad"]} '
                                                      f'fuera de rango ({ult_med["fecha_medicion"]})',
                        "fuente": "Rangos de referencia del diccionario de datos HLF"})

    return {"id_paciente": perfil["id_paciente"], "excluido": False, "categoria": categoria,
            "estado_clinico": estado, "riesgo_vital": riesgo_vital, "lace": lace, "antiguedad_mayor_1_anio": antiguo, "dias_espera": dias_espera,
            "ges": ges_info, "medicion_alerta": medicion_alerta, "senales": senales, "grupo_proteccion": grupo, "acg": acg,
            "fecha_descompensacion": ult_desc["fecha_evento"] if estado == "descompensado" else None,
            "dias_desde_descompensacion": (corte - d(ult_desc["fecha_evento"])).days if estado == "descompensado" else None,
            "registro_descompensacion": ult_desc.get("registrado") if estado == "descompensado" else None,
            "riesgo_inasistencia": consecutivas >= 2, "no_shows": no_show, "razones": razones}


def clave_orden(r, categoria=None):
    """MINSAL Ord. 536/2025: criterio médico (categoría y descompensación grave) → grupos de especial protección
    → antigüedad > 1 año → LACE (componente experimental, solo desempata) → orden de llegada."""
    return (-ORDEN_CAT[categoria or r["categoria"]], not r["riesgo_vital"], not r.get("grupo_proteccion"),
            not r["antiguedad_mayor_1_anio"], -r["lace"]["total"], -r["dias_espera"], r["id_paciente"])


def priorizar(perfiles, corte, especialidad=None):
    out = []
    for p in perfiles:
        if especialidad and p["lista_espera"]["especialidad"] != especialidad: continue
        r = puntuar(p, corte)
        if r: out.append(r)
    activos = sorted([r for r in out if not r["excluido"]], key=clave_orden)
    for i, r in enumerate(activos, 1): r["posicion"] = i
    return activos, [r for r in out if r["excluido"]]


if __name__ == "__main__":
    perfiles = json.load(open(sys.argv[1], encoding="utf-8"))
    corte = d(sys.argv[2]) if len(sys.argv) > 2 else date(2026, 10, 13)
    activos, excl = priorizar(perfiles, corte)
    print(f"corte {corte}: {len(activos)} activos, {len(excl)} excluidos")
    for r in activos[:10]: print(r["posicion"], r["id_paciente"], r["categoria"], r["estado_clinico"], r["dias_espera"])
