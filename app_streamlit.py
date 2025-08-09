# app_streamlit.py
# -*- coding: utf-8 -*-
APP_VERSION = "2025-08-09 02:10"

import streamlit as st
st.set_page_config(layout="wide")  # Debe ser lo primero en Streamlit

import pandas as pd
import os, re, io, zipfile, tempfile
import plotly.express as px
from datetime import datetime, date
import streamlit.components.v1 as components

# === Archivos esperados en la raíz ===
INVENTARIO_FILE = "inventario_cuentas.xlsx"
USUARIOS_FILE   = "usuarios.xlsx"

# Colores por estado
ESTADO_COLORES = {
    "Radicada": "green",
    "Pendiente": "red",
    "Auditada":  "orange",
    "Subsanada": "blue",
}

ESTADOS = ["Pendiente","Auditada","Subsanada","Radicada"]

MES_NOMBRE = {
    1:"Enero",2:"Febrero",3:"Marzo",4:"Abril",5:"Mayo",6:"Junio",
    7:"Julio",8:"Agosto",9:"Septiembre",10:"Octubre",11:"Noviembre",12:"Diciembre"
}

# ====== Helpers ======
def _to_ts(d):
    """Convierte date/datetime/str a Timestamp o NaT."""
    return pd.to_datetime(d, errors="coerce") if d not in (None, "", pd.NaT) else pd.NaT

def guardar_inventario(df: pd.DataFrame):
    """Guarda DataFrame al Excel y limpia caché."""
    try:
        # Usar openpyxl si está disponible; si no, CSV
        with pd.ExcelWriter(INVENTARIO_FILE, engine="openpyxl") as w:
            df.to_excel(w, index=False)
    except Exception:
        df.to_csv(Path(INVENTARIO_FILE).with_suffix(".csv"), index=False, encoding="utf-8-sig")
    st.cache_data.clear()

def registro_por_factura(df: pd.DataFrame, numero_factura: str):
    """Devuelve (existe, idx, fila_series) según NumeroFactura."""
    if "NumeroFactura" not in df.columns:
        return False, None, None
    mask = df["NumeroFactura"].astype(str).str.strip() == str(numero_factura).strip()
    if mask.any():
        idx = df[mask].index[0]
        return True, idx, df.loc[idx]
    return False, None, None

def _id_num(id_str):
    """Extrae el número del ID con formato CHIA-0001; si no coincide, intenta convertir a int.
       Retorna None si no hay número válido.
    """
    s = str(id_str).strip()
    m = re.match(r"^CHIA-(\d+)$", s)
    if m:
        try:
            return int(m.group(1))
        except:
            return None
    # fallback: intentar int directo
    try:
        return int(float(s))
    except:
        return None

def siguiente_id(df: pd.DataFrame):
    """Calcula el siguiente ID con prefijo CHIA-#### (relleno a 4 dígitos)."""
    if "ID" not in df.columns or df["ID"].dropna().empty:
        return "CHIA-0001"
    nums = df["ID"].apply(_id_num).dropna()
    n = int(nums.max()) + 1 if not nums.empty else 1
    return f"CHIA-{n:04d}"

def _set_query_params(**kwargs):
    # Compatibilidad con versiones nuevas/viejas de Streamlit
    try:
        st.query_params.clear()
        for k,v in kwargs.items():
            st.query_params[k] = v
    except Exception:
        st.experimental_set_query_params(**kwargs)

def _select_tab(label: str):
    """Fuerza seleccionar una pestaña por su etiqueta (helper con un poco de JS seguro)."""
    js = f"""
    <script>
    window.addEventListener('load', () => {{
        const labels = Array.from(parent.document.querySelectorAll('button[role="tab"]'));
        const target = labels.find(el => el.innerText.trim() === "{label}");
        if (target) target.click();
    }});
    </script>
    """
    components.html(js, height=0, scrolling=False)

