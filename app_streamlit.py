
import streamlit as st
import pandas as pd
import os
import plotly.express as px
from io import BytesIO




from openpyxl import Workbook

INVENTARIO_FILE = "inventario_cuentas.xlsx"
USUARIOS_FILE = "usuarios.xlsx"
BACKUP_DIR = "backups"
os.makedirs(BACKUP_DIR, exist_ok=True)

# Configurar colores por estado
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

def export_pdf(resumen):
    return None
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = [Paragraph("Resumen Gerencial - Dashboard AIPAD", styles["Title"]), Spacer(1, 12)]

    table_data = [resumen.columns.tolist()] + resumen.values.tolist()
    table = Table(table_data)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
        ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
        ("GRID", (0, 0), (-1, -1), 1, colors.black),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 24))
    elements.append(Paragraph("Este reporte contiene las métricas clave del avance del proyecto.", styles["Normal"]))
    doc.build(elements)
    buffer.seek(0)
    return buffer

def export_excel(df, resumen):
    buffer = BytesIO()
    wb = Workbook()
    ws = wb.active
    ws.title = "Resumen"
    for r in resumen.itertuples(index=False):
        ws.append(list(r))
    ws2 = wb.create_sheet("Facturas")
    ws2.append(df.columns.tolist())
    for row in df.itertuples(index=False):
        ws2.append(list(row))
    wb.save(buffer)
    buffer.seek(0)
    return buffer

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

                estado_sel = colf1.multiselect("Estado", sorted(estados), default=sorted(estados))
                eps_sel = colf2.multiselect("EPS", sorted(eps_lista), default=sorted(eps_lista))
                fecha_min = fechas.min() if not fechas.empty else None
                fecha_max = fechas.max() if not fechas.empty else None
                fecha_rango = colf3.date_input("Rango de fechas", (fecha_min, fecha_max))

                if fecha_rango and len(fecha_rango) == 2:
                    desde, hasta = pd.to_datetime(fecha_rango[0]), pd.to_datetime(fecha_rango[1])
                    df = df[(df["Estado"].isin(estado_sel)) &
                            (df["EPS"].isin(eps_sel)) &
                            (df["FechaRadicacion"] >= desde) &
                            (df["FechaRadicacion"] <= hasta)]

                total = len(df)
                radicadas = df[df["Estado"] == "Radicada"]
                total_valor = df["Valor"].sum() if "Valor" in df.columns else 0
                avance = round(len(radicadas) / total * 100, 2) if total else 0

                resumen_df = pd.DataFrame({
                    "Métrica": ["Total facturas", "Valor total", "Avance (%)"],
                    "Valor": [total, f"${total_valor:,.0f}", f"{avance}%"]
                })

                col1, col2, col3 = st.columns(3)
                col1.metric("📦 Total facturas", total)
                col2.metric("💰 Valor total", f"${total_valor:,.0f}")
                col3.metric("📊 Avance (radicadas)", f"{avance}%")

                colex = st.container()
                    # pdf_data = export_pdf(resumen_df)
                    # st.download_button(...) (PDF eliminado) file_name="dashboard_resumen.pdf", mime="application/pdf")
        st.download_button("📊 Descargar resumen Excel", export_excel(df, resumen_df), file_name="dashboard_resumen.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                    excel_data = export_excel(df, resumen_df)
        st.download_button("📊 Descargar resumen Excel", export_excel(df, resumen_df), file_name="dashboard_resumen.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

                st.markdown("---")

                fig_estado = px.pie(df, names="Estado", hole=0.4, title="Distribución por Estado",
                                    color="Estado", color_discrete_map=estado_colores)
                st.plotly_chart(fig_estado, use_container_width=True)

                st.markdown("## 🏥 Por EPS")
                col1, col2 = st.columns(2)
                with col1:
                    fig_valor_eps = px.bar(df, x="EPS", y="Valor", color="Estado", barmode="group",
                                           title="Valor total por EPS", text_auto=".2s", color_discrete_map=estado_colores)
                    fig_valor_eps.update_layout(xaxis={'categoryorder': 'total descending'})
                    st.plotly_chart(fig_valor_eps, use_container_width=True)
                with col2:
                    fig_count_eps = px.bar(df, x="EPS", title="Número de facturas por EPS",
                                           color="Estado", barmode="group", text_auto=True, color_discrete_map=estado_colores)
                    fig_count_eps.update_layout(xaxis={'categoryorder': 'total descending'})
                    st.plotly_chart(fig_count_eps, use_container_width=True)

                st.markdown("## 📅 Por Mes")
                if "Mes" in df.columns:
                    col1, col2 = st.columns(2)
                    with col1:
                        fig_valor_mes = px.area(df, x="Mes", y="Valor", title="Valor total por Mes",
                                                color="Estado", line_group="Estado", color_discrete_map=estado_colores)
                        st.plotly_chart(fig_valor_mes, use_container_width=True)
                    with col2:
                        fig_count_mes = px.bar(df, x="Mes", title="Facturas por Mes", color="Estado",
                                               barmode="stack", text_auto=True, color_discrete_map=estado_colores)
                        st.plotly_chart(fig_count_mes, use_container_width=True)

                st.markdown("## 📆 Por Vigencia")
                if "Vigencia" in df.columns:
                    col1, col2 = st.columns(2)
                    with col1:
                        fig_valor_vig = px.bar(df, x="Vigencia", y="Valor", color="Estado",
                                               barmode="group", title="Valor por Vigencia",
                                               text_auto=".2s", color_discrete_map=estado_colores)
                        st.plotly_chart(fig_valor_vig, use_container_width=True)
                    with col2:
                        fig_count_vig = px.pie(df, names="Vigencia", title="Distribución de Facturas por Vigencia", hole=0.4)
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