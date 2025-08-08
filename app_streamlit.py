
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
