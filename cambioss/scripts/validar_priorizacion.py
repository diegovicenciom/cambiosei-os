"""(Tomado del PR #1 de agusnoopy3000.) Valida la priorización con el registro del HLF (solo lectura, solo datos con fecha ≤ cada corte).
Uso (desde la raíz):  python scripts/validar_priorizacion.py data

1. Fallecidos: ¿en qué parte de la lista estaban 7 días antes de morir? (reglas vs lista estática = prioridad inicial + llegada)
2. Eventos graves (urgencia / hospitalización grave) en los 60 días siguientes a cortes mensuales.
3. Qué regla usa cada fuente de datos.
"""
import json, os, statistics as st, sys
from datetime import date, timedelta

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = sys.argv[1] if len(sys.argv) > 1 else os.path.join(RAIZ, "data")
sys.path.insert(0, os.path.join(RAIZ, "lambda"))
import puntaje  # noqa: E402

perfiles = json.load(open(os.path.join(D, "perfiles.json"), encoding="utf-8"))
perfiles = perfiles if isinstance(perfiles, list) else list(perfiles.values())
por_id = {p["id_paciente"]: p for p in perfiles}
REF = date(2026, 10, 13)
ORD = {"alta": 0, "media": 1, "baja": 2}


def percentil(lista, pid):
    ids = [r["id_paciente"] for r in lista]
    return ids.index(pid) / len(ids) if pid in ids else None


def estatica(activos):
    le = lambda r: por_id[r["id_paciente"]]["lista_espera"]
    return sorted(activos, key=lambda r: (ORD[le(r)["prioridad_inicial"]], le(r)["fecha_ingreso_lista"]))


grave = lambda e: e["severidad"] == "grave" and e["tipo_evento"] in ("visita_urgencia", "hospitalizacion")

print("1. Fallecidos: posición 7 días antes del fallecimiento (percentil; 0 = primero de la lista)")
reglas, est = [], []
for p in perfiles:
    if not p["paciente"].get("fecha_defuncion"):
        continue
    corte = date.fromisoformat(p["paciente"]["fecha_defuncion"]) - timedelta(days=7)
    activos, _ = puntaje.priorizar(perfiles, corte)
    if percentil(activos, p["id_paciente"]) is None:
        continue
    reglas.append(percentil(activos, p["id_paciente"]))
    est.append(percentil(estatica(activos), p["id_paciente"]))
print(f"   n={len(reglas)} · mediana reglas {st.median(reglas):.0%} vs estática {st.median(est):.0%} · "
      f"en el 10% superior: {sum(x <= .1 for x in reglas)} vs {sum(x <= .1 for x in est)}")

print("2. Eventos graves en los 60 días siguientes (5 cortes mensuales)")
r_p, e_p = [], []
for k in range(1, 6):
    corte = REF - timedelta(days=30 * k + 60)
    activos, _ = puntaje.priorizar(perfiles, corte)
    e_lista = estatica(activos)
    for r in activos:
        evs = [e for e in por_id[r["id_paciente"]].get("eventos_clinicos", [])
               if grave(e) and corte < date.fromisoformat(e["fecha_evento"]) <= corte + timedelta(days=60)]
        if evs:
            r_p.append(percentil(activos, r["id_paciente"])); e_p.append(percentil(e_lista, r["id_paciente"]))
print(f"   n={len(r_p)} · mediana reglas {st.median(r_p):.0%} vs estática {st.median(e_p):.0%} · "
      f"en el 20% superior: {sum(x <= .2 for x in r_p) / len(r_p):.0%} vs {sum(x <= .2 for x in e_p) / len(e_p):.0%}")
print("   (los eventos agudos llegan sin aviso: la lista los recoge en cuanto se registran)")

print("3. Fuentes → reglas")
for f, uso in [("pacientes.csv", "edad (GES), fallecimiento → egreso causal 9"),
               ("lista_espera.csv", "prioridad inicial (categoría base), CIE-10 (tabla HLF, GES, Charlson), fecha de ingreso (antigüedad > 1 año, llegada), estado"),
               ("eventos_clinicos.csv", "descompensación → fila 'descompensada' tabla HLF, descompensación grave (evaluar en 72 h), LACE (A, E), revisión sugerida"),
               ("mediciones.csv", "última medición fuera de rango"),
               ("citaciones.csv", "2 inasistencias consecutivas (causal 8), primera atención → sale de la lista"),
               ("agenda_box.csv", "horas libres por box y día (agenda de referencia)")]:
    print(f"   {f:22s} {uso}")
