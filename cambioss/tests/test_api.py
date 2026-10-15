import json, os, sys
from datetime import date
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["LOCAL"] = "1"; os.environ.setdefault("DATA_DIR", os.path.join(RAIZ, "data")); os.environ.pop("MODEL_ID", None)
sys.path.insert(0, os.path.join(RAIZ, "lambda"))
import app

def call(method, path, qs=None, body=None):
    r = app.handler({"requestContext": {"http": {"method": method}}, "rawPath": path,
                     "queryStringParameters": qs, "body": json.dumps(body) if body else None})
    return r["statusCode"], json.loads(r["body"])

def fila(d, pid):
    return next(p for p in d["pacientes"] if p["id_paciente"] == pid)

def test_lista_y_exclusion():
    s, d = call("GET", "/pacientes", {"fecha_corte": "2026-10-13"})
    assert s == 200 and sum(p["id_paciente"].startswith("PAC-HLF") for p in d["pacientes"]) == 409
    assert "PAC-HLF-00009" in [e["id_paciente"] for e in d["excluidos"]]
    assert all(k in d["pacientes"][0] for k in ("categoria", "estado_clinico", "posicion", "razones", "estado_revision"))
    assert {p["categoria"] for p in d["pacientes"]} <= {"alta", "media", "baja"}

def test_orden_minsal():
    """Categoría → descompensación grave → grupo de protección → > 1 año → LACE (solo desempate) → llegada."""
    _, d = call("GET", "/pacientes", {"fecha_corte": "2026-10-13"})
    orden = {"alta": 3, "media": 2, "baja": 1}
    claves = [(-orden[p["categoria"]], not p["riesgo_vital"], not p["grupo_proteccion"],
               not p["antiguedad_mayor_1_anio"], -p["lace"]["total"], -p["dias_espera"]) for p in d["pacientes"]]
    assert claves == sorted(claves)
    assert all(p["lace"]["experimental"] and p["lace"]["datos_faltantes"] for p in d["pacientes"])

def test_lace_00002():
    """Angina sin Charlson; hospitalización (A=3) y 1 urgencia (E=1) en los 6 meses previos al 10-08."""
    _, d = call("GET", "/pacientes", {"fecha_corte": "2026-08-10"})
    l = fila(d, "PAC-HLF-00002")["lace"]
    assert {x["letra"]: x["puntos"] for x in l["partes"]} == {"L": 0, "A": 3, "C": 0, "E": 1} and l["total"] == 4

def test_riesgo_vital_00002():
    _, d = call("GET", "/pacientes", {"fecha_corte": "2026-08-10"})
    p = fila(d, "PAC-HLF-00002")
    assert p["riesgo_vital"] and p["razones"][0]["factor"] == "riesgo_vital"
    assert all(q["riesgo_vital"] for q in d["pacientes"][:p["posicion"]] if q["categoria"] == "alta")

def test_box_asigna_con_motivo_y_alternativa():
    _, d = call("GET", "/boxes", {"fecha_corte": "2026-10-13", "especialidad": "Cardiología"})
    e = d["especialidades"][0]
    asignados = [p for a in e["asignaciones"] for p in a["pacientes"]]
    assert asignados and all(p["motivo"] for p in asignados)
    assert e["alternativa"]["por_que_despues"]

def test_deterioro_agudo_sube_por_tabla_oficial():
    _, antes = call("GET", "/pacientes", {"fecha_corte": "2026-07-01"})
    _, despues = call("GET", "/pacientes", {"fecha_corte": "2026-08-10"})
    a, b = fila(antes, "PAC-HLF-00002"), fila(despues, "PAC-HLF-00002")
    assert a["categoria"] == "baja" and b["categoria"] == "alta" and b["posicion"] < a["posicion"]
    assert any(r["factor"] == "tabla_oficial" and "Angina inestable" in r["valor"] and "pág. 85" in r["fuente"] for r in b["razones"])

def test_no_baja_solo():
    """00028 se estabiliza: el sistema no le baja la categoría por su cuenta."""
    _, d = call("GET", "/pacientes", {"fecha_corte": "2026-10-13"})
    p = fila(d, "PAC-HLF-00028")
    assert p["estado_clinico"] == "estabilizado" and p["categoria"] == p["prioridad_inicial"]
    assert p["posicion"] > 350

def test_inasistencia_causal_8():
    _, d = call("GET", "/pacientes", {"fecha_corte": "2026-10-13"})
    p = fila(d, "PAC-HLF-00020")
    orden = {"alta": 3, "media": 2, "baja": 1}
    assert p["riesgo_inasistencia"] and orden[p["categoria"]] >= orden[p["prioridad_inicial"]]  # nunca la baja

def test_filtro_especialidad():
    _, d = call("GET", "/pacientes", {"especialidad": "Cardiología"})
    assert d["total"] > 0 and all(p["especialidad"] == "Cardiología" for p in d["pacientes"])

def test_evento_sube_paciente():
    s, d = call("POST", "/eventos", body={"id_paciente": "PAC-HLF-00020", "tipo_evento": "hospitalizacion",
                                          "subtipo": "ingreso UCI", "severidad": "grave"})
    assert s == 200 and d["posicion_despues"] < d["posicion_antes"] and d["paciente"]["categoria"] == "alta"
    assert d["reevaluado_en_ms"] < 72 * 3600 * 1000

def test_informe_texto_propone_sin_guardar():
    pid = "PAC-HLF-00003"
    _, antes = call("GET", f"/pacientes/{pid}")
    s, d = call("POST", f"/pacientes/{pid}/informe",
                body={"texto": "Paciente consulta en urgencia y se hospitaliza por descompensación de su cuadro."})
    assert s == 200 and d["evento"]["tipo_evento"] == "hospitalizacion" and d["fuente"] == "reglas"
    assert "hospitaliza" in d["evento"]["evidencia"]
    _, despues = call("GET", f"/pacientes/{pid}")
    assert len(despues["eventos_clinicos"]) == len(antes["eventos_clinicos"])  # solo propone

