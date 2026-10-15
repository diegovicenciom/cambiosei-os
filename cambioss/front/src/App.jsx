import React, { useMemo } from "react";

const pacientesDemo = [
  { id: "P-101", nombre: "María López", especialidad: "Cardiología", diagnostico: "IC con hipertensión", categoria: "alta", dias_espera: 210, estado_clinico: "descompensado" },
  { id: "P-102", nombre: "Juan Pérez", especialidad: "Cardiología", diagnostico: "Insuficiencia cardiaca", categoria: "alta", dias_espera: 195, estado_clinico: "estabilizado" },
  { id: "P-103", nombre: "Ana García", especialidad: "Traumatología", diagnostico: "Fractura de cadera", categoria: "media", dias_espera: 180, estado_clinico: "estable" },
  { id: "P-104", nombre: "Luis Rojas", especialidad: "Neurología", diagnostico: "Migraña crónica", categoria: "media", dias_espera: 170, estado_clinico: "estable" },
  { id: "P-105", nombre: "Carmen Torres", especialidad: "Broncopulmonar", diagnostico: "EPOC descompensado", categoria: "alta", dias_espera: 240, estado_clinico: "descompensado" },
  { id: "P-106", nombre: "Pedro Díaz", especialidad: "Endocrinología", diagnostico: "Diabetes no controlada", categoria: "media", dias_espera: 155, estado_clinico: "estable" },
  { id: "P-107", nombre: "Sofía Navarro", especialidad: "Salud Mental", diagnostico: "Depresión grave", categoria: "baja", dias_espera: 140, estado_clinico: "estable" },
  { id: "P-108", nombre: "Martín Silva", especialidad: "Gastroenterología", diagnostico: "Cirrosis descompensada", categoria: "alta", dias_espera: 260, estado_clinico: "descompensado" },
  { id: "P-109", nombre: "Elena Castro", especialidad: "Cardiología", diagnostico: "Arritmia", categoria: "alta", dias_espera: 175, estado_clinico: "estabilizado" },
  { id: "P-110", nombre: "José Romero", especialidad: "Traumatología", diagnostico: "Dolor lumbar crónico", categoria: "baja", dias_espera: 130, estado_clinico: "estable" },
  { id: "P-111", nombre: "Patricia Vega", especialidad: "Broncopulmonar", diagnostico: "Asma severa", categoria: "media", dias_espera: 200, estado_clinico: "estable" },
  { id: "P-112", nombre: "Rodrigo Fuentes", especialidad: "Cardiología", diagnostico: "Insuficiencia cardiaca", categoria: "alta", dias_espera: 220, estado_clinico: "descompensado" },
];

function percentil(arr, p) {
  if (!arr || !arr.length) return 0;
  const ordenado = [...arr].sort((a, b) => a - b);
  const idx = (ordenado.length - 1) * p;
  const bajo = Math.floor(idx);
  const alto = Math.ceil(idx);
  if (bajo === alto) return ordenado[bajo];
  return ordenado[bajo] + (ordenado[alto] - ordenado[bajo]) * (idx - bajo);
}

const prioridadColor = {
  alta: "#d32f2f",
  media: "#f9a825",
  baja: "#2e7d32",
};