# ====== DATA ======
@st.cache_data
def load_data():
    if not os.path.exists(INVENTARIO_FILE):
        # Estructura vacía si no existe
        cols = ["ID","NumeroFactura","Valor","EPS","Vigencia","Estado",
                "Mes","FechaRadicacion","FechaMovimiento","Observaciones"]
        return pd.DataFrame(columns=cols)
    df = pd.read_excel(INVENTARIO_FILE)

    # Normalizar fechas si existen
    for col in ["FechaRadicacion", "FechaMovimiento"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    # Asegurar columnas mínimas
    cols_needed = ["ID","NumeroFactura","Valor","EPS","Vigencia","Estado",
                   "Mes","FechaRadicacion","FechaMovimiento","Observaciones"]
    for c in cols_needed:
        if c not in df.columns:
            df[c] = pd.NA

    # Tipos
    df["Valor"] = pd.to_numeric(df["Valor"], errors="coerce")
    if "Vigencia" in df.columns:
        df["Vigencia"] = pd.to_numeric(df["Vigencia"], errors="coerce")

    # Normalizar textos clave
    if "Estado" in df.columns:
        df["Estado"] = df["Estado"].astype(str).str.strip()
        df.loc[~df["Estado"].isin(ESTADOS), "Estado"] = "Pendiente"

    return df

# ====== Auth ======
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
                st.rerun()
            else:
                st.sidebar.warning("Datos incorrectos")
        except Exception as e:
            st.sidebar.error(f"Error cargando usuarios: {e}")

# ====== Bandejas Helpers ======
def filtrar_por_estado(df: pd.DataFrame, estado: str, eps: str, vigencia, q: str):
    sub = df[df["Estado"] == estado].copy()
    if eps and eps != "Todos":
        sub = sub[sub["EPS"].astype(str) == eps]
    if vigencia and vigencia != "Todos":
        sub = sub[sub["Vigencia"].astype(str) == str(vigencia)]
    if q:
        qn = str(q).strip().lower()
        sub = sub[sub["NumeroFactura"].astype(str).str.lower().str.contains(qn)]
    return sub

def paginar(df: pd.DataFrame, page: int, per_page: int):
    total = len(df)
    total_pages = max((total - 1) // per_page + 1, 1)
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    end = start + per_page
    return df.iloc[start:end], total_pages, page

def aplicar_movimiento_masivo(df: pd.DataFrame, indices, nuevo_estado: str):
    ahora = pd.Timestamp(datetime.now())
    for idx in indices:
        df.at[idx, "Estado"] = nuevo_estado
        if nuevo_estado == "Radicada" and pd.isna(df.at[idx, "FechaRadicacion"]):
            # Si no tiene fecha, la definimos "hoy"
            df.at[idx, "FechaRadicacion"] = ahora.normalize()
            df.at[idx, "Mes"] = MES_NOMBRE.get(int(ahora.month), "")
        df.at[idx, "FechaMovimiento"] = ahora
    guardar_inventario(df)

# ====== Export helpers (Excel/PDF) ======
def exportar_dashboard_excel(df: pd.DataFrame) -> bytes:
    output = io.BytesIO()
    # Resúmenes iguales a lo mostrado en el dashboard
    total = len(df)
    radicadas = int((df["Estado"] == "Radicada").sum())
    total_valor = float(df["Valor"].fillna(0).sum())
    avance = round((radicadas / total) * 100, 2) if total else 0.0

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame({
            "Métrica": ["Total facturas", "Valor total", "% Avance (radicadas)"],
            "Valor": [total, total_valor, avance]
        }).to_excel(writer, index=False, sheet_name="Resumen")

        if {"EPS","NumeroFactura"}.issubset(df.columns):
            g_eps = df.groupby("EPS", dropna=False).agg(
                N_Facturas=("NumeroFactura","count"),
                Valor_Total=("Valor", "sum"),
                Radicadas=("Estado", lambda x: (x=="Radicada").sum())
            ).fillna(0)
            g_eps["% Avance"] = (g_eps["Radicadas"] / g_eps["N_Facturas"].replace(0, float("nan")) * 100).fillna(0).round(2)
            g_eps.to_excel(writer, sheet_name="Por_EPS")

        if {"Mes","NumeroFactura"}.issubset(df.columns):
            g_mes = df.groupby("Mes", dropna=False).agg(
                N_Facturas=("NumeroFactura","count"),
                Valor_Total=("Valor","sum"),
                Radicadas=("Estado", lambda x: (x=="Radicada").sum())
            ).fillna(0)
            g_mes["% Avance"] = (g_mes["Radicadas"] / g_mes["N_Facturas"].replace(0, float("nan")) * 100).fillna(0).round(2)
            g_mes.to_excel(writer, sheet_name="Por_Mes")

        if {"Vigencia","NumeroFactura"}.issubset(df.columns):
            g_vig = df.groupby("Vigencia", dropna=False).agg(
                N_Facturas=("NumeroFactura","count"),
                Valor_Total=("Valor","sum"),
                Radicadas=("Estado", lambda x: (x=="Radicada").sum())
            ).fillna(0)
            g_vig["% Avance"] = (g_vig["Radicadas"] / g_vig["N_Facturas"].replace(0, float("nan")) * 100).fillna(0).round(2)
            g_vig.to_excel(writer, sheet_name="Por_Vigencia")
    return output.getvalue()


def check_pdf_dependencies() -> tuple[bool, str]:
    try:
        import reportlab  # noqa: F401
    except Exception as e:
        return False, f"Falta reportlab: {e}"
    try:
        import kaleido  # noqa: F401
    except Exception as e:
        return False, f"Falta kaleido: {e}"
    try:
        import plotly.graph_objects as go
        # Prueba mínima de render a imagen en memoria
        fig = go.Figure(go.Scatter(x=[0,1], y=[0,1]))
        _ = fig.to_image(format="png", scale=1, engine="kaleido")
    except Exception as e:
        return False, f"Plotly/Kaleido no pudieron renderizar imágenes: {e}"
    return True, "OK"

def exportar_dashboard_pdf(df: pd.DataFrame) -> bytes:
    """Genera un PDF con KPIs + gráficos.
       Usa kaleido en memoria (sin archivos temporales) + reportlab.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader
    import plotly.express as px

    # Crear figuras (similares a las del dashboard)
    figs = []
    if "Estado" in df.columns:
        figs.append(px.pie(df, names="Estado", hole=0.4, title="Distribución por Estado",
                           color="Estado", color_discrete_map=ESTADO_COLORES))
    if {"EPS","Valor","Estado"}.issubset(df.columns):
        figs.append(px.bar(df, x="EPS", y="Valor", color="Estado", barmode="group",
                           title="Valor total por EPS", color_discrete_map=ESTADO_COLORES))
    if {"Mes","Estado","Valor"}.issubset(df.columns):
        figs.append(px.area(df, x="Mes", y="Valor", color="Estado",
                            title="Valor total por Mes", line_group="Estado",
                            color_discrete_map=ESTADO_COLORES))
    if {"Vigencia","Estado","Valor"}.issubset(df.columns):
        figs.append(px.bar(df, x="Vigencia", y="Valor", color="Estado", barmode="group",
                           title="Valor por Vigencia", color_discrete_map=ESTADO_COLORES))

    # Renderizar cada figura a PNG en memoria
    images = []
    for f in figs:
        img_bytes = f.to_image(format="png", scale=2, engine="kaleido")
        images.append(ImageReader(io.BytesIO(img_bytes)))

    # Crear PDF
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    W, H = A4

    total = len(df)
    radicadas = int((df["Estado"] == "Radicada").sum()) if "Estado" in df.columns else 0
    total_valor = float(df["Valor"].fillna(0).sum()) if "Valor" in df.columns else 0
    avance = round((radicadas / total) * 100, 2) if total else 0.0

    c.setFont("Helvetica-Bold", 14)
    c.drawString(2*cm, H-2*cm, "Dashboard - Resumen")
    c.setFont("Helvetica", 11)
    c.drawString(2*cm, H-3*cm, f"Total facturas: {total}")
    c.drawString(2*cm, H-3.6*cm, f"Valor total: ${total_valor:,.0f}")
    c.drawString(2*cm, H-4.2*cm, f"% Avance (radicadas): {avance}%")

    y = H-5.2*cm
    for img in images:
        c.drawImage(img, 2*cm, y-8*cm, width=W-4*cm, height=8*cm, preserveAspectRatio=True, anchor='n')
        y -= 9*cm
        if y < 6*cm:
            c.showPage()
            y = H-2*cm

    c.showPage()
    c.save()
    pdf_bytes = buf.getvalue()
    buf.close()
    return pdf_bytes


def main_app():
    st.caption(f"🆔 Versión: {APP_VERSION}")
    st.title("📊 AIPAD • Control de Radicación")
    if "usuario" in st.session_state and "rol" in st.session_state:
        st.markdown(f"👤 Usuario: `{st.session_state['usuario']}`  |  🔐 Rol: `{st.session_state['rol']}`")

    # Leer query param para re-seleccionar pestaña si aplica
    qp = {}
    try:
        qp = dict(st.query_params)
    except Exception:
        qp = st.experimental_get_query_params()

    df = load_data()

    tab_labels = ["📋 Dashboard", "🗂️ Bandejas", "📝 Gestión", "📑 Reportes"]
    tab1, tab2, tab3, tab4 = st.tabs(tab_labels)

    # Si hay query param ?tab=bandejas o ?tab=gestion, forzar selección
    if qp.get("tab", [""])[0] == "bandejas":
        _select_tab("🗂️ Bandejas")
    elif qp.get("tab", [""])[0] == "gestion":
        _select_tab("📝 Gestión")

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

            # --- EPS ---
            st.markdown("## 🏥 Por EPS")
            if {"EPS","NumeroFactura"}.issubset(df.columns):
                g = df.groupby("EPS", dropna=False).agg(
                    N_Facturas=("NumeroFactura","count"),
                    Valor_Total=("Valor", "sum"),
                    Radicadas=("Estado", lambda x: (x=="Radicada").sum())
                ).fillna(0)
                g["% Avance"] = (g["Radicadas"].astype(float)/g["N_Facturas"].replace(0, float("nan"))*100).fillna(0).round(2)
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
                        text=g["% Avance"].astype(str) + "%"
                    )
                    st.plotly_chart(fig_eps_cnt, use_container_width=True)

            # --- Mes ---
            st.markdown("## 📅 Por Mes")
            if {"Mes","NumeroFactura"}.issubset(df.columns):
                g = df.groupby("Mes", dropna=False).agg(
                    N_Facturas=("NumeroFactura","count"),
                    Valor_Total=("Valor","sum"),
                    Radicadas=("Estado", lambda x: (x=="Radicada").sum())
                ).fillna(0)
                g["% Avance"] = (g["Radicadas"].astype(float)/g["N_Facturas"].replace(0, float("nan"))*100).fillna(0).round(2)

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
                        text=g["% Avance"].astype(str) + "%"
                    )
                    st.plotly_chart(fig_mes_cnt, use_container_width=True)

            # --- Vigencia ---
            st.markdown("## 📆 Por Vigencia")
            if {"Vigencia","NumeroFactura"}.issubset(df.columns):
                g = df.groupby("Vigencia", dropna=False).agg(
                    N_Facturas=("NumeroFactura","count"),
                    Valor_Total=("Valor","sum"),
                    Radicadas=("Estado", lambda x: (x=="Radicada").sum())
                ).fillna(0)
                g["% Avance"] = (g["Radicadas"].astype(float)/g["N_Facturas"].replace(0, float("nan"))*100).fillna(0).round(2)

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

            # --- Descargas Dashboard ---
            st.divider()
            cdb1, cdb2 = st.columns(2)
            with cdb1:
                xls_bytes = exportar_dashboard_excel(df)
                st.download_button(
                    "⬇️ Descargar Dashboard a Excel",
                    data=xls_bytes,
                    file_name="dashboard_radicacion.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
            with cdb2:
                ok_deps, detail = check_pdf_dependencies()
                if ok_deps:
                    try:
                        pdf_bytes = exportar_dashboard_pdf(df)
                        st.download_button(
                            "⬇️ Descargar Dashboard en PDF",
                            data=pdf_bytes,
                            file_name="dashboard_radicacion.pdf",
                            mime="application/pdf",
                            use_container_width=True
                        )
                    except Exception as e:
                        st.error(f"No se pudo generar el PDF: {e}")
                else:
                    st.warning("PDF no disponible: " + detail)

    # ---- BANDEJAS (por estado, con filtros y paginación) ----
    with tab2:
        st.subheader("🗂️ Bandejas por estado")

        if df.empty:
            st.info("No hay datos para mostrar.")
        else:
            # Filtros globales de bandeja
            fc1, fc2, fc3, fc4 = st.columns([1.2,1,1,1])
            with fc1:
                q = st.text_input("🔎 Buscar factura (contiene)", key="bandeja_q")
            with fc2:
                eps_opts = ["Todos"] + sorted([e for e in df["EPS"].dropna().astype(str).unique().tolist() if e])
                eps_sel = st.selectbox("EPS", eps_opts, index=0, key="bandeja_eps")
            with fc3:
                vig_opts = ["Todos"] + sorted([str(int(v)) for v in pd.to_numeric(df["Vigencia"], errors="coerce").dropna().unique().tolist()])
                vig_sel = st.selectbox("Vigencia", vig_opts, index=0, key="bandeja_vig")
            with fc4:
                per_page = st.selectbox("Filas por página", [50, 100, 200], index=1, key="bandeja_pp")

            # Pestañas internas por estado
            tabs_estado = st.tabs(ESTADOS)

            for estado, tab in zip(ESTADOS, tabs_estado):
                with tab:
                    sub = filtrar_por_estado(df, estado, eps_sel, vig_sel, q)
                    sub = sub.sort_values(by=["FechaMovimiento","NumeroFactura"], ascending=[False, True])

                    # Estado de paginación en session_state
                    pg_key = f"page_{estado}"
                    if pg_key not in st.session_state:
                        st.session_state[pg_key] = 1

                    # Barra de paginación
                    sub_page, total_pages, current_page = paginar(sub, st.session_state[pg_key], per_page)
                    st.session_state[pg_key] = current_page  # normaliza rango

                    cpa, cpb, cpc = st.columns([1,2,1])
                    with cpa:
                        prev = st.button("⬅️ Anterior", key=f"prev_{estado}", disabled=(current_page<=1))
                    with cpc:
                        nextb = st.button("Siguiente ➡️", key=f"next_{estado}", disabled=(current_page>=total_pages))
                    with cpb:
                        st.markdown(f"**Página {current_page} / {total_pages}** &nbsp; &nbsp; (**{len(sub)}** registros)")

                    if prev:
                        st.session_state[pg_key] = max(1, current_page-1)
                        st.rerun()
                    if nextb:
                        st.session_state[pg_key] = min(total_pages, current_page+1)
                        st.rerun()

                    # Selección por fila en la página
                    st.divider()
                    sel_all_key = f"sel_all_{estado}_{current_page}"
                    sel_all = st.checkbox("Seleccionar todo (esta página)", key=sel_all_key, value=False)

                    cols_mostrar = ["ID","NumeroFactura","EPS","Vigencia","Valor","FechaRadicacion","FechaMovimiento","Observaciones"]
                    view = sub_page[cols_mostrar].copy()
                    view.insert(0, "Seleccionar", sel_all)
                    view.insert(1, "__idx", sub_page.index)

                    column_order = ["Seleccionar","ID","NumeroFactura","EPS","Vigencia","Valor","FechaRadicacion","FechaMovimiento","Observaciones","__idx"]

                    edited = st.data_editor(
                        view,
                        hide_index=True,
                        use_container_width=True,
                        num_rows="fixed",
                        column_config={
                            "Seleccionar": st.column_config.CheckboxColumn("Seleccionar", help="Marca las filas a mover", default=False),
                            "__idx": st.column_config.Column("", width="small", disabled=True),
                            "ID": st.column_config.Column("ID", disabled=True, width="small"),
                            "NumeroFactura": st.column_config.Column("Número de factura", disabled=True),
                            "EPS": st.column_config.Column("EPS", disabled=True),
                            "Vigencia": st.column_config.Column("Vigencia", disabled=True, width="small"),
                            "Valor": st.column_config.Column("Valor", disabled=True),
                            "FechaRadicacion": st.column_config.Column("Fecha Radicación", disabled=True),
                            "FechaMovimiento": st.column_config.Column("Fecha Movimiento", disabled=True),
                            "Observaciones": st.column_config.Column("Observaciones", disabled=True),
                        },
                        column_order=column_order[:-1],
                        key=f"editor_{estado}_{current_page}",
                    )

                    try:
                        mask = edited["Seleccionar"].fillna(False).tolist()
                    except Exception:
                        mask = [False] * len(sub_page)

                    seleccionados = [idx for pos, idx in enumerate(sub_page.index.tolist()) if pos < len(mask) and mask[pos]]

                    st.divider()
                    c1, c2 = st.columns([2,1])
                    with c1:
                        nuevo_estado = st.selectbox("Mover seleccionadas a:", [e for e in ESTADOS if e != estado], key=f"move_to_{estado}")
                    with c2:
                        mover = st.button("Aplicar movimiento", type="primary", key=f"aplicar_{estado}", disabled=(len(seleccionados)==0))

                    if mover:
                        aplicar_movimiento_masivo(df, seleccionados, nuevo_estado)
                        st.success(f"Se movieron {len(seleccionados)} facturas de {estado} → {nuevo_estado}")
                        _set_query_params(tab="bandejas")
                        st.rerun()

    # ---- GESTIÓN (Formulario) ----
    with tab3:
        st.subheader("📝 Gestión")

        df = load_data().copy()

        # Asegurar columnas mínimas
        cols_needed = ["ID","NumeroFactura","Valor","EPS","Vigencia","Estado",
                    "Mes","FechaRadicacion","FechaMovimiento","Observaciones"]
        for c in cols_needed:
            if c not in df.columns:
                df[c] = pd.NA

        # Tipos
        df["Valor"] = pd.to_numeric(df["Valor"], errors="coerce")
        for c in ["FechaRadicacion","FechaMovimiento"]:
            df[c] = pd.to_datetime(df[c], errors="coerce")

        # Búsqueda
        colb1, colb2 = st.columns([2,1])
        with colb1:
            q_factura = st.text_input("🔎 Buscar por Número de factura", key="buscar_factura_input")
        with colb2:
            buscar = st.button("Buscar / Cargar", type="primary")

        if buscar and q_factura.strip():
            st.session_state["factura_activa"] = q_factura.strip()

        numero_activo = st.session_state.get("factura_activa", "")

        if not numero_activo:
            st.info("Ingresa un número de factura y presiona **Buscar / Cargar** para editar o crear.")
        else:
            existe, idx, fila = registro_por_factura(df, numero_activo)
            st.caption(f"Factura seleccionada: **{numero_activo}** {'(existente)' if existe else '(nueva)'}")

            # Valores por defecto
            if existe:
                def_val = {
                    "ID": str(fila.get("ID","") if pd.notna(fila.get("ID","")) else ""),
                    "NumeroFactura": str(fila.get("NumeroFactura", numero_activo)),
                    "Valor": float(fila.get("Valor", 0) if pd.notna(fila.get("Valor",0)) else 0),
                    "EPS": str(fila.get("EPS","") if pd.notna(fila.get("EPS","")) else ""),
                    "Vigencia": int(fila.get("Vigencia", date.today().year)) if pd.notna(fila.get("Vigencia", pd.NA)) else date.today().year,
                    "Estado": str(fila.get("Estado","Pendiente") if pd.notna(fila.get("Estado", pd.NA)) else "Pendiente"),
                    "FechaRadicacion": fila.get("FechaRadicacion", pd.NaT),
                    "FechaMovimiento": fila.get("FechaMovimiento", pd.NaT),
                    "Observaciones": str(fila.get("Observaciones","") if pd.notna(fila.get("Observaciones", pd.NA)) else ""),
                    "Mes": str(fila.get("Mes","") if pd.notna(fila.get("Mes", pd.NA)) else ""),
                }
            else:
                def_val = {
                    "ID": "",  # se autoasigna
                    "NumeroFactura": numero_activo,
                    "Valor": 0.0,
                    "EPS": "",
                    "Vigencia": date.today().year,
                    "Estado": "Pendiente",
                    "FechaRadicacion": pd.NaT,
                    "FechaMovimiento": pd.NaT,
                    "Observaciones": "",
                    "Mes": ""
                }

            estados_opciones = ESTADOS
            eps_opciones = sorted([e for e in df["EPS"].dropna().astype(str).unique().tolist() if e]) or []
            vigencias = sorted([int(v) for v in pd.to_numeric(df["Vigencia"], errors="coerce").dropna().unique().tolist()] + [date.today().year])

            # ======= Estado y Fecha de Radicación fuera del form para habilitar al instante =======
            ctop1, ctop2, ctop3 = st.columns(3)
            with ctop1:
                st.text_input("ID (automático)", value=def_val["ID"] or "", disabled=True)
            with ctop2:
                est_val = st.selectbox(
                    "Estado",
                    options=estados_opciones,
                    index=estados_opciones.index(def_val["Estado"]) if def_val["Estado"] in estados_opciones else 0,
                    key="estado_val"
                )
            with ctop3:
                frad_disabled = (est_val != "Radicada")
                frad_val = st.date_input(
                    "Fecha de Radicación",
                    value=def_val["FechaRadicacion"].date() if pd.notna(def_val["FechaRadicacion"]) else date.today(),
                    disabled=frad_disabled,
                    key="frad_val"
                )

            # Fecha de movimiento mostrada (si existe), siempre bloqueada
            st.text_input(
                "Fecha de Movimiento (automática)",
                value=str(def_val["FechaMovimiento"].date()) if pd.notna(def_val["FechaMovimiento"]) else "",
                disabled=True
            )

            # ======= Resto del formulario =======
            with st.form("form_factura", clear_on_submit=False):
                c1, c2 = st.columns(2)
                with c1:
                    num_val = st.text_input("Número de factura", value=def_val["NumeroFactura"])
                    valor_val = st.number_input("Valor", min_value=0.0, step=1000.0, value=float(def_val["Valor"]))
                    eps_val = st.selectbox("EPS", options=[""] + eps_opciones, index=([""]+eps_opciones).index(def_val["EPS"]) if def_val["EPS"] in ([""]+eps_opciones) else 0)
                with c2:
                    vig_set = sorted(set(vigencias))
                    vig_val = st.selectbox("Vigencia", options=vig_set, index=vig_set.index(def_val["Vigencia"]) if def_val["Vigencia"] in vig_set else 0)
                    obs_val = st.text_area("Observaciones", value=def_val["Observaciones"], height=100)

                submit = st.form_submit_button("💾 Guardar cambios", type="primary")

            if submit:
                ahora = pd.Timestamp(datetime.now())
                # Tomar Estado y FechaRadicación de los widgets FUERA del form
                estado_actual = st.session_state.get("estado_val", def_val["Estado"])
                frad_widget = st.session_state.get("frad_val", date.today())
                frad_ts = _to_ts(frad_widget) if estado_actual == "Radicada" else pd.NaT
                mes_calc = MES_NOMBRE.get(int(frad_ts.month), "") if pd.notna(frad_ts) else def_val["Mes"]

                # Armar fila nueva (ID se autogenera si viene vacío, con prefijo CHIA-####)
                new_id = def_val["ID"]
                if not new_id:  # si está vacío o no existe
                    new_id = siguiente_id(df) if not existe else def_val["ID"]

                nueva = {
                    "ID": new_id,
                    "NumeroFactura": str(num_val).strip(),
                    "Valor": float(valor_val),
                    "EPS": eps_val.strip(),
                    "Vigencia": int(vig_val) if str(vig_val).isdigit() else vig_val,
                    "Estado": estado_actual,
                    "FechaRadicacion": frad_ts,
                    "Observaciones": obs_val.strip(),
                    "Mes": mes_calc
                }

                # ===== Reglas para FechaMovimiento: SOLO cuando cambia el Estado o es nuevo =====
                estado_anterior = str(fila.get("Estado","")) if existe else ""
                estado_cambio = (str(estado_actual) != estado_anterior) or (not existe)

                if existe:
                    nueva["FechaMovimiento"] = (ahora if estado_cambio else fila.get("FechaMovimiento", pd.NaT))
                else:
                    nueva["FechaMovimiento"] = ahora

                # Insertar/actualizar
                if existe:
                    for k, v in nueva.items():
                        df.at[idx, k] = v
                else:
                    df = pd.concat([df, pd.DataFrame([nueva])], ignore_index=True)

                try:
                    guardar_inventario(df)
                    st.success("✅ Cambios guardados. El formulario fue limpiado.")
                    # Limpiar formulario sin ir al Dashboard y mantener pestaña Gestión
                    st.session_state["factura_activa"] = ""
                    for k in ["estado_val", "frad_val", "buscar_factura_input"]:
                        if k in st.session_state:
                            del st.session_state[k]
                    _set_query_params(tab="gestion")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Error guardando el inventario: {e}")

    # ---- REPORTES ----
    with tab4:
        st.subheader("📑 Reportes")
        if df.empty:
            st.info("No hay datos en el inventario para generar reportes.")
        else:
            # KPIs
            total = len(df)
            valor_total = float(df["Valor"].fillna(0).sum())
            radicadas = int((df["Estado"] == "Radicada").sum())
            avance = round((radicadas / total) * 100, 2) if total else 0.0
            c1, c2, c3 = st.columns(3)
            c1.metric("Número de facturas", f"{total:,}")
            c2.metric("Valor total", f"${valor_total:,.0f}")
            c3.metric("% avance general", f"{avance}%")

            # Asegurar 'Mes' si hace falta
            if "Mes" not in df.columns:
                if "FechaRadicacion" in df.columns:
                    df["Mes"] = pd.to_datetime(df["FechaRadicacion"], errors="coerce").dt.to_period("M").astype(str)
                else:
                    df["Mes"] = "Sin Mes"

            # Gráficos
            st.markdown("### Gráficos")
            if {"EPS","Estado"}.issubset(df.columns):
                eps_count = df.groupby("EPS")["Estado"].count().reset_index(name="Facturas")
                fig_eps = px.bar(eps_count.sort_values("Facturas", ascending=False).head(25),
                                 x="EPS", y="Facturas", title="Facturas por EPS (Top 25)",
                                 text="Facturas")
                fig_eps.update_traces(texttemplate="%{text}", textposition="outside")
                fig_eps.update_layout(xaxis_tickangle=-45, uniformtext_minsize=10, uniformtext_mode="hide")
                st.plotly_chart(fig_eps, use_container_width=True)

            if {"Vigencia","Estado"}.issubset(df.columns):
                vig_estado = df.groupby(["Vigencia", "Estado"]).size().reset_index(name="Facturas")
                fig_vig = px.bar(vig_estado, x="Vigencia", y="Facturas", color="Estado",
                                 title="Distribución por Vigencia y Estado",
                                 color_discrete_map=ESTADO_COLORES)
                st.plotly_chart(fig_vig, use_container_width=True)

            if {"Mes","Estado"}.issubset(df.columns):
                mes_estado = df.groupby(["Mes", "Estado"]).size().reset_index(name="Facturas")
                mes_estado = mes_estado.sort_values("Mes")
                fig_mes = px.area(mes_estado, x="Mes", y="Facturas", color="Estado",
                                  groupnorm=None, title="Evolución mensual por Estado",
                                  color_discrete_map=ESTADO_COLORES)
                st.plotly_chart(fig_mes, use_container_width=True)

            # Tablas de resumen
            st.markdown("### Resúmenes")
            def tabla_resumen(df_, by, nombre):
                g = df_.groupby(by, dropna=False).agg(
                    Facturas=("Estado", "count"),
                    Valor=("Valor", "sum"),
                    Radicadas=("Estado", lambda s: (s == "Radicada").sum()),
                    Pendientes=("Estado", lambda s: (s == "Pendiente").sum()),
                    Auditadas=("Estado", lambda s: (s == "Auditada").sum()),
                    Subsanadas=("Estado", lambda s: (s == "Subsanada").sum()),
                ).reset_index()
                g["% Avance"] = (g["Radicadas"] / g["Facturas"]).fillna(0) * 100
                st.subheader(f"Resumen por {nombre}")
                st.dataframe(g, use_container_width=True)
                return g

            t_eps = tabla_resumen(df, "EPS", "EPS") if "EPS" in df.columns else pd.DataFrame()
            t_vig = tabla_resumen(df, "Vigencia", "Vigencia") if "Vigencia" in df.columns else pd.DataFrame()
            t_mes = tabla_resumen(df, "Mes", "Mes") if "Mes" in df.columns else pd.DataFrame()

            # Exportar a Excel
            st.markdown("### Descarga")
            def exportar_reportes_excel():
                out = io.BytesIO()
                with pd.ExcelWriter(out, engine="openpyxl") as writer:
                    pd.DataFrame(
                        {"Métrica": ["# Facturas", "Valor total", "% Avance general"],
                         "Valor": [total, valor_total, avance]}
                    ).to_excel(writer, index=False, sheet_name="Resumen")
                    if not t_eps.empty: t_eps.to_excel(writer, index=False, sheet_name="Por_EPS")
                    if not t_vig.empty: t_vig.to_excel(writer, index=False, sheet_name="Por_Vigencia")
                    if not t_mes.empty: t_mes.to_excel(writer, index=False, sheet_name="Por_Mes")
                return out.getvalue()

            xls_bytes_rep = exportar_reportes_excel()
            st.download_button(
                "⬇️ Descargar reportes a Excel",
                data=xls_bytes_rep,
                file_name="reportes_radicacion.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )

# ====== BOOT ======
if "autenticado" not in st.session_state:
    login()
elif st.session_state.get("autenticado"):
    main_app()