def test_informe_sin_evento():
    s, d = call("POST", "/pacientes/PAC-HLF-00003/informe", body={"texto": "Paciente refiere cefalea leve."})
    assert s == 200 and d["evento"] is None and d["mensaje"]

LEER_FOTO_REAL = app.informe.leer_foto

def test_foto_sin_aws_avisa():
    app.informe.leer_foto = LEER_FOTO_REAL   # Textract real: sin credenciales AWS en las pruebas debe avisar, no caerse
    s, d = call("POST", "/pacientes/PAC-HLF-00003/informe", body={"imagen_base64": "aGVsbG8=", "media_type": "image/png"})
    assert s == 200 and d["evento"] is None and "Textract" in d["mensaje"]

def _foto_simulada(texto, confianza=99.0):
    """Reemplaza Textract por un OCR simulado (las pruebas no usan AWS)."""
    from modelos import Lectura, LineaLeida
    lineas = [LineaLeida(texto=l, confianza=confianza) for l in texto.splitlines() if l.strip()]
    app.informe.leer_foto = lambda b64: Lectura(origen="foto", motor="textract", texto=texto, lineas=lineas)

def test_foto_varios_eventos_y_fecha_correcta():
    _foto_simulada("DAU Urgencia - Paciente PAC-HLF-00003\nFecha de nacimiento: 01/02/1960\nFecha: 11/10/2026\n"
                   "Categorizacion: ESI 2.\nSe descarta sindrome coronario.\nSe hospitaliza en medicina por disnea.")
    s, d = call("POST", "/pacientes/PAC-HLF-00003/informe", body={"imagen_base64": "x", "fecha_corte": "2026-10-13"})
    subt = [e["subtipo"] for e in d["eventos"]]
    assert subt[0] == "ingreso hospitalario" and "triage ESI 2" in subt          # muestra todos, el más grave primero
    assert all(e["fecha_evento"] == "2026-10-11" for e in d["eventos"])           # no toma la fecha de nacimiento
    assert d["identidad_en_documento"] and not d["otro_paciente"] and d["lectura"]["motor"] == "textract"

def test_foto_de_otro_paciente_alerta():
    _foto_simulada("Paciente PAC-HLF-00444\nSe hospitaliza por neumonia.")
    s, d = call("POST", "/pacientes/PAC-HLF-00003/informe", body={"imagen_base64": "x"})
    assert d["otro_paciente"] and "otro paciente" in d["advertencias"][0]

def test_foto_poco_legible_pide_repetir():
    _foto_simulada("Se hospitaliza en medicina.", confianza=55.0)
    s, d = call("POST", "/pacientes/PAC-HLF-00003/informe", body={"imagen_base64": "x"})
    assert not d["lectura"]["legible"] and any("repita la foto" in a for a in d["advertencias"])

def test_pydantic_rechaza_evento_invalido():
    from datetime import date as _d
    from pydantic import ValidationError
    from modelos import EventoPropuesto
    base = {"tipo_evento": "hospitalizacion", "subtipo": "ingreso hospitalario", "severidad": "grave",
            "evidencia": "Se hospitaliza en medicina", "detectado_por": "reglas"}
    EventoPropuesto.model_validate(base, context={"texto": "Hoy. Se hospitaliza en medicina.", "corte": _d(2026, 10, 13)})
    for malo, ctx in [({**base, "subtipo": "cirugía"}, {}),                                   # subtipo fuera del registro
                      ({**base, "severidad": "leve"}, {}),                                    # severidad incoherente
                      (base, {"texto": "Paciente estable, control en APS."}),                 # evidencia no está en el documento
                      ({**base, "fecha_evento": "2026-12-01"}, {"corte": _d(2026, 10, 13)})]:  # fecha futura
        try:
            EventoPropuesto.model_validate(malo, context=ctx)
            assert False, f"debió rechazar {malo}"
        except ValidationError:
            pass

def test_revision():
    s, _ = call("POST", "/pacientes/PAC-HLF-00001/revision", body={"accion": "confirmar"})
    assert s == 200
    _, d = call("GET", "/pacientes")
    assert fila(d, "PAC-HLF-00001")["estado_revision"] == "confirmado"
    s, _ = call("POST", "/pacientes/PAC-HLF-00001/revision", body={"accion": "ajustar"})
    assert s == 400

def test_ajuste_clinico_reordena():
    _, d = call("GET", "/pacientes")
    p = next(p for p in reversed(d["pacientes"]) if p["categoria"] == "baja" and p["id_paciente"] not in
             ("PAC-HLF-00028", "PAC-HLF-00002", "PAC-HLF-00020"))
    s, _ = call("POST", f"/pacientes/{p['id_paciente']}/revision",
                body={"accion": "ajustar", "categoria_ajustada": "alta", "motivo": "criterio clínico"})
    assert s == 200
    _, d2 = call("GET", "/pacientes")
    q = fila(d2, p["id_paciente"])
    assert q["categoria"] == "alta" and q["categoria_sistema"] == "baja" and q["posicion"] < p["posicion"]

def test_ges():
    _, d = call("GET", "/pacientes")
    p = next(p for p in d["pacientes"] if p["diagnostico_cie10"] == "F32" and p["edad"] >= 15)
    assert p["ges"]["problema"] == 34 and p["ges"]["plazo_dias"] == 30
    assert any(r["factor"] == "ges" and "auge.minsal.cl" in r["fuente"] for r in p["razones"])

def test_explicar_plantilla():
    s, d = call("POST", "/pacientes/PAC-HLF-00002/explicar", body={"fecha_corte": "2026-08-10"})
    assert s == 200 and "validación clínica" in d["explicacion_ia"] and "Angina inestable" in d["explicacion_ia"]

