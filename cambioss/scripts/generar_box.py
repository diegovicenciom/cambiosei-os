"""Genera data/box.json desde data/agenda_box.csv y data/citaciones.csv (sin dependencias).
Uso: python scripts/generar_box.py data"""
import csv, json, sys, os
from collections import defaultdict
D = sys.argv[1] if len(sys.argv) > 1 else "data"
agenda = list(csv.DictReader(open(os.path.join(D, "agenda_box.csv"), encoding="utf-8")))
citas = list(csv.DictReader(open(os.path.join(D, "citaciones.csv"), encoding="utf-8")))
esp = defaultdict(lambda: {"bloques": 0, "cupos": 0, "usados": 0, "sobretiempo": 0, "dias": set()})
for a in agenda:
    e = esp[a["especialidad"]]
    e["bloques"] += 1; e["cupos"] += int(a["capacidad_cupos"]); e["usados"] += int(a["cupos_usados"])
    e["sobretiempo"] += int(a["minutos_sobretiempo"]); e["dias"].add(a["fecha"])
ns = defaultdict(lambda: [0, 0])
for c in citas:
    ns[c["especialidad"]][1] += 1
    if c["estado_cita"] == "no_asistio": ns[c["especialidad"]][0] += 1
out = {}
for k, e in esp.items():
    libres = e["cupos"] - e["usados"]
    out[k] = {"cupos_totales": e["cupos"], "cupos_usados": e["usados"], "cupos_libres": libres,
              "ocupacion_pct": round(e["usados"] / e["cupos"] * 100, 1),
              "cupos_libres_promedio_dia": round(libres / len(e["dias"]), 1),
              "sobretiempo_promedio_min": round(e["sobretiempo"] / e["bloques"], 1),
              "inasistencia_pct": round(ns[k][0] / ns[k][1] * 100, 1) if ns[k][1] else None}
tc = sum(v["cupos_totales"] for v in out.values()); tu = sum(v["cupos_usados"] for v in out.values())
res = {"periodo": f'{min(a["fecha"] for a in agenda)} a {max(a["fecha"] for a in agenda)}',
       "cupos_totales": tc, "cupos_usados": tu, "cupos_libres": tc - tu, "ocupacion_pct": round(tu / tc * 100, 1),
       "citas": len(citas), "inasistencias": sum(1 for c in citas if c["estado_cita"] == "no_asistio")}
# agenda diaria por box (para asignar los cupos libres de un día a pacientes de la lista)
agenda_dia = defaultdict(list)
for a in agenda:
    agenda_dia[a["fecha"]].append({"id_box": a["id_box"], "especialidad": a["especialidad"],
                                   "bloque": f'{a["bloque_inicio"]}-{a["bloque_fin"]}',
                                   "capacidad": int(a["capacidad_cupos"]), "usados": int(a["cupos_usados"]),
                                   "sobretiempo_min": int(a["minutos_sobretiempo"])})
json.dump({"resumen": res, "especialidades": out, "agenda": agenda_dia}, open(os.path.join(D, "box.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps(res, ensure_ascii=False))
