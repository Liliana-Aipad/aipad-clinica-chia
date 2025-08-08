
import streamlit as st
import pandas as pd
import os
import plotly.express as px
from datetime import datetime

INVENTARIO_FILE = "inventario_cuentas.xlsx"
USUARIOS_FILE = "usuarios.xlsx"

# Colores por estado
estado_colores = {
    "Radicada": "green",
    "Pendiente": "red",
    "Auditada": "orange",
    "Subsanada": "blue"
}

@st.cache_data
def load_data():
    if os.path.exists(INVENTARIO_FILE):
        df = pd.read_excel(INVENTARIO_FILE)
        for col in ["FechaRadicacion", "FechaMovimiento"]:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce")
        return df
    else:
        return pd.DataFrame()

def login():
    st.sidebar.title("🔐 Ingreso")
    cedula = st.sidebar.text_input("Cédula")
    contrasena = st.sidebar.text_input("Contraseña", type="password")
    if st.sidebar.button("Ingresar"):
        try:
            usuarios_df = pd.read_excel(USUARIOS_FILE, dtype=str)
            usuario = usuarios_df[
                (usuarios_df["Cedula"] == cedula) &
                (usuarios_df["Contrasena"] == contrasena)
            ]
            if not usuario.empty:
                st.session_state["autenticado"] = True
                st.session_state["usuario"] = usuario.iloc[0]["Cedula"]
                st.session_state["rol"] = usuario.iloc[0]["Rol"]
            else:
                st.sidebar.warning("Datos incorrectos")
        except Exception as e:
            st.sidebar.error(f"Error cargando usuarios: {e}")

def main_app():
    st.set_page_config(layout="wide")
    st.title("📊 AIPAD Control de Radicación")
    st.markdown(f"👤 Usuario: `{st.session_state['usuario']}`")
    st.markdown(f"🔐 Rol: `{st.session_state['rol']}`")

    df = load_data()

    tab1, tab2, tab3 = st.tabs(["📋 Dashboard", "📌 Kanban", "📝 Inventario"])

    with tab1:
        st.subheader("📈 Avance general del proyecto")
        total = len(df)
        radicadas = len(df[df["Estado"] == "Radicada"])
        total_valor = df["Valor"].sum() if "Valor" in df.columns else 0
        avance = round((radicadas / total) * 100, 2) if total else 0

        col1, col2, col3 = st.columns(3)
        col1.metric("📦 Total facturas", total)
        col2.metric("💰 Valor total", f"${total_valor:,.0f}")
        col3.metric("📊 Avance (radicadas)", f"{avance}%")

        fig_estado = px.pie(df, names="Estado", hole=0.4, title="Distribución por Estado",
                            color="Estado", color_discrete_map=estado_colores)
        st.plotly_chart(fig_estado, use_container_width=True)

# Gráfico por EPS
if "EPS" in df.columns:
    st.subheader("📊 Facturación por EPS")
    resumen_eps = df.groupby("EPS").agg({
        "Factura": "count",
        "Valor": "sum",
        "Estado": lambda x: (x == "Radicada").sum()
    }).rename(columns={"Factura": "N° Facturas", "Valor": "Valor Total", "Estado": "Radicadas"})
    resumen_eps["% Avance"] = round((resumen_eps["Radicadas"] / resumen_eps["N° Facturas"]) * 100, 2)
    resumen_eps = resumen_eps.sort_values("N° Facturas", ascending=False)
    fig_eps = px.bar(resumen_eps, x=resumen_eps.index, y="N° Facturas", color_discrete_sequence=["blue"],
                     text="% Avance", title="Facturas por EPS")
    st.plotly_chart(fig_eps, use_container_width=True)

# Gráfico por Mes
if "Mes" in df.columns:
    st.subheader("📅 Facturación por Mes")
    resumen_mes = df.groupby("Mes").agg({
        "Factura": "count",
        "Valor": "sum",
        "Estado": lambda x: (x == "Radicada").sum()
    }).rename(columns={"Factura": "N° Facturas", "Valor": "Valor Total", "Estado": "Radicadas"})
    resumen_mes["% Avance"] = round((resumen_mes["Radicadas"] / resumen_mes["N° Facturas"]) * 100, 2)
    fig_mes = px.area(resumen_mes, x=resumen_mes.index, y="N° Facturas", text="% Avance",
                      title="Facturas por Mes")
    st.plotly_chart(fig_mes, use_container_width=True)

# Gráfico por Vigencia
if "Vigencia" in df.columns:
    st.subheader("📅 Facturación por Vigencia")
    resumen_vigencia = df.groupby("Vigencia").agg({
        "Factura": "count",
        "Valor": "sum",
        "Estado": lambda x: (x == "Radicada").sum()
    }).rename(columns={"Factura": "N° Facturas", "Valor": "Valor Total", "Estado": "Radicadas"})
    resumen_vigencia["% Avance"] = round((resumen_vigencia["Radicadas"] / resumen_vigencia["N° Facturas"]) * 100, 2)
    fig_vigencia = px.bar(resumen_vigencia, x=resumen_vigencia.index, y="N° Facturas",
                          text="% Avance", title="Facturas por Vigencia")
    st.plotly_chart(fig_vigencia, use_container_width=True)


    with tab2:
        st.subheader("📌 Kanban")
        st.warning("Módulo en desarrollo.")

    with tab3:
        st.subheader("📝 Inventario")
        st.dataframe(df, use_container_width=True)

if "autenticado" not in st.session_state:
    login()
elif st.session_state.get("autenticado"):
    main_app()
