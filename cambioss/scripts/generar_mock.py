"""Genera front/src/mock.json (modo demo sin API) con el MISMO motor de reglas de la API.
Uso (desde la raíz):  python scripts/generar_mock.py data
"""
import json, os, sys
from datetime import date, timedelta

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["LOCAL"] = "1"
os.environ["DATA_DIR"] = sys.argv[1] if len(sys.argv) > 1 else os.path.join(RAIZ, "data")
sys.path.insert(0, os.path.join(RAIZ, "lambda"))
import app  # noqa: E402

# mismas fechas que el slider del front (api.js)
fechas, f = [], date(2026, 4, 1)
while f < date(2026, 10, 13):
    fechas.append(f.isoformat()); f += timedelta(days=14)
fechas.append("2026-10-13")

ESTATICOS = ("nombre_fantasia", "edad", "sexo", "comuna", "especialidad", "diagnostico_cie10", "diagnostico_texto",
             "prioridad_inicial", "fecha_ingreso_lista")
QUITAR = set(ESTATICOS) | {"posicion_anterior", "explicacion_ia", "estado_revision"}

perfs, revs = app.perfiles_combinados()
out = {"fechas": fechas, "cortes": {}, "pacientes": {}, "timeline": {}}
for fc in fechas:
    data = app.lista(date.fromisoformat(fc), None, perfs, revs)
    for p in data["pacientes"]:
        out["pacientes"].setdefault(p["id_paciente"], {k: p[k] for k in ("id_paciente",) + ESTATICOS})
    out["cortes"][fc] = {"pacientes": [{k: v for k, v in p.items() if k not in QUITAR} for p in data["pacientes"]],
                         "excluidos": data["excluidos"]}
for pid in out["pacientes"]:
    p = perfs[pid]
    out["timeline"][pid] = {"eventos": p.get("eventos_clinicos", []), "mediciones": p.get("mediciones", []),
                            "citaciones": p.get("citaciones", [])}

ruta = os.path.join(RAIZ, "front", "src", "mock.json")
with open(ruta, "w", encoding="utf-8") as fh:
    json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
print(f"{ruta}: {len(fechas)} cortes, {len(out['pacientes'])} pacientes, {os.path.getsize(ruta) // 1024} KB")
