
# app_streamlit.py
# -*- coding: utf-8 -*-
import os
from datetime import datetime
import io
import pandas as pd
import numpy as np
import streamlit as st
import plotly.express as px

st.set_page_config(page_title="Gestión Radicación - Clínica Chía", layout="wide")

SAMPLE_PATH = "inventario.xlsx"  # Cambia a tu ruta real si lo necesitas

ESTADOS = ["Pendiente", "Auditada", "Radicada"]
ESTADO_COLORS = {
    "Radicada": "#2ecc71",  # verde
    "Pendiente": "#e74c3c", # rojo
    "Auditada": "#e67e22",  # naranja
}

# -------------------- Utilidades de datos --------------------
def _ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    needed = ["ID","EPS","Vigencia","Estado","Valor","FechaRadicacion","FechaMovimiento","Mes"]
    for col in needed:
        if col not in df.columns:
            if col in ["Valor"]:
                df[col] = 0.0
            elif col in ["FechaRadicacion","FechaMovimiento"]:
                df[col] = pd.NaT
            elif col == "Mes":
                df[col] = ""
            elif col == "Estado":
                df[col] = "Pendiente"
            else:
                df[col] = ""
    # Tipos
    df["Valor"] = pd.to_numeric(df["Valor"], errors="coerce").fillna(0.0)
    df["FechaRadicacion"] = pd.to_datetime(df["FechaRadicacion"], errors="coerce")
    df["FechaMovimiento"] = pd.to_datetime(df["FechaMovimiento"], errors="coerce")
    # Mes derivado
    df["Mes"] = df["FechaRadicacion"].dt.to_period("M").astype(str).where(df["FechaRadicacion"].notna(), "")
    # Orden de columnas
    return df[["ID","EPS","Vigencia","Estado","Valor","FechaRadicacion","FechaMovimiento","Mes"]]

def load_data() -> pd.DataFrame:
    if os.path.exists(SAMPLE_PATH):
        try:
            df = pd.read_excel(SAMPLE_PATH)
        except Exception:
            df = pd.DataFrame()
    else:
        # Datos de ejemplo
        df = pd.DataFrame({
            "ID": [f"FAC-{i:04d}" for i in range(1, 51)],
            "EPS": np.random.choice(["EPS A","EPS B","EPS C","EPS D","EPS E"], 50),
            "Vigencia": np.random.choice([2023, 2024, 2025], 50),
            "Estado": np.random.choice(ESTADOS, 50, p=[0.5, 0.3, 0.2]),
            "Valor": np.random.randint(100_000, 5_000_000, 50).astype(float),
            "FechaRadicacion": pd.NaT,
            "FechaMovimiento": pd.to_datetime(datetime.now()),
            "Mes": ""
        })
    return _ensure_columns(df)

def save_data(df: pd.DataFrame):
    df = _ensure_columns(df.copy())
    with pd.ExcelWriter(SAMPLE_PATH, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False)

def _kpis(df: pd.DataFrame):
    n_fact = len(df)
    valor_total = float(df["Valor"].sum())
    radicadas = (df["Estado"] == "Radicada").sum()
    pct_avance = (radicadas / n_fact * 100) if n_fact else 0.0
    return n_fact, valor_total, pct_avance

def _format_money(x: float) -> str:
    try:
        return f"${x:,.0f}"
    except Exception:
        return str(x)

# -------------------- Componentes: Dashboard --------------------
def render_tab_dashboard(df: pd.DataFrame):
    st.header("Dashboard")

    n_fact, valor_total, pct_avance = _kpis(df)
    c1, c2, c3 = st.columns(3)
    c1.metric("Número de facturas", f"{n_fact:,}")
    c2.metric("Valor total", _format_money(valor_total))
    c3.metric("% avance general", f"{pct_avance:.1f}%")

    # Gráfico 1: Barras por EPS (Top 25)
    eps_count = df.groupby("EPS")["ID"].count().reset_index(name="Facturas")
    fig_eps = px.bar(
        eps_count.sort_values("Facturas", ascending=False).head(25),
        x="EPS", y="Facturas", title="Facturas por EPS (Top 25)",
        text="Facturas"
    )
    fig_eps.update_traces(texttemplate="%{text}", textposition="outside")
    fig_eps.update_layout(xaxis_tickangle=-45, margin=dict(l=10,r=10,t=40,b=10))
    st.plotly_chart(fig_eps, use_container_width=True)

    # Gráfico 2: Barras apiladas por Vigencia y Estado
    vig_estado = df.groupby(["Vigencia", "Estado"]).size().reset_index(name="Facturas")
    fig_vig = px.bar(
        vig_estado, x="Vigencia", y="Facturas", color="Estado",
        title="Distribución por Vigencia y Estado",
        color_discrete_map=ESTADO_COLORS
    )
    st.plotly_chart(fig_vig, use_container_width=True)

    # Gráfico 3: Área apilada por Mes y Estado
    df_mes = df.copy()
    df_mes["Mes"] = df_mes["FechaRadicacion"].dt.to_period("M").astype(str).where(df_mes["FechaRadicacion"].notna(), "Sin Mes")
    mes_estado = df_mes.groupby(["Mes", "Estado"]).size().reset_index(name="Facturas")
    mes_estado = mes_estado.sort_values("Mes")
    fig_mes = px.area(
        mes_estado, x="Mes", y="Facturas", color="Estado",
        title="Evolución mensual por Estado",
        color_discrete_map=ESTADO_COLORS
    )
    st.plotly_chart(fig_mes, use_container_width=True)

    st.info("Descarga del Dashboard a Excel/PDF deshabilitada por solicitud. Usa la pestaña Reportes para exportar.")