export default function App() {
  const pacientes = pacientesDemo;

  const umbral90 = useMemo(() => Math.round(percentil(pacientes.map((p) => p.dias_espera), 0.9)), [pacientes]);
  const percentil90 = useMemo(
    () => pacientes.filter((p) => (p.dias_espera || 0) >= umbral90).sort((a, b) => b.dias_espera - a.dias_espera),
    [pacientes, umbral90]
  );

  const exportarCsv = () => {
    const header = ["Paciente", "ID", "Especialidad", "Diagnóstico", "Días de espera", "Prioridad", "Estado clínico"];
    const rows = percentil90.map((p) => [p.nombre, p.id, p.especialidad, p.diagnostico, p.dias_espera, p.categoria, p.estado_clinico]);
    const csv = [header, ...rows].map((row) => row.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `percentil_90_${umbral90}_dias.csv`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div style={{ fontFamily: "system-ui, sans-serif", background: "#f4f7fb", minHeight: "100vh", padding: 24, color: "#17212b" }}>
      <div style={{ maxWidth: 1200, margin: "0 auto" }}>
        <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 16, marginBottom: 24, flexWrap: "wrap" }}>
          <div>
            <div style={{ fontSize: 12, letterSpacing: 1, textTransform: "uppercase", color: "#5b6b7a", fontWeight: 700 }}>
              Indicadores de espera
            </div>
            <h1 style={{ margin: "8px 0 0", fontSize: 34 }}>Pacientes en percentil 90</h1>
          </div>
          <button
            onClick={exportarCsv}
            style={{
              border: "none",
              background: "#1976d2",
              color: "#fff",
              borderRadius: 10,
              padding: "12px 18px",
              fontWeight: 700,
              cursor: "pointer",
            }}
          >
            Exportar CSV
          </button>
        </header>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
            gap: 16,
            marginBottom: 24,
          }}
        >
          <div style={{ background: "#fff", borderRadius: 14, padding: 18, boxShadow: "0 1px 3px rgba(0,0,0,0.06)" }}>
            <div style={{ fontSize: 12, color: "#617183" }}>Umbral 90</div>
            <div style={{ fontSize: 30, fontWeight: 800, marginTop: 8 }}>{umbral90} días</div>
          </div>
          <div style={{ background: "#fff", borderRadius: 14, padding: 18, boxShadow: "0 1px 3px rgba(0,0,0,0.06)" }}>
            <div style={{ fontSize: 12, color: "#617183" }}>Pacientes en top 10%</div>
            <div style={{ fontSize: 30, fontWeight: 800, marginTop: 8 }}>{percentil90.length}</div>
          </div>
          <div style={{ background: "#fff", borderRadius: 14, padding: 18, boxShadow: "0 1px 3px rgba(0,0,0,0.06)" }}>
            <div style={{ fontSize: 12, color: "#617183" }}>Con descompensación</div>
            <div style={{ fontSize: 30, fontWeight: 800, marginTop: 8 }}>
              {percentil90.filter((p) => p.estado_clinico === "descompensado").length}
            </div>
          </div>
        </div>

        <section style={{ background: "#fff", borderRadius: 14, boxShadow: "0 1px 3px rgba(0,0,0,0.06)", overflow: "hidden" }}>
          <div style={{ padding: 18, borderBottom: "1px solid #e7edf3" }}>
            <h2 style={{ margin: 0, fontSize: 22 }}>Lista del percentil 90</h2>
            <p style={{ margin: "6px 0 0", color: "#617183", fontSize: 14 }}>
              Pacientes que llevan más tiempo esperando y que pueden requerir revisión clínica rápida.
            </p>
          </div>

          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 840 }}>
              <thead>
                <tr style={{ background: "#f5f8fc" }}>
                  <th style={thStyle}>#</th>
                  <th style={thStyle}>Paciente</th>
                  <th style={thStyle}>Especialidad</th>
                  <th style={thStyle}>Diagnóstico</th>
                  <th style={thStyle}>Días</th>
                  <th style={thStyle}>Prioridad</th>
                  <th style={thStyle}>Estado</th>
                </tr>
              </thead>
              <tbody>
                {percentil90.map((p, index) => (
                  <tr key={p.id} style={{ borderBottom: "1px solid #edf2f7" }}>
                    <td style={tdStyle}>{index + 1}</td>
                    <td style={tdStyle}>
                      <div style={{ fontWeight: 700 }}>{p.nombre}</div>
                      <div style={{ fontSize: 12, color: "#617183" }}>{p.id}</div>
                    </td>
                    <td style={tdStyle}>{p.especialidad}</td>
                    <td style={tdStyle}>{p.diagnostico}</td>
                    <td style={{ ...tdStyle, fontWeight: 800, textAlign: "right" }}>{p.dias_espera}</td>
                    <td style={tdStyle}>
                      <span
                        style={{
                          display: "inline-block",
                          padding: "6px 10px",
                          borderRadius: 999,
                          color: "#fff",
                          background: prioridadColor[p.categoria] || "#607d8b",
                          fontWeight: 700,
                          fontSize: 12,
                        }}
                      >
                        {p.categoria.toUpperCase()}
                      </span>
                    </td>
                    <td style={tdStyle}>
                      <span
                        style={{
                          color: p.estado_clinico === "descompensado" ? "#d32f2f" : "#2d3c4d",
                          fontWeight: p.estado_clinico === "descompensado" ? 700 : 600,
                        }}
                      >
                        {p.estado_clinico}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </div>
  );
}

const thStyle = {
  textAlign: "left",
  padding: "14px 16px",
  fontSize: 12,
  letterSpacing: 0.4,
  color: "#5c6d7d",
  textTransform: "uppercase",
};

const tdStyle = {
  padding: "14px 16px",
  fontSize: 14,
  verticalAlign: "top",
};
