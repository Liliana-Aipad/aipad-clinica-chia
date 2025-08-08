
import streamlit as st
import pandas as pd
import os
import plotly.express as px
from datetime import datetime

INVENTARIO_FILE = "inventario_cuentas.xlsx"
USUARIOS_FILE = "usuarios.xlsx"
BACKUP_DIR = "backups"

os.makedirs(BACKUP_DIR, exist_ok=True)

@st.cache_data
def load_data():
    if os.path.exists(INVENTARIO_FILE):
        df = pd.read_excel(INVENTARIO_FILE)
        return df
    else:
        return pd.DataFrame()

def save_data(df):
    try:
        df.to_excel(INVENTARIO_FILE, index=False)
        now = datetime.now().strftime("%Y-%m-%d_%H-%M")
        backup_file = f"{BACKUP_DIR}/inventario_backup_{now}.xlsx"
        df.to_excel(backup_file, index=False)
        return True
    except Exception as e:
        st.error(f"❌ Error al guardar el archivo: {e}")
        return False

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

    with tab5:
        st.subheader("📝 Editar Inventario")

        if not df.empty:
            edited_df = st.data_editor(
                df,
                num_rows="dynamic",
                use_container_width=True,
                key="editor"
            )
            if st.button("💾 Guardar cambios"):
                success = save_data(edited_df)
                if success:
                    st.success("✅ Cambios guardados y respaldo creado.")
        else:
            st.warning("No hay datos para mostrar.")

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