# -------------------- Componentes: Gestión --------------------
def _row_selector(df: pd.DataFrame):
    st.subheader("Gestión (formulario de captura y edición)")
    ids = df["ID"].tolist()
    col1, col2 = st.columns([2,1])
    with col1:
        sel = st.selectbox("Selecciona una factura por ID", ids, index=0 if ids else None)
    with col2:
        st.write("")
        st.write("")
        nuevo = st.button("➕ Nueva factura")
    return sel, nuevo

def _form_factura(df: pd.DataFrame, sel_id: str):
    st.divider()
    st.subheader("Formulario")
    if sel_id and sel_id in df["ID"].values:
        row = df[df["ID"] == sel_id].iloc[0].copy()
    else:
        # Nueva
        row = pd.Series({
            "ID": f"FAC-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "EPS": "",
            "Vigencia": datetime.now().year,
            "Estado": "Pendiente",
            "Valor": 0.0,
            "FechaRadicacion": pd.NaT,
            "FechaMovimiento": pd.to_datetime(datetime.now()),
            "Mes": ""
        })

    with st.form("form_factura", clear_on_submit=False):
        c1, c2, c3 = st.columns(3)
        with c1:
            id_val = st.text_input("ID (no editable)", value=row["ID"], disabled=True)
            eps = st.text_input("EPS", value=str(row.get("EPS","")))
            vig = st.number_input("Vigencia", value=int(row.get("Vigencia", datetime.now().year)), step=1)
        with c2:
            estado = st.selectbox("Estado", ESTADOS, index=ESTADOS.index(row.get("Estado","Pendiente")) if row.get("Estado","Pendiente") in ESTADOS else 0)
            valor = st.number_input("Valor", value=float(row.get("Valor",0.0)), step=1000.0, min_value=0.0)
            # FechaRadicacion editable solo si estado == Radicada
            fecha_rad = st.date_input("Fecha de radicación", value=row["FechaRadicacion"].date() if pd.notna(row["FechaRadicacion"]) else datetime.now().date(),
                                      disabled=(estado != "Radicada"))
        with c3:
            # FechaMovimiento: no editable, auto cuando cambie estado
            st.text_input("Fecha de movimiento (auto)", value=str(row["FechaMovimiento"]) if pd.notna(row["FechaMovimiento"]) else "", disabled=True)
            st.text_input("Mes (auto)", value=str(row["Mes"]), disabled=True)
            st.write("")
        submitted = st.form_submit_button("💾 Guardar cambios")

    if submitted:
        # Detectar cambio de estado
        old_estado = str(row.get("Estado",""))
        new_estado = estado
        fecha_mov = row["FechaMovimiento"]
        if new_estado != old_estado:
            fecha_mov = pd.to_datetime(datetime.now())  # actualizar automáticamente

        # FechaRadicacion solo si estado == Radicada; si no, limpiar
        if new_estado == "Radicada":
            fecha_rad_dt = pd.to_datetime(fecha_rad)
        else:
            fecha_rad_dt = pd.NaT

        # Mes derivado
        mes = fecha_rad_dt.to_period("M").astype(str) if pd.notna(fecha_rad_dt) else ""

        # Guardar / actualizar en df
        if id_val in df["ID"].values:
            df.loc[df["ID"] == id_val, ["EPS","Vigencia","Estado","Valor","FechaRadicacion","FechaMovimiento","Mes"]] = [
                eps, int(vig), new_estado, float(valor), fecha_rad_dt, fecha_mov, mes
            ]
        else:
            df.loc[len(df)] = [id_val, eps, int(vig), new_estado, float(valor), fecha_rad_dt, fecha_mov, mes]

        save_data(df)
        st.success("✅ Cambios guardados. Permaneces en la pestaña Gestión.")
    return df

def render_tab_gestion(df: pd.DataFrame):
    st.header("Gestión")
    if df.empty:
        st.warning("No hay datos en el inventario aún.")
    sel, nuevo = _row_selector(df)
    if nuevo:
        sel = None
    df = _form_factura(df, sel)

    # Vista tabla compacta (sin listar facturas por bandeja)
    st.subheader("Inventario (vista rápida)")
    st.dataframe(df.style.format({"Valor": lambda x: f"${x:,.0f}"}), use_container_width=True, height=400)