def test_detalle_y_boxes():
    s, d = call("GET", "/pacientes/PAC-HLF-00001")
    assert s == 200 and d["mediciones"]
    s, d = call("GET", "/boxes")
    assert s == 200 and d["especialidades"] and d["especialidades"][0]["sugeridos"]

def test_ingresar_paciente_nuevo():
    s, cat = call("GET", "/catalogo")
    assert s == 200 and any(d["diagnostico_cie10"] == "I50" for d in cat["diagnosticos"])
    s, d = call("POST", "/pacientes", body={"nombre": "Juan Pérez", "edad": 70, "sexo": "M", "diagnostico_cie10": "I50",
                                             "prioridad_inicial": "media", "fecha_corte": "2026-10-13"})
    assert s == 200 and d["paciente"]["categoria"] == "media" and d["paciente"]["especialidad"] == "Cardiología"
    pid = d["id_paciente"]
    s, r = call("POST", "/eventos", body={"id_paciente": pid, "tipo_evento": "hospitalizacion", "subtipo": "ingreso hospitalario",
                                          "severidad": "grave", "fecha_corte": "2026-10-13"})
    assert s == 200 and r["paciente"]["categoria"] == "alta" and r["paciente"]["riesgo_vital"]
    assert call("POST", "/pacientes", body={"nombre": "", "edad": 70})[0] == 400

