
import streamlit as st
import pandas as pd
import os
import plotly.express as px
from datetime import datetime

# Ruta del archivo principal
INVENTARIO_FILE = "inventario_cuentas.xlsx"
USUARIOS_FILE = "usuarios.xlsx"
BACKUP_DIR = "backups"

# Crear carpeta de backups si no existe
os.makedirs(BACKUP_DIR, exist_ok=True)

# Cargar datos
@st.cache_data
def load_data():
    if os.path.exists(INVENTARIO_FILE):
        df = pd.read_excel(INVENTARIO_FILE)
        return df
    else:
        return pd.DataFrame()

# Guardar backup
def backup_data(df):
    now = datetime.now().strftime("%Y-%m-%d_%H-%M")
    filename = f"{BACKUP_DIR}/inventario_backup_{now}.xlsx"
    df.to_excel(filename, index=False)

# Login
def login():
    st.sidebar.title("🔐 Ingreso")
    cedula = st.sidebar.text_input("Cédula", key="cedula")
    contrasena = st.sidebar.text_input("Contraseña", type="password", key="contrasena")
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

# App principal
def main_app():
    st.title("📊 AIPAD Control de Radicación")
    st.markdown(f"👤 Usuario: `{st.session_state['usuario']}`")
    st.markdown(f"🔐 Rol: `{st.session_state['rol']}`")

    df = load_data()

    # Realizar backup automáticamente
    if not df.empty:
        backup_data(df)

    tab1, tab2, tab3, tab4 = st.tabs(["📋 Dashboard", "📌 Kanban", "📁 Entregas", "📄 Reportes"])

    with tab1:
        st.subheader("📈 Avance general del proyecto")
        if not df.empty:
            total = len(df)
            estados = df["Estado"].value_counts().to_dict()
            procesadas = estados.get("Radicada", 0)
            avance = round((procesadas / total) * 100, 2) if total else 0

            col1, col2, col3 = st.columns(3)
            col1.metric("📦 Total cuentas", total)
            col2.metric("✅ Radicadas", procesadas)
            col3.metric("📊 Avance (%)", f"{avance}%")

            fig1 = px.pie(df, names="Estado", title="Distribución por Estado", hole=0.4)
            st.plotly_chart(fig1, use_container_width=True)

            if "Mes" in df.columns:
                fig2 = px.bar(df, x="Mes", color="Estado", title="Cuentas procesadas por mes", barmode="group")
                st.plotly_chart(fig2, use_container_width=True)
            else:
                st.info("Agrega una columna 'Mes' al inventario para ver evolución mensual.")
        else:
            st.info("No se encontró el archivo de inventario.")

    with tab2:
        st.subheader("Kanban (en desarrollo)")

    with tab3:
        st.subheader("Control de entregas (en desarrollo)")

    with tab4:
        st.subheader("Generar reportes (en desarrollo)")

if "autenticado" not in st.session_state:
    login()
if st.session_state.get("autenticado", False):
    main_app()