# -------------------- Componentes: Reportes --------------------
def _tabla_resumen(df, by, nombre):
    g = df.groupby(by, dropna=False).agg(
        Facturas=("Estado", "count"),
        Valor=("Valor", "sum"),
        Radicadas=("Estado", lambda s: (s == "Radicada").sum()),
        Pendientes=("Estado", lambda s: (s == "Pendiente").sum()),
        Auditadas=("Estado", lambda s: (s == "Auditada").sum()),
    ).reset_index()
    g["% Avance"] = (g["Radicadas"] / g["Facturas"]).fillna(0) * 100
    st.subheader(f"Resumen por {nombre}")
    st.dataframe(g, use_container_width=True)
    return g

def _exportar_excel(kpis, t_eps, t_vig, t_mes):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        pd.DataFrame(
            {
                "Métrica": ["# Facturas", "Valor total", "% Avance general"],
                "Valor": [kpis[0], kpis[1], round(kpis[2], 2)],
            }
        ).to_excel(writer, index=False, sheet_name="Resumen")
        t_eps.to_excel(writer, index=False, sheet_name="Por_EPS")
        t_vig.to_excel(writer, index=False, sheet_name="Por_Vigencia")
        t_mes.to_excel(writer, index=False, sheet_name="Por_Mes")
    return output.getvalue()

def render_tab_reportes(df: pd.DataFrame):
    st.header("Reportes")
    df = df.copy()
    # Asegurar columnas mínimas
    for col in ["Estado", "Valor", "EPS", "Vigencia"]:
        if col not in df.columns:
            st.warning(f"⚠ Falta la columna requerida: {col}")
            return
    # Mes: si no existe, derivarlo de FechaRadicacion
    if "Mes" not in df.columns:
        if "FechaRadicacion" in df.columns:
            df["Mes"] = pd.to_datetime(df["FechaRadicacion"], errors="coerce").dt.to_period("M").astype(str)
        else:
            df["Mes"] = "Sin Mes"

    # KPIs
    n_fact, valor_total, pct_avance = _kpis(df)
    c1, c2, c3 = st.columns(3)
    c1.metric("Número de facturas", f"{n_fact:,}")
    c2.metric("Valor total", f"${valor_total:,.0f}")
    c3.metric("% avance general", f"{pct_avance:.1f}%")

    st.subheader("Gráficos")
    # 1) Por EPS (barras) - etiquetas
    eps_count = df.groupby("EPS")["Estado"].count().reset_index(name="Facturas")
    fig_eps = px.bar(
        eps_count.sort_values("Facturas", ascending=False).head(25),
        x="EPS", y="Facturas", title="Facturas por EPS (Top 25)",
        text="Facturas"
    )
    fig_eps.update_traces(texttemplate="%{text}", textposition="outside")
    fig_eps.update_layout(xaxis_tickangle=-45, uniformtext_minsize=10, uniformtext_mode="hide")
    st.plotly_chart(fig_eps, use_container_width=True)

    # 2) Por Vigencia (barras apiladas por Estado)
    vig_estado = df.groupby(["Vigencia", "Estado"]).size().reset_index(name="Facturas")
    fig_vig = px.bar(vig_estado, x="Vigencia", y="Facturas", color="Estado",
                     title="Distribución por Vigencia y Estado",
                     color_discrete_map=ESTADO_COLORS)
    st.plotly_chart(fig_vig, use_container_width=True)

    # 3) Por Mes (área apilada por Estado)
    mes_estado = df.groupby(["Mes", "Estado"]).size().reset_index(name="Facturas")
    mes_estado = mes_estado.sort_values("Mes")
    fig_mes = px.area(mes_estado, x="Mes", y="Facturas", color="Estado",
                      groupnorm=None, title="Evolución mensual por Estado",
                      color_discrete_map=ESTADO_COLORS)
    st.plotly_chart(fig_mes, use_container_width=True)

    # Tablas de resumen
    t_eps = _tabla_resumen(df, by="EPS", nombre="EPS")
    t_vig = _tabla_resumen(df, by="Vigencia", nombre="Vigencia")
    t_mes = _tabla_resumen(df, by="Mes", nombre="Mes")

    # Exportar a Excel (sin PDF)
    st.subheader("Descarga")
    xls_bytes = _exportar_excel((n_fact, valor_total, pct_avance), t_eps, t_vig, t_mes)
    st.download_button(
        "⬇️ Descargar reportes a Excel",
        data=xls_bytes,
        file_name="reportes_radicacion.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )

# -------------------- App --------------------
def main_app():
    st.title("Gestión de Radicación e Inventario - Clínica Chía")

    # Cargar datos
    df = load_data()

    # Tabs
    tab_dashboard, tab_gestion, tab_reportes = st.tabs(["Dashboard", "Gestión", "Reportes"])

    with tab_dashboard:
        render_tab_dashboard(df)

    with tab_gestion:
        render_tab_gestion(df)
        # recargar después de posibles cambios
        df = load_data()

    with tab_reportes:
        df = load_data()
        render_tab_reportes(df)

if __name__ == "__main__":
    main_app()
