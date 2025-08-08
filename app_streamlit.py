import streamlit as st
import pandas as pd
from datetime import datetime

st.set_page_config(page_title="AIPAD Clínica Chía", layout="wide")

# --- Tabs ---
tab_gestion, tab_dashboard, tab_kanban = st.tabs(["🛠️ Gestión", "📋 Dashboard", "📌 Kanban"])

# --- Gestión ---
with tab_gestion:
    st.subheader("🛠️ Gestión")
    st.write("Aquí iría tu formulario de captura y edición del inventario...")
    # Ejemplo mínimo de formulario
    factura_id = st.text_input("ID", "CHIA-0001", disabled=True)
    estado = st.selectbox("Estado", ["Pendiente", "Auditada", "Subsanada", "Radicada"])
    fecha_mov = st.date_input("Fecha de Movimiento", datetime.today(), disabled=True)
    if estado == "Radicada":
        fecha_rad = st.date_input("Fecha de Radicación", datetime.today())
    else:
        fecha_rad = st.date_input("Fecha de Radicación", datetime.today(), disabled=True)
    if st.button("💾 Guardar cambios"):
        st.success("Cambios guardados correctamente.")
        st.experimental_rerun()  # Volverá a la primera pestaña (Gestión)

# --- Dashboard ---
with tab_dashboard:
    st.subheader("📋 Dashboard")
    st.write("Aquí irían tus gráficos por EPS, Mes y Vigencia.")

# --- Kanban ---
with tab_kanban:
    st.subheader("📌 Kanban")
    st.write("Aquí iría el tablero Kanban.")

