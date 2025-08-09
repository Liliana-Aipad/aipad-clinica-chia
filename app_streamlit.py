# app_streamlit.py
# -*- coding: utf-8 -*-
APP_VERSION = "2025-08-09 05:15 (safe-view, NA fix)"

import streamlit as st
st.set_page_config(layout="wide")  # Debe ser lo primero en Streamlit

import pandas as pd
import os, re, io
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, date
import streamlit.components.v1 as components

# === Archivos esperados en la raíz ===
INVENTARIO_FILE = "inventario_cuentas.xlsx"
USUARIOS_FILE   = "usuarios.xlsx"

# Colores por estado (solo para gráficos)
ESTADO_COLORES = {
    "Radicada": "green",
    "Pendiente": "red",
    "Auditada":  "orange",
    "Subsanada": "blue",
}

# Lista de pestañas de estado para bandejas (no se usa para escribir)
ESTADOS = ["Pendiente","Auditada","Subsanada","Radicada"]

MES_NOMBRE = {
    1:"Enero",2:"Febrero",3:"Marzo",4:"Abril",5:"Mayo",6:"Junio",
    7:"Julio",8:"Agosto",9:"Septiembre",10:"Octubre",11:"Noviembre",12:"Diciembre"
}

# ====== Helpers ======
def _to_ts(d):
    """Convierte date/datetime/str a Timestamp o NaT de forma segura."""
    try:
        return pd.to_datetime(d, errors="coerce")
    except Exception:
        return pd.NaT

def guardar_inventario(df: pd.DataFrame):
    """Guarda DataFrame al Excel. SOLO se llama en Gestión o movimientos masivos."""
    try:
        with pd.ExcelWriter(INVENTARIO_FILE, engine="openpyxl") as w:
            df.to_excel(w, index=False)
    except Exception:
        # Fallback: CSV si no puede escribir xlsx
        df.to_csv("inventario_cuentas.csv", index=False, encoding="utf-8-sig")
    st.cache_data.clear()

def _id_num(id_str):
    s = str(id_str).strip()
    m = re.match(r"^CHIA-(\d+)$", s)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None
    try:
        return int(float(s))
    except Exception:
        return None

def siguiente_id(df: pd.DataFrame):
    if "ID" not in df.columns or df["ID"].dropna().empty:
        return "CHIA-0001"
    nums = df["ID"].apply(_id_num).dropna()
    n = int(nums.max()) + 1 if not nums.empty else 1
    return f"CHIA-{n:04d}"

def _set_query_params(**kwargs):
    try:
        st.query_params.clear()
        for k,v in kwargs.items():
            st.query_params[k] = v
    except Exception:
        st.experimental_set_query_params(**kwargs)

def _select_tab(label: str):
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

