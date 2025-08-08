
import streamlit as st
import pandas as pd
import os
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

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

def avanzar_por_estado(df, agrupador):
    conteo = df.groupby([agrupador, "Estado"]).size().unstack(fill_value=0)
    conteo["Total"] = conteo.sum(axis=1)
    for estado in ["Pendiente", "Auditada", "Subsanada", "Radicada"]:
        if estado not in conteo.columns:
            conteo[estado] = 0
    for estado in ["Pendiente", "Auditada", "Subsanada", "Radicada"]:
        conteo[f"% {estado}"] = (conteo[estado] / conteo["Total"]) * 100
    return conteo.reset_index()

def plot_estado_avance(df, agrupador):
    data = avanzar_por_estado(df, agrupador)
    fig = go.Figure()
    for estado in ["Pendiente", "Auditada", "Subsanada", "Radicada"]:
        fig.add_trace(go.Bar(
            x=data[agrupador],
            y=data[f"% {estado}"],
            name=estado
        ))
    fig.update_layout(
        barmode='stack',
        title=f"📊 Avance porcentual por estado ({agrupador})",
        yaxis_title="% avance",
        xaxis_title=agrupador,
        height=400
    )
    return fig

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
            total_valor = df["Valor"].sum() if "Valor" in df.columns else 0
            estados = df["Estado"].value_counts().to_dict()

            col1, col2, col3 = st.columns(3)
            col1.metric("📦 Total facturas", total)
            col2.metric("💰 Valor total", f"${total_valor:,.0f}")
            col3.metric("📊 Estados registrados", len(estados))

            # Gráfico general por Estado
            fig_estado = px.bar(df, x="Estado", title="Distribución general por Estado",
                                color="Estado", color_discrete_sequence=px.colors.qualitative.Set2)
            st.plotly_chart(fig_estado, use_container_width=True)

            # Gráficos por EPS
            st.subheader("🏥 Avance por EPS")
            col1, col2 = st.columns(2)
            with col1:
                fig_eps_valor = px.bar(df, x="EPS", y="Valor", title="Valor total por EPS", color="EPS")
                st.plotly_chart(fig_eps_valor, use_container_width=True)
            with col2:
                fig_eps_count = px.histogram(df, x="EPS", title="Número de facturas por EPS", color="EPS")
                st.plotly_chart(fig_eps_count, use_container_width=True)
            st.plotly_chart(plot_estado_avance(df, "EPS"), use_container_width=True)

            # Gráficos por Mes
            if "Mes" in df.columns:
                st.subheader("📅 Avance por Mes")
                col1, col2 = st.columns(2)
                with col1:
                    fig_mes_valor = px.bar(df, x="Mes", y="Valor", title="Valor total por Mes", color="Mes")
                    st.plotly_chart(fig_mes_valor, use_container_width=True)
                with col2:
                    fig_mes_count = px.histogram(df, x="Mes", title="Número de facturas por Mes", color="Mes")
                    st.plotly_chart(fig_mes_count, use_container_width=True)
                st.plotly_chart(plot_estado_avance(df, "Mes"), use_container_width=True)

            # Gráficos por Vigencia
            if "Vigencia" in df.columns:
                st.subheader("📆 Avance por Vigencia")
                col1, col2 = st.columns(2)
                with col1:
                    fig_vig_valor = px.bar(df, x="Vigencia", y="Valor", title="Valor total por Vigencia", color="Vigencia")
                    st.plotly_chart(fig_vig_valor, use_container_width=True)
                with col2:
                    fig_vig_count = px.histogram(df, x="Vigencia", title="Número de facturas por Vigencia", color="Vigencia")
                    st.plotly_chart(fig_vig_count, use_container_width=True)
                st.plotly_chart(plot_estado_avance(df, "Vigencia"), use_container_width=True)

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