def _xlsx(hojas):
    """Excel mínimo (cadenas en línea) para probar la lectura sin librerías."""
    import base64, io, zipfile
    from xml.sax.saxutils import escape
    b = io.BytesIO()
    z = zipfile.ZipFile(b, "w")
    z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
    z.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
               'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>' +
               "".join(f'<sheet name="{n}" sheetId="{i}" r:id="rId{i}"/>' for i, n in enumerate(hojas, 1)) + "</sheets></workbook>")
    z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
               "".join(f'<Relationship Id="rId{i}" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(hojas) + 1)) + "</Relationships>")
    for i, filas in enumerate(hojas.values(), 1):
        xml = "".join("<row>" + "".join(
            (f'<c r="{chr(65 + j)}{k + 1}"><v>{v}</v></c>' if isinstance(v, (int, float)) else
             f'<c r="{chr(65 + j)}{k + 1}" t="inlineStr"><is><t>{escape(str(v))}</t></is></c>') for j, v in enumerate(f)) + "</row>"
                      for k, f in enumerate(filas))
        z.writestr(f"xl/worksheets/sheet{i}.xml", f'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{xml}</sheetData></worksheet>')
    z.close()
    return base64.b64encode(b.getvalue()).decode()

def test_importar_excel_y_csv():
    import base64
    excel = _xlsx({
        "Pacientes": [["RUT", "Nombre", "Edad", "Género"], ["11.111.111-1", "Ana Soto", 71, "Femenino"]],
        "Lista espera": [["RUT", "CIE10", "Prioridad", "Fecha ingreso"], ["11.111.111-1", "I50.9", "MEDIA", 46000]],
    })
    csv_ev = base64.b64encode("Rut;Fecha;Tipo;Subtipo;Gravedad\n11.111.111-1;01-10-2026;Hospitalización;ingreso hospitalario;Grave\n"
                              "99;xx;urgencia;;leve\n".encode("utf-8")).decode()
    archivos = [{"nombre": "export_hlf.xlsx", "contenido_base64": excel}, {"nombre": "eventos.csv", "contenido_base64": csv_ev}]
    s, rev = call("POST", "/importar", body={"archivos": archivos})
    assert s == 200 and not rev["cargado"]
    tablas = {i["tabla"]: i for i in rev["informe"]}
    assert tablas["pacientes"]["validas"] == 1 and tablas["lista_espera"]["validas"] == 1
    assert tablas["eventos_clinicos"]["validas"] == 1 and tablas["eventos_clinicos"]["errores"][0]["fila"] == 3
    assert rev["resumen"]["pacientes_nuevos"] == 1 and rev["resumen"]["eventos"] == 1
    s, carga = call("POST", "/importar", body={"archivos": archivos, "confirmar": True})
    assert carga["cargado"]
    _, d = call("GET", "/pacientes", {"fecha_corte": "2026-10-13"})
    p = fila(d, "11.111.111-1")
    assert p["especialidad"] == "Cardiología" and p["fecha_ingreso_lista"] == "2025-12-09"   # 46000 = fecha interna de Excel
    assert p["categoria"] == "alta" and p["riesgo_vital"]   # IC descompensada (pág. 85) tras la hospitalización importada

def test_novedades_comorbilidad_diagnostico_fallecimiento():
    _, d = call("GET", "/pacientes", {"fecha_corte": "2026-10-13"})
    p = next(x for x in d["pacientes"] if x["diagnostico_cie10"] == "M75" and x["lace"]["total"] == 0)
    pid = p["id_paciente"]
    s, r = call("POST", f"/pacientes/{pid}/novedad", body={"tipo": "comorbilidad", "cie10": "M54"})   # lumbago: sin peso Charlson
    assert s == 200 and r["paciente"]["lace"]["total"] == 0 and "sin peso Charlson" in r["paciente"]["lace"]["partes"][2]["valor"]
    s, r = call("POST", f"/pacientes/{pid}/novedad", body={"tipo": "comorbilidad", "condicion": "insuficiencia cardíaca congestiva"})
    assert r["paciente"]["lace"]["partes"][2]["puntos"] == 2 and r["paciente"]["lace"]["total"] == 2
    s, r = call("POST", f"/pacientes/{pid}/novedad", body={"tipo": "diagnostico", "cie10": "I20"})
    assert r["paciente"]["especialidad"] == "Cardiología"
    s, r = call("POST", f"/pacientes/{pid}/novedad", body={"tipo": "fallecimiento", "fecha": "2026-10-12"})
    assert s == 200 and not r["en_lista"]
    _, d = call("GET", "/pacientes", {"fecha_corte": "2026-10-13"})
    assert pid in [e["id_paciente"] for e in d["excluidos"]] and pid not in [x["id_paciente"] for x in d["pacientes"]]

def _otro(d, **cond):
    usados = {"PAC-HLF-00001", "PAC-HLF-00002", "PAC-HLF-00020", "PAC-HLF-00028", "PAC-HLF-00003"}
    return next(p for p in d["pacientes"] if p["id_paciente"].startswith("PAC-HLF") and p["id_paciente"] not in usados
                and p["estado_revision"] == "pendiente" and all(p[k] == v for k, v in cond.items()))

def test_bug_ajuste_no_tapa_descompensacion_posterior():
    """Un ajuste a 'baja' no puede ocultar una hospitalización registrada después."""
    _, d = call("GET", "/pacientes", {"fecha_corte": "2026-10-13"})
    p = _otro(d, diagnostico_cie10="I50", categoria="media", estado_clinico="sin_cambios")
    pid = p["id_paciente"]
    call("POST", f"/pacientes/{pid}/revision", body={"accion": "ajustar", "categoria_ajustada": "baja", "motivo": "estable", "fecha_corte": "2026-10-13"})
    _, d = call("GET", "/pacientes", {"fecha_corte": "2026-10-13"})
    assert fila(d, pid)["categoria"] == "baja" and fila(d, pid)["estado_revision"] == "ajustado"
    call("POST", "/eventos", body={"id_paciente": pid, "tipo_evento": "hospitalizacion", "subtipo": "ingreso hospitalario",
                                   "severidad": "grave", "fecha_corte": "2026-10-13"})
    _, d = call("GET", "/pacientes", {"fecha_corte": "2026-10-13"})
    q = fila(d, pid)
    assert q["categoria"] == "alta" and q["estado_revision"] == "requiere_revision" and q["revision_sugerida"]

def test_bug_contacto_apaga_alerta():
    _, d = call("GET", "/pacientes", {"fecha_corte": "2026-10-13"})
    p = next(x for x in d["pacientes"] if x["contactar_hoy"] and x["id_paciente"] != "PAC-HLF-00002")
    s, r = call("POST", f"/pacientes/{p['id_paciente']}/contacto", body={"resultado": "no_contesta", "fecha_corte": "2026-10-13"})
    assert s == 200 and r["paciente"]["contactar_hoy"]          # no contesta: la alerta sigue
    s, r = call("POST", f"/pacientes/{p['id_paciente']}/contacto", body={"resultado": "contactado", "fecha_corte": "2026-10-13"})
    assert s == 200 and r["paciente"]["contactar_hoy"]          # llamar no es decidir: sigue pendiente la evaluación médica
    s, r = call("POST", f"/pacientes/{p['id_paciente']}/contacto", body={"resultado": "citado", "fecha_corte": "2026-10-13"})
    assert r["paciente"]["contactar_hoy"] and r["paciente"]["gestion"]["estado"] == "cita_reservada"   # citar no es revisar la prioridad
    s, r = call("POST", f"/pacientes/{p['id_paciente']}/revision", body={"accion": "confirmar", "fecha_corte": "2026-10-13"})
    _, d = call("GET", "/pacientes", {"fecha_corte": "2026-10-13"})
    assert not fila(d, p["id_paciente"])["contactar_hoy"] and fila(d, p["id_paciente"])["riesgo_vital"]   # revisada, sigue priorizada

def test_plazo_72h_corre_desde_que_el_evento_llega():
    _, d = call("GET", "/pacientes", {"fecha_corte": "2026-10-14"})
    v = [p for p in d["pacientes"] if p["riesgo_vital"] and p["evaluacion"]["estado"] != "evaluada" and p["id_paciente"].startswith("PAC-HLF")
         and not p["evaluacion"]["llego_al_sistema"] > "2026-10-13"]
    assert v and all(p["evaluacion"]["llego_al_sistema"] == "2026-10-13" and p["evaluacion"]["dias_en_revision"] == 1
                     and p["evaluacion"]["estado"] == "pendiente" for p in v)   # el registro se cargó el 13-10: aún en plazo
    _, d = call("GET", "/pacientes", {"fecha_corte": "2026-10-20"})
    assert all(p["evaluacion"]["estado"] == "atrasada" for p in d["pacientes"] if p["id_paciente"] in {x["id_paciente"] for x in v}
               and p["evaluacion"]["estado"] != "evaluada")

def test_gestion_responsable_y_seguimiento():
    _, d = call("GET", "/pacientes", {"fecha_corte": "2026-10-13"})
    pid = next(x["id_paciente"] for x in d["pacientes"] if x["id_paciente"].startswith("PAC-HLF") and not x["gestion"]["responsable"])
    assert fila(d, pid)["gestion"]["estado"] in ("pendiente_revision", "pendiente_cita", "pendiente_contacto", "cita_reservada")
    assert call("POST", f"/pacientes/{pid}/gestion", body={"responsable": "Enf. Rojas", "fecha_corte": "2026-10-13"})[0] == 400   # sin usuario
    assert call("POST", f"/pacientes/{pid}/gestion", body={"usuario": "Enf. Rojas", "motivo_pendiente": "otro", "nota": "corto", "fecha_corte": "2026-10-13"})[0] == 400
    assert call("POST", f"/pacientes/{pid}/gestion", body={"usuario": "Enf. Rojas", "seguimiento": "2026-01-01", "fecha_corte": "2026-10-13"})[0] == 400
    s, r = call("POST", f"/pacientes/{pid}/gestion", body={"usuario": "Enf. Rojas", "responsable": "Enf. Rojas", "proxima_accion": "Pedir ecografía a APS",
                                                          "seguimiento": "2026-10-15", "motivo_pendiente": "antecedentes", "fecha_corte": "2026-10-13"})
    g = r["paciente"]["gestion"]
    assert s == 200 and g["responsable"] == "Enf. Rojas" and g["proxima_accion"] == "Pedir ecografía a APS" and not g["seguimiento_vencido"]
    assert g["motivo_texto"] == "Faltan antecedentes o exámenes"
    _, d = call("GET", "/pacientes", {"fecha_corte": "2026-10-20"})
    assert fila(d, pid)["gestion"]["seguimiento_vencido"]
    _, k = call("GET", "/kpis", {"fecha_corte": "2026-10-20"})
    assert k["trabajo_pendiente"]["seguimiento_vencido"] >= 1 and k["espera"]["mas_de_1_anio"] >= 1

def test_bug_atendido_respeta_fecha_de_corte():
    import json as _j
    perfs = app.perfiles()
    p = next(x for x in perfs.values() if x["lista_espera"]["estado"] == "atendido")
    fa = app.puntaje.fecha_atencion(p)
    antes = (date.fromisoformat(fa) - __import__("datetime").timedelta(days=1)).isoformat()
    _, d1 = call("GET", "/pacientes", {"fecha_corte": antes})
    _, d2 = call("GET", "/pacientes", {"fecha_corte": fa})
    if p["lista_espera"]["fecha_ingreso_lista"] <= antes:
        assert p["id_paciente"] in [x["id_paciente"] for x in d1["pacientes"]]
    assert any(e["id_paciente"] == p["id_paciente"] and e["motivo"] == "atendido" for e in d2["excluidos"])

def test_bug_negacion_en_informe():
    s, d = call("POST", "/pacientes/PAC-HLF-00003/informe", body={"texto": "Evaluado en urgencia, se descarta hospitalización. Alta a domicilio."})
    assert d["evento"] is None or d["evento"]["tipo_evento"] != "hospitalizacion"
    s, d = call("POST", "/pacientes/PAC-HLF-00003/informe", body={"texto": "Paciente sin hospitalizaciones previas. Hoy se hospitaliza por disnea."})
    assert d["evento"]["tipo_evento"] == "hospitalizacion" and "Hoy se hospitaliza" in d["evento"]["evidencia"]

def test_revision_sugerida_deterioro_00001():
    # antes de la confirmación de test_revision (fecha_corte 13-10): las señales piden revisión
    _, d = call("GET", "/pacientes", {"fecha_corte": "2026-10-01"})
    motivos = {s["motivo"] for s in fila(d, "PAC-HLF-00001")["revision_sugerida"]}
    assert {"examen alterado", "aumento de dosis"} <= motivos

def test_kpis_y_kappa():
    s, k = call("GET", "/kpis", {"fecha_corte": "2026-10-13"})
    assert s == 200 and k["cobertura"]["pct"] == 100.0 and k["concordancia"]["revisiones"] >= 1
    assert k["concordancia"]["kappa"] is None or -1 <= k["concordancia"]["kappa"] <= 1
    assert app._kappa([("alta", "alta"), ("baja", "baja"), ("media", "media")]) == 1.0

def test_grupo_proteccion_ordena_despues_de_lace():
    _, d = call("GET", "/pacientes", {"fecha_corte": "2026-10-13"})
    baja = [x for x in d["pacientes"] if x["categoria"] == "baja" and not x["riesgo_vital"] and x["lace"]["total"] == 0
            and x["estado_revision"] == "pendiente" and x["id_paciente"].startswith("PAC-HLF")]
    ultimo = baja[-1]
    call("POST", f"/pacientes/{ultimo['id_paciente']}/novedad", body={"tipo": "riesgo", "grupo_proteccion": "PRAIS", "acg": "G3"})
    _, d = call("GET", "/pacientes", {"fecha_corte": "2026-10-13"})
    q = fila(d, ultimo["id_paciente"])
    assert q["grupo_proteccion"] == "PRAIS" and q["acg"] == "G3" and q["posicion"] < ultimo["posicion"]

def test_box_horas_distintas_por_paciente():
    _, b = call("GET", "/boxes", {"fecha_corte": "2026-10-13"})
    for e in b["especialidades"]:
        for a in e["asignaciones"]:
            horas = [p["hora"] for p in a["pacientes"]]
            assert len(horas) == len(set(horas)), f'{a["id_box"]} repite horas: {horas}'
            ini, fin = a["bloque"].split("-")
            assert all(ini <= h < fin for h in horas)
            assert all(p["hora"] < p["hora_fin"] <= fin for p in a["pacientes"])   # cada hora tiene inicio < término
    assert all(v["hora"] for v in b["cupo_por_paciente"].values())

def test_citar_reserva_la_hora():
    q = {"fecha_corte": "2026-10-13", "especialidad": "Gastroenterología"}
    _, b = call("GET", "/boxes", q)
    a = next(x for e in b["especialidades"] for x in e["asignaciones"] if len(x["pacientes"]) >= 2)
    p1, p2 = a["pacientes"][0], a["pacientes"][1]
    s, r = call("POST", f"/pacientes/{p1['id_paciente']}/contacto", body={"resultado": "citado", "fecha_corte": "2026-10-13",
                "hora": p1["hora"], "hora_fin": p1["hora_fin"], "id_box": a["id_box"]})
    assert s == 200 and r["contacto"]["hora"] == p1["hora"]
    s, r = call("POST", f"/pacientes/{p2['id_paciente']}/contacto", body={"resultado": "citado", "fecha_corte": "2026-10-13",
                "hora": p1["hora"], "id_box": a["id_box"]})
    assert s == 409                                                     # la misma hora no se reserva dos veces
    _, b2 = call("GET", "/boxes", q)
    a2 = next(x for e in b2["especialidades"] for x in e["asignaciones"] if x["id_box"] == a["id_box"])
    fila1 = next(p for p in a2["pacientes"] if p["id_paciente"] == p1["id_paciente"])
    assert fila1["citado"] and fila1["hora"] == p1["hora"] and a2["libres_sin_citar"] == a["libres"] - 1
    assert [p["hora"] for p in a2["pacientes"]].count(p1["hora"]) == 1   # nadie más recibe esa hora
    _, d = call("GET", "/disponible", {**q, "cupos": "40"})
    assert p1["id_paciente"] not in [p["id_paciente"] for p in d["pacientes"]]   # el médico no lo vuelve a proponer

def test_no_contesta_cuenta_intentos():
    _, d = call("GET", "/pacientes", {"fecha_corte": "2026-10-13"})
    p = next(x for x in d["pacientes"] if x["contactar_hoy"] and not x["contacto"])
    for _ in range(2):
        s, r = call("POST", f"/pacientes/{p['id_paciente']}/contacto", body={"resultado": "no_contesta", "fecha_corte": "2026-10-13"})
    assert r["paciente"]["contacto"]["intentos_sin_respuesta"] == 2 and r["paciente"]["contactar_hoy"]

def test_medico_con_horas_libres():
    s, d = call("GET", "/disponible", {"fecha_corte": "2026-10-13", "especialidad": "Cardiología", "desde": "14:00", "hasta": "17:00"})
    assert s == 200 and d["duracion_min"] > 0 and d["cupos"] == 180 // d["duracion_min"]
    assert d["pacientes"][0]["hora"] == "14:00" and len(d["pacientes"]) == d["cupos"]
    _, b = call("GET", "/boxes", {"fecha_corte": "2026-10-13", "especialidad": "Cardiología"})
    citados = {pid for pid, c in b["cupo_por_paciente"].items() if c["citado"]}
    assert not set(p["id_paciente"] for p in d["pacientes"]) & citados       # no repite a quien ya tiene cita reservada
    propuestos = {pid for pid, c in b["cupo_por_paciente"].items() if not c["citado"]}
    assert all(p.get("propuesto_en_box") for p in d["pacientes"] if p["id_paciente"] in propuestos)   # propuesta rotulada
    _, l = call("GET", "/pacientes", {"fecha_corte": "2026-10-13", "especialidad": "Cardiología"})
    orden = [p["id_paciente"] for p in l["pacientes"] if p["id_paciente"] not in citados]
    assert [p["id_paciente"] for p in d["pacientes"]] == orden[:d["cupos"]]                   # respeta el orden de la lista
    s, d = call("GET", "/disponible", {"especialidad": "Cardiología", "cupos": "5"})
    assert len(d["pacientes"]) == 5 and d["reservas"] and d["reservas"][0]["por_que_despues"]
    assert call("GET", "/disponible", {})[0] == 400

def test_validaciones_de_entrada():
    pid = "PAC-HLF-00003"
    s, d = call("POST", "/eventos", body={"id_paciente": pid, "tipo_evento": "hospitalizacion", "subtipo": "ingreso UCI", "severidad": "leve"})
    assert s == 200 and d["evento"]["severidad"] == "grave"          # la severidad la define el vocabulario, no el cliente
    assert call("POST", "/eventos", body={"id_paciente": pid, "tipo_evento": "hospitalizacion", "subtipo": "cirugía"})[0] == 400
    assert call("POST", "/eventos", body={"id_paciente": pid, "tipo_evento": "visita_urgencia", "subtipo": "triage ESI 2",
                                          "fecha_evento": "2030-01-01", "fecha_corte": "2026-10-13"})[0] == 400
    assert call("POST", f"/pacientes/{pid}/novedad", body={"tipo": "fallecimiento", "fecha": "2031-01-01"})[0] == 400
    assert call("POST", f"/pacientes/{pid}/novedad", body={"tipo": "fallecimiento", "fecha": "13/10/2026"})[0] == 400
    assert call("POST", f"/pacientes/{pid}/contacto", body={"resultado": "citado", "hora": "25:99"})[0] == 400
    assert call("GET", "/disponible", {"especialidad": "Cardiología", "desde": "14", "hasta": "x"})[0] == 400
    assert call("GET", "/disponible", {"especialidad": "Cardiología", "cupos": "muchos"})[0] == 400

def test_importar_hospitalizacion_sin_severidad_cuenta():
    import base64
    _, l = call("GET", "/pacientes", {"fecha_corte": "2026-10-13"})
    pid = next(p["id_paciente"] for p in l["pacientes"] if p["id_paciente"].startswith("PAC-HLF") and p["estado_clinico"] == "sin_cambios"
               and p["fecha_ingreso_lista"] < "2026-10-01")
    csv_ev = base64.b64encode(f"rut;fecha;tipo;subtipo\n{pid};2026-10-01;Hospitalización;\n".encode()).decode()
    s, d = call("POST", "/importar", body={"archivos": [{"nombre": "ev.csv", "contenido_base64": csv_ev}], "confirmar": True})
    assert s == 200 and d["resumen"]["eventos"] == 1
    _, l = call("GET", "/pacientes", {"fecha_corte": "2026-10-13"})
    assert fila(l, pid)["estado_clinico"] == "descompensado"

def test_plantilla():
    r = app.handler({"requestContext": {"http": {"method": "GET"}}, "rawPath": "/plantillas/lista_espera"})
    assert r["statusCode"] == 200 and "diagnostico_cie10" in r["body"]

def test_404():
    assert call("GET", "/nada")[0] == 404

def test_decision_clinica_cierra_la_alerta():
    _, d = call("GET", "/pacientes", {"fecha_corte": "2026-10-13"})
    p = next(x for x in d["pacientes"] if x["contactar_hoy"] and not x["contacto"] and not x["decision"])
    assert p["evaluacion"]["estado"] in ("pendiente", "atrasada") and p["evaluacion"]["dias_desde_evento"] >= 0
    pid = p["id_paciente"]
    assert call("POST", f"/pacientes/{pid}/decision", body={"decision": "mantener"})[0] == 400        # falta responsable
    assert call("POST", f"/pacientes/{pid}/decision", body={"decision": "otra", "responsable": "Dra. X"})[0] == 400
    s, r = call("POST", f"/pacientes/{pid}/decision", body={"decision": "adelantar_control", "responsable": "Dra. Soto",
                                                           "seguimiento": "2026-10-20", "fecha_corte": "2026-10-13"})
    assert s == 200 and not r["paciente"]["contactar_hoy"] and r["paciente"]["evaluacion"]["estado"] == "evaluada"
    assert r["paciente"]["evaluacion"]["cierre"]["responsable"] == "Dra. Soto"
    # un evento grave nuevo reabre la evaluación
    call("POST", "/eventos", body={"id_paciente": pid, "tipo_evento": "visita_urgencia", "subtipo": "triage ESI 2", "fecha_corte": "2026-10-13"})
    _, d = call("GET", "/pacientes", {"fecha_corte": "2026-10-13"})
    assert fila(d, pid)["contactar_hoy"] and fila(d, pid)["evaluacion"]["estado"] == "pendiente"

def test_estados_de_cita():
    q = {"fecha_corte": "2026-10-13", "especialidad": "Neurología"}
    _, b = call("GET", "/boxes", q)
    a = next(x for e in b["especialidades"] for x in e["asignaciones"] if len(x["pacientes"]) >= 2)
    p1, p2 = a["pacientes"][0], a["pacientes"][1]
    assert p1["estado_cita"] == "propuesta"
    assert call("POST", f"/pacientes/{p1['id_paciente']}/cita", body={"estado": "confirmada", "fecha_corte": "2026-10-13"})[0] == 404
    call("POST", f"/pacientes/{p1['id_paciente']}/contacto", body={"resultado": "citado", "fecha_corte": "2026-10-13",
         "hora": p1["hora"], "hora_fin": p1["hora_fin"], "id_box": a["id_box"]})
    s, r = call("POST", f"/pacientes/{p1['id_paciente']}/cita", body={"estado": "confirmada", "fecha_corte": "2026-10-13"})
    assert s == 200 and r["cita"]["estado_cita"] == "confirmada"
    _, b = call("GET", "/boxes", q)
    e = b["especialidades"][0]
    assert e["conteo_citas"]["confirmada"] >= 1 and b["cupo_por_paciente"][p1["id_paciente"]]["estado_cita"] == "confirmada"
    # cancelar libera la hora: ahora otro paciente puede reservarla
    call("POST", f"/pacientes/{p1['id_paciente']}/cita", body={"estado": "cancelada", "fecha_corte": "2026-10-13"})
    s, _ = call("POST", f"/pacientes/{p2['id_paciente']}/contacto", body={"resultado": "citado", "fecha_corte": "2026-10-13",
                "hora": p1["hora"], "hora_fin": p1["hora_fin"], "id_box": a["id_box"]})
    assert s == 200

def test_kpis_de_resultado():
    pid = "PAC-HLF-00004"
    call("POST", "/eventos", body={"id_paciente": pid, "tipo_evento": "visita_urgencia", "subtipo": "triage ESI 2", "fecha_corte": "2026-10-13"})
    call("POST", f"/pacientes/{pid}/decision", body={"decision": "mantener", "responsable": "Dr. Rojas", "fecha_corte": "2026-10-13"})
    _, k = call("GET", "/kpis", {"fecha_corte": "2026-10-13"})
    r = k["reevaluacion"]
    assert r["evaluados"] >= 1 and r["mediana_horas"] is not None and r["meta_horas"] == 72
    assert r["descompensados_en_lista"] == r["evaluacion_pendiente"] + r["evaluacion_atrasada"] + r["evaluacion_hecha"]
    assert {"propuestas_sin_reservar", "reservada", "confirmada", "horas_recuperadas"} <= set(k["citas"])
    assert k["contactabilidad"]["intentos"] >= k["contactabilidad"]["efectivos"]
    c = k["concordancia"]
    assert c["n_recomendado"] == 50 and c["suficiente"] == (c["revisiones"] >= 50)

def test_ges_y_equivalencias_se_informan_para_verificar():
    _, d = call("GET", "/pacientes", {"fecha_corte": "2026-10-13"})
    g = next(p for p in d["pacientes"] if p["ges"] and p["ges"]["vencida"])
    assert g["ges"]["verificar"] and any("posible incumplimiento" in r["valor"] for r in g["razones"])
    k = next((p for p in d["pacientes"] if p["diagnostico_cie10"] == "K70" and p["estado_clinico"] == "descompensado"), None)
    assert k is None or any("a validar" in r["valor"] for r in k["razones"] if r["factor"] == "tabla_oficial")

def test_agenda_de_referencia_despues_del_registro():
    _, b = call("GET", "/boxes", {"fecha_corte": "2026-10-16"})
    assert b["dia_agenda"] == "2026-10-13" and b["agenda_referencia"]
    _, b = call("GET", "/boxes", {"fecha_corte": "2026-10-13"})
    assert not b["agenda_referencia"]

def test_usuario_queda_en_el_registro():
    s, r = call("POST", "/pacientes/PAC-HLF-00005/revision", body={"accion": "confirmar", "fecha_corte": "2026-10-13", "usuario": "Dra. Soto, cardiología"})
    assert s == 200 and r["revision"]["usuario"] == "Dra. Soto, cardiología"

def test_ajuste_manual_de_posicion():
    q = {"fecha_corte": "2026-10-13", "especialidad": "Neurología"}
    _, l = call("GET", "/pacientes", q)
    p = next(x for x in reversed(l["pacientes"]) if x["id_paciente"].startswith("PAC-HLF") and x["estado_clinico"] == "sin_cambios")
    pid, base = p["id_paciente"], {"posicion": 2, "motivo": "criterio_clinico", "fecha_corte": "2026-10-13", "usuario": "Dr. Muñoz, neurología"}
    # sin explicación suficiente, sin usuario o con motivo inválido: se rechaza
    assert call("POST", f"/pacientes/{pid}/orden", body={**base, "explicacion": "corto"})[0] == 400
    assert call("POST", f"/pacientes/{pid}/orden", body={**base, "usuario": "", "explicacion": "crisis frecuentes informadas por la familia"})[0] == 400
    assert call("POST", f"/pacientes/{pid}/orden", body={**base, "motivo": "porque si", "explicacion": "crisis frecuentes informadas por la familia"})[0] == 400
    assert call("POST", f"/pacientes/{pid}/orden", body={**base, "posicion": 9999, "explicacion": "crisis frecuentes informadas por la familia"})[0] == 400
    s, r = call("POST", f"/pacientes/{pid}/orden", body={**base, "explicacion": "crisis frecuentes informadas por la familia"})
    assert s == 200 and r["paciente"]["posicion_especialidad"] == 2 and r["paciente"]["ajuste_manual"]["usuario"] == "Dr. Muñoz, neurología"
    assert r["paciente"]["posicion_sistema"] > 2
    # la lista general respeta el mismo orden dentro de la especialidad
    _, todos = call("GET", "/pacientes", {"fecha_corte": "2026-10-13"})
    neuro = [x["id_paciente"] for x in todos["pacientes"] if x["especialidad"] == "Neurología"]
    assert neuro.index(pid) == 1
    # deshacer vuelve al orden del sistema
    s, r = call("POST", f"/pacientes/{pid}/orden", body={"quitar": True, "explicacion": "se revisó en comité y se vuelve al orden",
                                                        "usuario": "Dr. Muñoz", "fecha_corte": "2026-10-13"})
    assert s == 200 and not r["paciente"].get("ajuste_manual") and r["paciente"]["posicion_especialidad"] == p["posicion"]

def test_ajuste_manual_sin_efecto_tras_un_evento():
    q = {"fecha_corte": "2026-10-13", "especialidad": "Cardiología"}
    _, l = call("GET", "/pacientes", q)
    p = next(x for x in l["pacientes"] if x["diagnostico_cie10"] == "I50" and not x["riesgo_vital"] and x["id_paciente"].startswith("PAC-HLF"))
    pid = p["id_paciente"]
    call("POST", f"/pacientes/{pid}/orden", body={"posicion": len(l["pacientes"]), "motivo": "comite", "fecha_corte": "2026-10-13",
                                                  "usuario": "Jefatura", "explicacion": "paciente en control en otro centro"})
    call("POST", "/eventos", body={"id_paciente": pid, "tipo_evento": "hospitalizacion", "subtipo": "ingreso hospitalario", "fecha_corte": "2026-10-13"})
    _, l = call("GET", "/pacientes", q)
    f = fila(l, pid)
    assert not f.get("ajuste_manual") and f["ajuste_manual_vencido"]["vencido_por"]   # el deterioro no queda escondido

def test_rut_valida_digito_verificador():
    assert app.normalizar_rut("12345678-5") == "12.345.678-5" and app.normalizar_rut("11.111.111-1") == "11.111.111-1"
    assert app.normalizar_rut("12345678-4") is None and app.normalizar_rut("abc") is None and app.normalizar_rut("") is None
    assert app.normalizar_rut("10.000.013-k") == "10.000.013-K"
    base = {"nombre": "Prueba RUT", "edad": 50, "sexo": "F", "diagnostico_cie10": "I50", "prioridad_inicial": "media", "fecha_corte": "2026-10-13"}
    assert call("POST", "/pacientes", body={**base, "rut": "12.345.678-4"})[0] == 400          # dígito verificador malo
    s, r = call("POST", "/pacientes", body={**base, "rut": "12345678-5"})
    assert s == 200 and r["paciente"]["rut"] == "12.345.678-5"
    assert call("POST", "/pacientes", body={**base, "rut": "12.345.678-5"})[0] == 409          # misma interconsulta repetida

def test_estadisticas_en_una_llamada():
    s, e = call("GET", "/estadisticas", {"fecha_corte": "2026-10-13"})
    assert s == 200 and e["serie"][0]["fecha"] == "2026-04-01" and e["serie"][-1]["fecha"] == "2026-10-13"
    assert all(x["total"] == x["alta"] + x["media"] + x["baja"] for x in e["serie"])
    _, l = call("GET", "/pacientes", {"fecha_corte": "2026-10-13"})
    assert e["serie"][-1]["total"] == l["total"]                                       # coincide con la lista
    assert all(v["severidad"] == "grave" or "descompensaci" in v["subtipo"] for v in e["evento_causa"].values())
    s, c = call("GET", "/estadisticas", {"fecha_corte": "2026-10-13", "especialidad": "Cardiología"})
    assert c["serie"][-1]["total"] < e["serie"][-1]["total"]

def test_indicadores_por_especialidad_y_tramos():
    _, k = call("GET", "/kpis", {"fecha_corte": "2026-10-13"})
    assert sum(r["en_espera"] for r in k["por_especialidad"]) == k["total_hospital"]["en_espera"] == k["cobertura"]["en_espera"]
    assert sum(t["pacientes"] for t in k["tramos_espera"]) == k["cobertura"]["en_espera"]
    assert k["tramos_espera"][3]["pacientes"] + k["tramos_espera"][4]["pacientes"] == k["total_hospital"]["mas_de_1_anio"]
    _, c = call("GET", "/kpis", {"fecha_corte": "2026-10-13", "especialidad": "Cardiología"})
    card = next(r for r in k["por_especialidad"] if r["especialidad"] == "Cardiología")
    assert c["especialidad"] == "Cardiología" and c["cobertura"]["en_espera"] == card["en_espera"]

def test_health_informa_fecha_y_modo():
    s, h = call("GET", "/health")
    assert s == 200 and h["datos"] == "sinteticos" and h["modo"] in ("simulacion", "tiempo_real") and h["fecha_hoy"]
