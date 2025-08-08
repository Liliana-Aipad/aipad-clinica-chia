APP_VERSION = "2025-08-08 18:05"
import streamlit as st
import pandas as pd
import os
import plotly.express as px
from datetime import datetime

# === Archivos esperados (en la raíz del repo) ===
INVENTARIO_FILE = "inventario_cuentas.xlsx"
USUARIOS_FILE   = "usuarios.xlsx"

# Colores por estado
ESTADO_COLORES = {
    "Radicada": "green",
    "Pendiente": "red",
    "Auditada":  "orange",
    "Subsanada": "blue",
}

# ====== DATA ======
@st.cache_data
def load_data():
    if not os.path.exists(INVENTARIO_FILE):
        return pd.DataFrame()
    df = pd.read_excel(INVENTARIO_FILE)
    # Normalizar fechas si existen
    for col in ["FechaRadicacion", "FechaMovimiento"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    # Asegurar columnas mínimas para gráficos
    for col in ["NumeroFactura","Valor","EPS","Vigencia","Estado","Mes"]:
        if col not in df.columns:
            df[col] = pd.NA
    return df

def login():
    st.sidebar.title("🔐 Ingreso")
    cedula = st.sidebar.text_input("Cédula")
    contrasena = st.sidebar.text_input("Contraseña", type="password")
    if st.sidebar.button("Ingresar"):
        try:
            users = pd.read_excel(USUARIOS_FILE, dtype=str)
            ok = users[(users["Cedula"] == cedula) & (users["Contrasena"] == contrasena)]
            if not ok.empty:
                st.session_state["autenticado"] = True
                st.session_state["usuario"] = ok.iloc[0]["Cedula"]
                st.session_state["rol"] = ok.iloc[0]["Rol"]
            else:
                st.sidebar.warning("Datos incorrectos")
        except Exception as e:
            st.sidebar.error(f"Error cargando usuarios: {e}")

# ====== APP ======
def main_app():
    st.set_page_config(layout="wide")
    st.caption(f"🆔 Versión: {APP_VERSION}")
    st.title("📊 AIPAD • Control de Radicación")
    st.markdown(f"👤 Usuario: `{st.session_state['usuario']}`  |  🔐 Rol: `{st.session_state['rol']}`")

    df = load_data()

    tab1, tab2, tab3 = st.tabs(["📋 Dashboard", "📌 Kanban", "📝 Inventario"])

    # ---- DASHBOARD ----
    with tab1:
        st.subheader("📈 Avance general del proyecto")
        if df.empty:
            st.info("No hay datos en el inventario.")
        else:
            total = len(df)
            radicadas = int((df["Estado"] == "Radicada").sum())
            total_valor = float(df["Valor"].fillna(0).sum())
            avance = round((radicadas / total) * 100, 2) if total else 0.0

            c1, c2, c3 = st.columns(3)
            c1.metric("📦 Total facturas", total)
            c2.metric("💰 Valor total", f"${total_valor:,.0f}")
            c3.metric("📊 Avance (radicadas)", f"{avance}%")

            # Distribución por Estado (donut)
            if "Estado" in df.columns:
                fig_estado = px.pie(
                    df, names="Estado", hole=0.4, title="Distribución por Estado",
                    color="Estado", color_discrete_map=ESTADO_COLORES
                )
                st.plotly_chart(fig_estado, use_container_width=True)

            st.markdown("## 🏥 Por EPS")
            if {"EPS","NumeroFactura"}.issubset(df.columns):
                g = df.groupby("EPS", dropna=False).agg(
                    N_Facturas=("NumeroFactura","count"),
                    Valor_Total=("Valor", "sum"),
                    Radicadas=("Estado", lambda x: (x=="Radicada").sum())
                ).fillna(0)
                g["% Avance"] = (g["Radicadas"]/g["N_Facturas"]).replace([pd.NA, pd.NaT, 0], 0).astype(float)*100
                g = g.sort_values("N_Facturas", ascending=False)

                c1, c2 = st.columns(2)
                with c1:
                    fig_eps_val = px.bar(
                        df, x="EPS", y="Valor", color="Estado", barmode="group",
                        title="Valor total por EPS", color_discrete_map=ESTADO_COLORES, text_auto=".2s"
                    )
                    fig_eps_val.update_layout(xaxis={'categoryorder':'total descending'})
                    st.plotly_chart(fig_eps_val, use_container_width=True)
                with c2:
                    fig_eps_cnt = px.bar(
                        g, x=g.index, y="N_Facturas", title="Número de facturas por EPS",
                        text="% Avance"
                    )
                    st.plotly_chart(fig_eps_cnt, use_container_width=True)

            st.markdown("## 📅 Por Mes")
            if {"Mes","NumeroFactura"}.issubset(df.columns):
                g = df.groupby("Mes", dropna=False).agg(
                    N_Facturas=("NumeroFactura","count"),
                    Valor_Total=("Valor","sum"),
                    Radicadas=("Estado", lambda x: (x=="Radicada").sum())
                ).fillna(0)
                g["% Avance"] = (g["Radicadas"]/g["N_Facturas"]).replace(0,0)*100

                c1, c2 = st.columns(2)
                with c1:
                    fig_mes_val = px.area(
                        df, x="Mes", y="Valor", color="Estado",
                        title="Valor total por Mes", line_group="Estado",
                        color_discrete_map=ESTADO_COLORES
                    )
                    st.plotly_chart(fig_mes_val, use_container_width=True)
                with c2:
                    fig_mes_cnt = px.bar(
                        g, x=g.index, y="N_Facturas", title="Facturas por Mes",
                        text=g["% Avance"].round(2).astype(str)+"%"
                    )
                    st.plotly_chart(fig_mes_cnt, use_container_width=True)

            st.markdown("## 📆 Por Vigencia")
            if {"Vigencia","NumeroFactura"}.issubset(df.columns):
                g = df.groupby("Vigencia", dropna=False).agg(
                    N_Facturas=("NumeroFactura","count"),
                    Valor_Total=("Valor","sum"),
                    Radicadas=("Estado", lambda x: (x=="Radicada").sum())
                ).fillna(0)
                g["% Avance"] = (g["Radicadas"]/g["N_Facturas"]).replace(0,0)*100

                c1, c2 = st.columns(2)
                with c1:
                    fig_vig_val = px.bar(
                        df, x="Vigencia", y="Valor", color="Estado", barmode="group",
                        title="Valor por Vigencia", color_discrete_map=ESTADO_COLORES, text_auto=".2s"
                    )
                    st.plotly_chart(fig_vig_val, use_container_width=True)
                with c2:
                    fig_vig_pie = px.pie(
                        df, names="Vigencia", hole=0.5, title="Distribución de Facturas por Vigencia"
                    )
                    st.plotly_chart(fig_vig_pie, use_container_width=True)

    # ---- KANBAN ----
    with tab2:
        st.subheader("📌 Kanban")
        st.info("Módulo en construcción.")

    # ---- INVENTARIO ----
    with tab3:
        st.subheader("📝 Inventario (solo lectura)")
        st.dataframe(load_data(), use_container_width=True)

# ====== BOOT ======
if "autenticado" not in st.session_state:
    login()
elif st.session_state.get("autenticado"):
    main_app()

