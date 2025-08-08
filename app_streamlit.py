
import streamlit as st
import pandas as pd
import os
import plotly.express as px
import plotly.graph_objects as go

INVENTARIO_FILE = "inventario_cuentas.xlsx"
USUARIOS_FILE = "usuarios.xlsx"
BACKUP_DIR = "backups"

os.makedirs(BACKUP_DIR, exist_ok=True)

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

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📋 Dashboard", "📌 Kanban", "📁 Entregas", "📄 Reportes", "📝 Inventario"
    ])

    with tab1:
        st.subheader("📈 Avance general del proyecto")
        if not df.empty:
            total = len(df)
            radicadas = df[df["Estado"] == "Radicada"]
            total_valor = df["Valor"].sum() if "Valor" in df.columns else 0
            avance = round(len(radicadas) / total * 100, 2) if total else 0

            col1, col2, col3 = st.columns(3)
            col1.metric("📦 Total facturas", total)
            col2.metric("💰 Valor total", f"${total_valor:,.0f}")
            col3.metric("📊 Avance (radicadas)", f"{avance}%")

            st.markdown("---")

            # Distribución por Estado (Pastel)
            fig_estado = px.pie(df, names="Estado", hole=0.4, title="Distribución por Estado")
            st.plotly_chart(fig_estado, use_container_width=True)

            st.markdown("## 🏥 Por EPS")
            col1, col2 = st.columns(2)
            with col1:
                fig_valor_eps = px.treemap(df, path=["EPS"], values="Valor", title="Valor por EPS (Treemap)")
                st.plotly_chart(fig_valor_eps, use_container_width=True)
            with col2:
                fig_count_eps = px.bar(df, x="EPS", title="Número de facturas por EPS", color="Estado", barmode="group")
                st.plotly_chart(fig_count_eps, use_container_width=True)

            st.markdown("## 📅 Por Mes")
            if "Mes" in df.columns:
                col1, col2 = st.columns(2)
                with col1:
                    fig_valor_mes = px.area(df, x="Mes", y="Valor", title="Valor total por Mes", color="Estado", line_group="Estado")
                    st.plotly_chart(fig_valor_mes, use_container_width=True)
                with col2:
                    fig_count_mes = px.bar(df, x="Mes", title="Facturas por Mes", color="Estado", barmode="stack")
                    st.plotly_chart(fig_count_mes, use_container_width=True)

            st.markdown("## 📆 Por Vigencia")
            if "Vigencia" in df.columns:
                col1, col2 = st.columns(2)
                with col1:
                    fig_valor_vig = px.bar(df, x="Vigencia", y="Valor", color="Estado", barmode="group", title="Valor por Vigencia")
                    st.plotly_chart(fig_valor_vig, use_container_width=True)
                with col2:
                    fig_count_vig = px.pie(df, names="Vigencia", title="Distribución de Facturas por Vigencia")
                    st.plotly_chart(fig_count_vig, use_container_width=True)

        else:
            st.warning("No hay datos para mostrar en el dashboard.")

    with tab2:
        st.subheader("Kanban (en desarrollo)")
    with tab3:
        st.subheader("Control de entregas (en desarrollo)")
    with tab4:
        st.subheader("Generar reportes (en desarrollo)")
    with tab5:
        st.subheader("Edición de inventario (módulo independiente)")

if "autenticado" not in st.session_state:
    login()
if st.session_state.get("autenticado", False):
    main_app()