# ====== DATA (LOAD WITHOUT MUTATION) ======
@st.cache_data
def load_data():
    if not os.path.exists(INVENTARIO_FILE):
        # No crear columnas ni tocar datos; devolver DF vacío
        return pd.DataFrame()
    try:
        df = pd.read_excel(INVENTARIO_FILE)
    except Exception:
        # Si no se puede leer, devolver DF vacío (no inventar estructura)
        return pd.DataFrame()
    # NO normalizar ni corregir datos aquí
    # Convertir fechas a datetime de forma no destructiva para cálculos (no se guarda)
    for col in ["FechaRadicacion", "FechaMovimiento"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df

def build_view(df: pd.DataFrame) -> pd.DataFrame:
    """Crea una vista en memoria con columnas auxiliares para visualizar/filtrar sin tocar df."""
    view = df.copy()
    # Normalización NO destructiva de estado
    if "Estado" in view.columns:
        norm = view["Estado"].astype(str).str.strip().str.lower()
        mapa = {
            "radicada": "Radicada",
            "radicadas": "Radicada",
            "pendiente": "Pendiente",
            "auditada": "Auditada",
            "auditadas": "Auditada",
            "subsanada": "Subsanada",
            "subsanadas": "Subsanada",
        }
        view["EstadoCanon"] = norm.map(mapa).fillna(view["Estado"])
    else:
        view["EstadoCanon"] = "Pendiente"
    return view

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
                st.session_state["usuario"] = ok.iloc[0].get("Cedula","")
                st.session_state["rol"] = ok.iloc[0].get("Rol","")
                st.rerun()
            else:
                st.sidebar.warning("Datos incorrectos")
        except Exception as e:
            st.sidebar.error(f"Error cargando usuarios: {e}")

# ====== Bandejas Helpers ======
def filtrar_por_estado_view(df_view: pd.DataFrame, estado_canon: str, eps: str, vigencia, q: str):
    sub = df_view[df_view["EstadoCanon"] == estado_canon].copy()
    if eps and eps != "Todos" and "EPS" in sub.columns:
        sub = sub[sub["EPS"].astype(str) == eps]
    if vigencia and vigencia != "Todos" and "Vigencia" in sub.columns:
        sub = sub[sub["Vigencia"].astype(str) == str(vigencia)]
    if q and "NumeroFactura" in sub.columns:
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
    """Actualiza estados SOLO cuando el usuario lo pide explícitamente desde Bandejas."""
    ahora = pd.Timestamp(datetime.now())
    for idx in indices:
        if "Estado" in df.columns:
            df.at[idx, "Estado"] = nuevo_estado
        if nuevo_estado == "Radicada" and "FechaRadicacion" in df.columns and pd.isna(df.at[idx, "FechaRadicacion"]):
            df.at[idx, "FechaRadicacion"] = ahora.normalize()
        if "FechaMovimiento" in df.columns:
            df.at[idx, "FechaMovimiento"] = ahora
    guardar_inventario(df)

# ====== Export helpers (Excel) ======
def exportar_dashboard_excel(df_view: pd.DataFrame) -> bytes:
    output = io.BytesIO()
    # Métricas generales
    total = len(df_view)
    total_valor = float(df_view["Valor"].fillna(0).sum()) if "Valor" in df_view.columns else 0.0
    radicadas = int((df_view["EstadoCanon"] == "Radicada").sum())
    avance = round((radicadas / total) * 100, 2) if total else 0.0

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame({
            "Métrica": ["Total facturas", "Valor total", "% Avance (radicadas)"],
            "Valor": [total, total_valor, avance]
        }).to_excel(writer, index=False, sheet_name="Resumen")

        # EPS
        if {"EPS","NumeroFactura"}.issubset(df_view.columns):
            g_eps = df_view.groupby("EPS", dropna=False).agg(
                N_Facturas=("NumeroFactura","count"),
                Valor_Total=("Valor", "sum"),
                Radicadas=("EstadoCanon", lambda x: (x=="Radicada").sum())
            ).fillna(0)
            g_eps["% Avance"] = (g_eps["Radicadas"] / g_eps["N_Facturas"].replace(0, float("nan")) * 100).fillna(0).round(2)
            g_eps.to_excel(writer, sheet_name="Por_EPS")

        # Mes
        if {"Mes","NumeroFactura"}.issubset(df_view.columns):
            g_mes = df_view.groupby("Mes", dropna=False).agg(
                N_Facturas=("NumeroFactura","count"),
                Valor_Total=("Valor","sum"),
                Radicadas=("EstadoCanon", lambda x: (x=="Radicada").sum())
            ).fillna(0)
            g_mes["% Avance"] = (g_mes["Radicadas"] / g_mes["N_Facturas"].replace(0, float("nan")) * 100).fillna(0).round(2)
            g_mes.to_excel(writer, sheet_name="Por_Mes")

        # Vigencia
        if {"Vigencia","NumeroFactura"}.issubset(df_view.columns):
            g_vig = df_view.groupby("Vigencia", dropna=False).agg(
                N_Facturas=("NumeroFactura","count"),
                Valor_Total=("Valor","sum"),
                Radicadas=("EstadoCanon", lambda x: (x=="Radicada").sum())
            ).fillna(0)
            g_vig["% Avance"] = (g_vig["Radicadas"] / g_vig["N_Facturas"].replace(0, float("nan")) * 100).fillna(0).round(2)
            g_vig.to_excel(writer, sheet_name="Por_Vigencia")
    return output.getvalue()

# ====== APP ======
def main_app():
    st.caption(f"🆔 Versión: {APP_VERSION}")
    st.title("📊 AIPAD • Control de Radicación")
    if "usuario" in st.session_state and "rol" in st.session_state:
        st.markdown(f"👤 Usuario: `{st.session_state['usuario']}`  |  🔐 Rol: `{st.session_state['rol']}`")

    # Cargar datos (sin tocar archivo) y construir vista segura
    df = load_data()
    df_view = build_view(df)

    # Tabs
    tab_labels = ["📋 Dashboard", "🗂️ Bandejas", "📝 Gestión", "📑 Reportes", "📈 Avance"]
    tab1, tab2, tab3, tab4, tab5 = st.tabs(tab_labels)

    # ---- DASHBOARD ----
    with tab1:
        st.subheader("📈 Avance general del proyecto")
        if df_view.empty:
            st.info("No hay datos en el inventario.")
        else:
            total = len(df_view)
            total_valor = float(df_view["Valor"].fillna(0).sum()) if "Valor" in df_view.columns else 0.0
            radicadas = int((df_view["EstadoCanon"] == "Radicada").sum())
            avance = round((radicadas / total) * 100, 2) if total else 0.0

            c1, c2, c3 = st.columns(3)
            c1.metric("📦 Total facturas", total)
            c2.metric("💰 Valor total", f"${total_valor:,.0f}")
            c3.metric("📊 Avance (radicadas)", f"{avance}%")

            # Distribución por Estado (donut) usando EstadoCanon
            fig_estado = px.pie(
                df_view, names="EstadoCanon", hole=0.4, title="Distribución por Estado",
                color="EstadoCanon", color_discrete_map=ESTADO_COLORES
            )
            fig_estado.update_traces(textposition="inside", textinfo="percent+value")
            st.plotly_chart(fig_estado, use_container_width=True)

            # --- EPS ---
            st.markdown("## 🏥 Por EPS")
            if {"EPS","NumeroFactura"}.issubset(df_view.columns):
                # Métricas por EPS
                g = df_view.groupby("EPS", dropna=False).agg(
                    N_Facturas=("NumeroFactura","count"),
                    Valor_Total=("Valor", "sum"),
                    Radicadas=("EstadoCanon", lambda x: (x=="Radicada").sum())
                ).reset_index().fillna(0)
                g["% Avance"] = (g["Radicadas"].astype(float)/g["N_Facturas"].replace(0, float("nan"))*100).fillna(0).round(2)

                c1, c2 = st.columns(2)
                with c1:
                    # Embudo por # de facturas (Top 25) con cantidad (x) y % (texto)
                    g_sorted = g.sort_values("N_Facturas", ascending=False).head(25)
                    fig_funnel = px.funnel(g_sorted, x="N_Facturas", y="EPS", title="Cantidad y % por EPS")
                    # Añadir porcentaje como texto al lado del valor
                    fig_funnel.update_traces(text=g_sorted["% Avance"].astype(str) + "%")
                    st.plotly_chart(fig_funnel, use_container_width=True)

                with c2:
                    # Columnas de Valor radicado por EPS (solo Radicadas)
                    if {"EstadoCanon","Valor"}.issubset(df_view.columns):
                        df_rad = df_view[df_view["EstadoCanon"] == "Radicada"]
                        g_val = df_rad.groupby("EPS", dropna=False)["Valor"].sum().reset_index()
                        g_val = g_val.sort_values("Valor", ascending=False)
                        fig_val_eps = px.bar(g_val, x="EPS", y="Valor", title="Valor radicado por EPS (solo Radicadas)", text_auto=".2s")
                        fig_val_eps.update_layout(xaxis={'categoryorder':'total descending'})
                        st.plotly_chart(fig_val_eps, use_container_width=True)

            # --- Mes ---
            st.markdown("## 📅 Por Mes")
            if {"Mes","NumeroFactura"}.issubset(df_view.columns):
                g_mes = df_view.groupby("Mes", dropna=False).agg(
                    N_Facturas=("NumeroFactura","count"),
                    Valor_Total=("Valor","sum"),
                    Radicadas=("EstadoCanon", lambda x: (x=="Radicada").sum())
                ).reset_index().fillna(0)
                g_mes["% Avance"] = (g_mes["Radicadas"].astype(float)/g_mes["N_Facturas"].replace(0, float("nan"))*100).fillna(0).round(2)

                c1, c2 = st.columns(2)
                with c1:
                    fig_mes_val = px.area(
                        df_view, x="Mes", y="Valor", color="EstadoCanon",
                        title="Estados por Mes", line_group="EstadoCanon",
                        color_discrete_map=ESTADO_COLORES
                    )
                    st.plotly_chart(fig_mes_val, use_container_width=True)
                with c2:
                    fig_mes_cnt = px.bar(
                        g_mes, x="Mes", y="N_Facturas", title="Cantidad de facturas por Mes",
                    )
                    st.plotly_chart(fig_mes_cnt, use_container_width=True)

            # --- Vigencia ---
            st.markdown("## 📆 Por Vigencia")
            if {"Vigencia","NumeroFactura"}.issubset(df_view.columns):
                g_vig = df_view.groupby("Vigencia", dropna=False).agg(
                    N_Facturas=("NumeroFactura","count"),
                    Valor_Total=("Valor","sum"),
                    Radicadas=("EstadoCanon", lambda x: (x=="Radicada").sum())
                ).reset_index().fillna(0)
                g_vig["% Avance"] = (g_vig["Radicadas"].astype(float)/g_vig["N_Facturas"].replace(0, float("nan"))*100).fillna(0).round(2)

                c1, c2 = st.columns(2)
                with c1:
                    fig_vig_val = px.bar(
                        df_view, x="Vigencia", y="Valor", color="EstadoCanon", barmode="group",
                        title="Valor por Vigencia", color_discrete_map=ESTADO_COLORES, text_auto=".2s"
                    )
                    st.plotly_chart(fig_vig_val, use_container_width=True)
                with c2:
                    fig_vig_cnt = px.bar(
                        g_vig, x="Vigencia", y="N_Facturas", title="Cantidad por Vigencia"
                    )
                    st.plotly_chart(fig_vig_cnt, use_container_width=True)

            # Descarga Excel del Dashboard
            st.divider()
            xls_bytes = exportar_dashboard_excel(df_view)
            st.download_button(
                "⬇️ Descargar Dashboard a Excel",
                data=xls_bytes,
                file_name="dashboard_radicacion.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )

    # ---- BANDEJAS ----
    with tab2:
        st.subheader("🗂️ Bandejas por estado")
        if df_view.empty:
            st.info("No hay datos para mostrar.")
        else:
            # Filtros
            fc1, fc2, fc3, fc4 = st.columns([1.2,1,1,1])
            with fc1:
                q = st.text_input("🔎 Buscar factura (contiene)", key="bandeja_q")
            with fc2:
                eps_opts = ["Todos"] + sorted([e for e in df_view.get("EPS", pd.Series(dtype=str)).dropna().astype(str).unique().tolist() if e])
                eps_sel = st.selectbox("EPS", eps_opts, index=0, key="bandeja_eps")
            with fc3:
                vig_series = pd.to_numeric(df_view.get("Vigencia", pd.Series(dtype=float)), errors="coerce").dropna().astype(int)
                vig_opts = ["Todos"] + sorted([str(v) for v in vig_series.unique().tolist()])
                vig_sel = st.selectbox("Vigencia", vig_opts, index=0, key="bandeja_vig")
            with fc4:
                per_page = st.selectbox("Filas por página", [50, 100, 200], index=1, key="bandeja_pp")

            tabs_estado = st.tabs(ESTADOS)

            for estado, tab in zip(ESTADOS, tabs_estado):
                with tab:
                    sub_view = filtrar_por_estado_view(df_view, estado, eps_sel, vig_sel, q)
                    # Orden por movimiento si existe
                    sort_cols = [c for c in ["FechaMovimiento","NumeroFactura"] if c in sub_view.columns]
                    if sort_cols:
                        sub_view = sub_view.sort_values(by=sort_cols, ascending=[False, True] if len(sort_cols)==2 else False)

                    # Sincronizar con df REAL para poder actualizar (usamos índice original si existe)
                    # A falta de índice, usamos posición tras merge
                    sub = sub_view.copy()
                    sub["_row_index"] = sub_view.index

                    # Paginación
                    pg_key = f"page_{estado}"
                    if pg_key not in st.session_state:
                        st.session_state[pg_key] = 1
                    sub_page, total_pages, current_page = paginar(sub, st.session_state[pg_key], per_page)
                    st.session_state[pg_key] = current_page

                    cpa, cpb, cpc = st.columns([1,2,1])
                    with cpa:
                        prev = st.button("⬅️ Anterior", key=f"prev_{estado}", disabled=(current_page<=1))
                    with cpc:
                        nextb = st.button("Siguiente ➡️", key=f"next_{estado}", disabled=(current_page>=total_pages))
                    with cpb:
                        st.markdown(f"**Página {current_page} / {total_pages}** &nbsp; &nbsp; (**{len(sub_view)}** registros)")
                    if prev:
                        st.session_state[pg_key] = max(1, current_page-1); st.rerun()
                    if nextb:
                        st.session_state[pg_key] = min(total_pages, current_page+1); st.rerun()

                    # Selección en página
                    st.divider()
                    sel_all_key = f"sel_all_{estado}_{current_page}"
                    sel_all = st.checkbox("Seleccionar todo (esta página)", key=sel_all_key, value=False)

                    cols_mostrar = [c for c in ["ID","NumeroFactura","EPS","Vigencia","Valor","FechaRadicacion","FechaMovimiento","Observaciones"] if c in sub_page.columns]
                    view = sub_page[cols_mostrar].copy()
                    view.insert(0, "Seleccionar", sel_all)
                    view.insert(1, "__idx", sub_page["_row_index"])

                    column_order = [c for c in ["Seleccionar","ID","NumeroFactura","EPS","Vigencia","Valor","FechaRadicacion","FechaMovimiento","Observaciones","__idx"] if c in view.columns]

                    edited = st.data_editor(
                        view,
                        hide_index=True,
                        use_container_width=True,
                        num_rows="fixed",
                        column_config={
                            "Seleccionar": st.column_config.CheckboxColumn("Seleccionar", help="Marca las filas a mover", default=False),
                            "__idx": st.column_config.Column("", width="small", disabled=True),
                        },
                        column_order=column_order[:-1] if "__idx" in column_order else column_order,
                        key=f"editor_{estado}_{current_page}",
                    )

                    try:
                        mask = edited["Seleccionar"].fillna(False).tolist()
                    except Exception:
                        mask = [False] * len(sub_page)

                    seleccionados_view_idx = [idx for pos, idx in enumerate(sub_page["_row_index"].tolist()) if pos < len(mask) and mask[pos]]

                    st.divider()
                    c1, c2 = st.columns([2,1])
                    with c1:
                        nuevo_estado = st.selectbox("Mover seleccionadas a:", [e for e in ESTADOS if e != estado], key=f"move_to_{estado}")
                    with c2:
                        mover = st.button("Aplicar movimiento", type="primary", key=f"aplicar_{estado}", disabled=(len(seleccionados_view_idx)==0))

                    if mover:
                        # Mapear índices de la vista al df real
                        indices_reales = seleccionados_view_idx
                        aplicar_movimiento_masivo(df, indices_reales, nuevo_estado)
                        st.success(f"Se movieron {len(indices_reales)} facturas de {estado} → {nuevo_estado}")
                        _set_query_params(tab="bandejas")
                        st.rerun()

    # ---- GESTIÓN ----
    with tab3:
        st.subheader("📝 Gestión")
        if df.empty:
            st.info("No hay datos de inventario.")
        else:
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
                # Localizar por NumeroFactura (exacto)
                if "NumeroFactura" in df.columns:
                    mask = df["NumeroFactura"].astype(str).str.strip() == str(numero_activo).strip()
                    existe = bool(mask.any())
                    idx = df[mask].index[0] if existe else None
                    fila = df.loc[idx] if existe else pd.Series(dtype="object")
                else:
                    existe, idx, fila = False, None, pd.Series(dtype="object")

                st.caption(f"Factura seleccionada: **{numero_activo}** {'(existente)' if existe else '(nueva)'}")

                # Valores por defecto NO alteran df
                def _get(row, col, fallback):
                    try:
                        v = row.get(col, fallback)
                        return v if not (isinstance(v, float) and pd.isna(v)) else fallback
                    except Exception:
                        return fallback

                def_val = {
                    "ID": _get(fila, "ID", "" if not existe else "" if pd.isna(fila.get("ID", pd.NA)) else str(fila.get("ID"))),
                    "NumeroFactura": numero_activo,
                    "Valor": float(_get(fila, "Valor", 0.0) or 0.0),
                    "EPS": str(_get(fila, "EPS", "")),
                    "Vigencia": int(_get(fila, "Vigencia", date.today().year)) if str(_get(fila, "Vigencia", "")).isdigit() else date.today().year,
                    "Estado": str(_get(fila, "Estado", "Pendiente")),
                    "FechaRadicacion": _to_ts(_get(fila, "FechaRadicacion", pd.NaT)),
                    "FechaMovimiento": _to_ts(_get(fila, "FechaMovimiento", pd.NaT)),
                    "Observaciones": str(_get(fila, "Observaciones", "")),
                    "Mes": str(_get(fila, "Mes", "")),
                }

                ctop1, ctop2, ctop3 = st.columns(3)
                with ctop1:
                    st.text_input("ID (automático)", value=def_val["ID"] or "", disabled=True)
                with ctop2:
                    estados_opciones = ESTADOS  # no normalizamos aquí
                    try:
                        init_idx = estados_opciones.index(def_val["Estado"]) if def_val["Estado"] in estados_opciones else 0
                    except Exception:
                        init_idx = 0
                    est_val = st.selectbox("Estado", options=estados_opciones, index=init_idx, key="estado_val")
                with ctop3:
                    frad_disabled = (est_val != "Radicada")
                    # Si def_val["FechaRadicacion"] es NaT o None, usar hoy como valor por defecto, pero no escribirlo automáticamente
                    frad_default = def_val["FechaRadicacion"]
                    if pd.isna(frad_default):
                        frad_default = date.today()
                    else:
                        try:
                            frad_default = frad_default.date()
                        except Exception:
                            frad_default = date.today()
                    frad_val = st.date_input("Fecha de Radicación", value=frad_default, disabled=frad_disabled, key="frad_val")

                st.text_input(
                    "Fecha de Movimiento (automática)",
                    value=str(def_val["FechaMovimiento"].date()) if pd.notna(def_val["FechaMovimiento"]) else "",
                    disabled=True
                )

                with st.form("form_factura", clear_on_submit=False):
                    c1, c2 = st.columns(2)
                    with c1:
                        num_val = st.text_input("Número de factura", value=def_val["NumeroFactura"])
                        valor_val = st.number_input("Valor", min_value=0.0, step=1000.0, value=float(def_val["Valor"]))
                        eps_val = st.text_input("EPS", value=def_val["EPS"])
                    with c2:
                        vig_val = st.number_input("Vigencia", step=1, value=int(def_val["Vigencia"]))
                        obs_val = st.text_area("Observaciones", value=def_val["Observaciones"], height=100)

                    submit = st.form_submit_button("💾 Guardar cambios", type="primary")

                if submit:
                    ahora = pd.Timestamp(datetime.now())

                    estado_actual = st.session_state.get("estado_val", def_val["Estado"])
                    frad_widget = st.session_state.get("frad_val", None)
                    frad_ts = _to_ts(frad_widget) if (estado_actual == "Radicada") else pd.NaT

                    # NO tocar 'Mes' automáticamente salvo que esté vacío y tengamos FechaRadicación válida
                    mes_val = def_val["Mes"]
                    is_mes_vacio = (mes_val is None) or pd.isna(mes_val) or (str(mes_val).strip() == "")
                    if is_mes_vacio and pd.notna(frad_ts):
                        mes_val = MES_NOMBRE.get(int(frad_ts.month), "")

                    nueva = {
                        "ID": def_val["ID"] or (siguiente_id(df) if not existe else def_val["ID"]),
                        "NumeroFactura": str(num_val).strip(),
                        "Valor": float(valor_val),
                        "EPS": str(eps_val).strip(),
                        "Vigencia": int(vig_val) if str(vig_val).isdigit() else vig_val,
                        "Estado": estado_actual,
                        "FechaRadicacion": frad_ts if (estado_actual == "Radicada") else def_val["FechaRadicacion"],
                        "Observaciones": str(obs_val).strip(),
                        "Mes": mes_val,
                        # FechaMovimiento SOLO cuando cambia el estado o si es nueva
                        "FechaMovimiento": ahora if (not existe or estado_actual != def_val["Estado"]) else def_val["FechaMovimiento"],
                    }

                    # Insertar/actualizar
                    if existe:
                        for k, v in nueva.items():
                            df.at[idx, k] = v
                    else:
                        # Si el archivo está vacío, crear columnas a partir de 'nueva'
                        if df.empty:
                            df = pd.DataFrame([nueva])
                        else:
                            df = pd.concat([df, pd.DataFrame([nueva])], ignore_index=True)

                    try:
                        guardar_inventario(df)
                        st.success("✅ Cambios guardados.")
                        # Mantenerse en Gestión
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
        if df_view.empty:
            st.info("No hay datos en el inventario para generar reportes.")
        else:
            total = len(df_view)
            valor_total = float(df_view["Valor"].fillna(0).sum()) if "Valor" in df_view.columns else 0.0
            radicadas = int((df_view["EstadoCanon"] == "Radicada").sum())
            avance = round((radicadas / total) * 100, 2) if total else 0.0
            c1, c2, c3 = st.columns(3)
            c1.metric("Número de facturas", f"{total:,}")
            c2.metric("Valor total", f"${valor_total:,.0f}")
            c3.metric("% avance general", f"{avance}%")

            st.markdown("### Gráficos")
            if {"EPS","NumeroFactura"}.issubset(df_view.columns):
                eps_count = df_view.groupby("EPS")["NumeroFactura"].count().reset_index(name="Facturas")
                fig_eps_funnel = px.funnel(eps_count.sort_values("Facturas", ascending=False).head(25),
                                           x="Facturas", y="EPS", title="Embudo por EPS (Top 25, # de facturas)")
                st.plotly_chart(fig_eps_funnel, use_container_width=True)

            if {"Vigencia","NumeroFactura"}.issubset(df_view.columns):
                vig_estado = df_view.groupby("Vigencia")["NumeroFactura"].count().reset_index(name="Facturas")
                fig_vig_donut = px.pie(vig_estado, names="Vigencia", values="Facturas",
                                       hole=0.4, title="Participación por Vigencia")
                fig_vig_donut.update_traces(textposition="inside", textinfo="percent+value")
                st.plotly_chart(fig_vig_donut, use_container_width=True)

            if {"Mes","NumeroFactura"}.issubset(df_view.columns):
                mes_sum = df_view.groupby("Mes")["NumeroFactura"].count().reset_index(name="Facturas")
                fig_mes_donut = px.pie(mes_sum, names="Mes", values="Facturas",
                                       hole=0.4, title="Participación por Mes")
                fig_mes_donut.update_traces(textposition="inside", textinfo="percent+value")
                st.plotly_chart(fig_mes_donut, use_container_width=True)

            st.markdown("### Resúmenes")
            def tabla_resumen(df_, by, nombre):
                g = df_.groupby(by, dropna=False).agg(
                    Facturas=("NumeroFactura", "count"),
                    Valor=("Valor", "sum"),
                    Radicadas=("EstadoCanon", lambda s: (s == "Radicada").sum()),
                    Pendientes=("EstadoCanon", lambda s: (s == "Pendiente").sum()),
                    Auditadas=("EstadoCanon", lambda s: (s == "Auditada").sum()),
                    Subsanadas=("EstadoCanon", lambda s: (s == "Subsanada").sum()),
                ).reset_index()
                g["% Avance"] = (g["Radicadas"] / g["Facturas"]).fillna(0) * 100
                st.subheader(f"Resumen por {nombre}")
                st.dataframe(g, use_container_width=True)
                return g

            t_eps = tabla_resumen(df_view, "EPS", "EPS") if "EPS" in df_view.columns else pd.DataFrame()
            t_vig = tabla_resumen(df_view, "Vigencia", "Vigencia") if "Vigencia" in df_view.columns else pd.DataFrame()
            t_mes = tabla_resumen(df_view, "Mes", "Mes") if "Mes" in df_view.columns else pd.DataFrame()

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

    # ---- AVANCE ----
    with tab5:
        st.subheader("📈 Avance (Real vs Proyectado — Acumulado)")

        # Proyección mensual proporcionada por el usuario (no Excel). Se calcula acumulado y %.
        mensual = pd.DataFrame({
            "Mes": ["Agosto 2025", "Septiembre 2025", "Octubre 2025", "Noviembre 2025"],
            "Cuentas estimadas": [515, 1489, 1797, 1738],
        })
        proy = mensual.copy()
        proy["Cuentas estimadas acumuladas"] = proy["Cuentas estimadas"].cumsum()
        total_meta = float(proy["Cuentas estimadas"].sum())
        proy["% proyectado acumulado"] = (proy["Cuentas estimadas acumuladas"] / total_meta * 100).round(2) if total_meta else 0.0

        if df_view.empty:
            st.info("No hay datos reales para comparar aún.")
        else:
            # Normalizar llave de mes real (usa FechaRadicacion si existe; si 'Mes' ya incluye año, usarla; si no, Mes+Vigencia; último: 'Sin Mes')
            def _etiqueta_mes(row):
                fr = row.get("FechaRadicacion", pd.NaT)
                if pd.notna(fr):
                    fr = pd.to_datetime(fr, errors="coerce")
                    if pd.notna(fr):
                        return f"{MES_NOMBRE.get(int(fr.month), '')} {int(fr.year)}"
                m = str(row.get("Mes", "")).strip()
                if re.search(r"\b20\d{2}\b", m):
                    return m
                vig = str(row.get("Vigencia", "")).strip()
                if m and vig.isdigit():
                    return f"{m} {vig}"
                return m or "Sin Mes"

            df_rad = df_view[df_view["EstadoCanon"] == "Radicada"].copy()
            if not df_rad.empty:
                df_rad["MesClave"] = df_rad.apply(_etiqueta_mes, axis=1)
                # Contar facturas únicas por MesClave
                if "NumeroFactura" in df_rad.columns:
                    reales = df_rad.groupby("MesClave")["NumeroFactura"].nunique().reset_index(name="Cuentas reales")
                else:
                    reales = df_rad.groupby("MesClave").size().reset_index(name="Cuentas reales")
            else:
                reales = pd.DataFrame(columns=["MesClave","Cuentas reales"])

            comp = proy.merge(reales, left_on="Mes", right_on="MesClave", how="left").drop(columns=["MesClave"], errors="ignore").fillna(0)
            comp["Cuentas reales"] = comp["Cuentas reales"].astype(int)
            comp["Cuentas reales acumuladas"] = comp["Cuentas reales"].cumsum()
            comp["% real acumulado"] = (comp["Cuentas reales acumuladas"] / total_meta * 100).round(2) if total_meta else 0.0
            comp["Diferencia % (Real - Proy)"] = (comp["% real acumulado"] - comp["% proyectado acumulado"]).round(2)

            st.dataframe(comp, use_container_width=True)

            fig = go.Figure()
            fig.add_trace(go.Scatter(x=comp["Mes"], y=comp["% proyectado acumulado"], mode='lines+markers', name='Proyectado'))
            fig.add_trace(go.Scatter(x=comp["Mes"], y=comp["% real acumulado"], mode='lines+markers', name='Real'))
            fig.update_layout(title="Avance acumulado (%) — Real vs Proyectado", yaxis_title="% acumulado", xaxis_title="Mes")
            st.plotly_chart(fig, use_container_width=True)

            # KPIs
            total_real = int(comp["Cuentas reales"].sum())
            avance_real_total = (total_real / total_meta * 100) if total_meta else 0.0
            c1, c2, c3 = st.columns(3)
            c1.metric("Meta total (cuentas)", f"{int(total_meta):,}")
            c2.metric("Reales acumuladas", f"{total_real:,}")
            c3.metric("Avance total vs meta", f"{avance_real_total:.1f}%")

# ====== BOOT ======
if "autenticado" not in st.session_state:
    login()
elif st.session_state.get("autenticado"):
    main_app()
