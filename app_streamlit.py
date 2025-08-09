# app_streamlit.py
# -*- coding: utf-8 -*-
APP_VERSION = "2025-08-09 05:05 (dashboard fix + safe states)"

import streamlit as st
st.set_page_config(layout="wide", page_title="AIPAD • Control de Radicación")

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, date
import os, re, io
import streamlit.components.v1 as components

# === Archivos esperados en la raíz ===
INVENTARIO_FILE = "inventario_cuentas.xlsx"
USUARIOS_FILE   = "usuarios.xlsx"

# Colores por estado (para vistas)
ESTADO_COLORES = {
    "Radicada": "green",
    "Pendiente": "red",
    "Auditada":  "orange",
    "Subsanada": "blue",
}

# Estados de trabajo (para Bandejas/Gestión). NO se fuerza sobre tus datos.
ESTADOS = ["Pendiente","Auditada","Subsanada","Radicada"]

MES_NOMBRE = {
    1:"Enero",2:"Febrero",3:"Marzo",4:"Abril",5:"Mayo",6:"Junio",
    7:"Julio",8:"Agosto",9:"Septiembre",10:"Octubre",11:"Noviembre",12:"Diciembre"
}

# =================== Helpers ===================
def _to_ts(d):
    """Convierte date/datetime/str a Timestamp o NaT."""
    return pd.to_datetime(d, errors="coerce") if d not in (None, "", pd.NaT) else pd.NaT

def guardar_inventario(df: pd.DataFrame):
    """Guarda DataFrame al Excel (solo cuando tú guardas) y limpia caché."""
    try:
        with pd.ExcelWriter(INVENTARIO_FILE, engine="openpyxl") as w:
            df.to_excel(w, index=False)
    except Exception:
        # fallback a CSV si algo ocurre con openpyxl
        df.to_csv("inventario_cuentas.csv", index=False, encoding="utf-8-sig")
    st.cache_data.clear()

@st.cache_data
def load_data():
    """Lee inventario SIN modificar valores. Solo tipifica fechas y asegura columnas inexistentes en memoria."""
    if not os.path.exists(INVENTARIO_FILE):
        cols = ["ID","NumeroFactura","Valor","EPS","Vigencia","Estado",
                "Mes","FechaRadicacion","FechaMovimiento","Observaciones"]
        return pd.DataFrame(columns=cols)
    df = pd.read_excel(INVENTARIO_FILE)

    # Tipificar fechas si existen (no cambia archivo, solo vista)
    for col in ["FechaRadicacion","FechaMovimiento"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    # Asegurar columnas mínimas en memoria (no se escriben hasta guardar)
    cols_needed = ["ID","NumeroFactura","Valor","EPS","Vigencia","Estado",
                   "Mes","FechaRadicacion","FechaMovimiento","Observaciones"]
    for c in cols_needed:
        if c not in df.columns:
            df[c] = pd.NA

    # Tipos amables (en memoria)
    df["Valor"] = pd.to_numeric(df["Valor"], errors="coerce")
    if "Vigencia" in df.columns:
        df["Vigencia"] = pd.to_numeric(df["Vigencia"], errors="coerce")

    # NO normalizamos Estado en df real
    return df

def _id_num(id_str):
    s = str(id_str).strip()
    m = re.match(r"^CHIA-(\d+)$", s)
    if m:
        try: return int(m.group(1))
        except: return None
    try: return int(float(s))
    except: return None

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

# =================== Auth ===================
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

# =================== Bandejas helpers ===================
def filtrar_por_estado(df: pd.DataFrame, estado: str, eps: str, vigencia, q: str):
    """Usa el estado REAL, no el canon. Así no se esconde nada de tu archivo."""
    sub = df[df["Estado"].astype(str).str.strip() == estado].copy()
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
            df.at[idx, "FechaRadicacion"] = ahora.normalize()
            df.at[idx, "Mes"] = MES_NOMBRE.get(int(ahora.month), "")
        df.at[idx, "FechaMovimiento"] = ahora
    guardar_inventario(df)

# =================== Export helpers (Excel) ===================
def exportar_dashboard_excel(df_view: pd.DataFrame) -> bytes:
    out = io.BytesIO()
    total = len(df_view)
    radicadas = int((df_view["EstadoCanon"] == "Radicada").sum())
    total_valor = float(df_view["Valor"].fillna(0).sum())
    avance = round((radicadas / total) * 100, 2) if total else 0.0

    with pd.ExcelWriter(out, engine="openpyxl") as w:
        pd.DataFrame({
            "Métrica": ["Total facturas", "Valor total", "% Avance (radicadas)"],
            "Valor": [total, total_valor, avance]
        }).to_excel(w, index=False, sheet_name="Resumen")

        if {"EPS","NumeroFactura"}.issubset(df_view.columns):
            g_eps = df_view.groupby("EPS", dropna=False).agg(
                N_Facturas=("NumeroFactura","count"),
                Valor_Total=("Valor", "sum"),
                Radicadas=("EstadoCanon", lambda x: (x=="Radicada").sum())
            ).fillna(0)
            g_eps["% Avance"] = (g_eps["Radicadas"] / g_eps["N_Facturas"].replace(0, float("nan")) * 100).fillna(0).round(2)
            g_eps.to_excel(w, sheet_name="Por_EPS")

        if {"Vigencia","NumeroFactura"}.issubset(df_view.columns):
            g_vig = df_view.groupby("Vigencia", dropna=False).agg(
                N_Facturas=("NumeroFactura","count"),
                Valor_Total=("Valor","sum"),
                Radicadas=("EstadoCanon", lambda x: (x=="Radicada").sum())
            ).fillna(0)
            g_vig["% Avance"] = (g_vig["Radicadas"] / g_vig["N_Facturas"].replace(0, float("nan")) * 100).fillna(0).round(2)
            g_vig.to_excel(w, sheet_name="Por_Vigencia")
    return out.getvalue()

# =================== APP ===================
def main_app():
    st.caption(f"🆔 Versión: {APP_VERSION}")
    st.title("📊 AIPAD • Control de Radicación")
    if "usuario" in st.session_state and "rol" in st.session_state:
        st.markdown(f"👤 Usuario: `{st.session_state['usuario']}`  |  🔐 Rol: `{st.session_state['rol']}`")

    qp = {}
    try: qp = dict(st.query_params)
    except Exception: qp = st.experimental_get_query_params()

    # ----------- Cargar DF real -----------
    df = load_data()

    # ----------- Crear vista segura (no escribe) -----------
    df_view = df.copy()
    # EstadoCanon solo para métricas y gráficos
    norm = df_view["Estado"].astype(str).str.strip().str.lower()
    mapa = {
        "radicada":"Radicada","radicadas":"Radicada",
        "pendiente":"Pendiente","pendientes":"Pendiente",
        "auditada":"Auditada","auditadas":"Auditada",
        "subsanada":"Subsanada","subsanadas":"Subsanada",
    }
    df_view["EstadoCanon"] = norm.map(mapa).fillna(df_view["Estado"])
    # Asegurar numérico en valor para la vista
    df_view["Valor"] = pd.to_numeric(df_view["Valor"], errors="coerce")

    tab_labels = ["📋 Dashboard", "🗂️ Bandejas", "📝 Gestión", "📑 Reportes", "📈 Avance"]
    tab1, tab2, tab3, tab4, tab5 = st.tabs(tab_labels)

    if qp.get("tab", [""])[0] == "bandejas":
        _select_tab("🗂️ Bandejas")
    elif qp.get("tab", [""])[0] == "gestion":
        _select_tab("📝 Gestión")

    # =================== DASHBOARD ===================
    with tab1:
        st.subheader("📈 Avance general del proyecto")
        if df_view.empty:
            st.info("No hay datos en el inventario.")
        else:
            total = len(df_view)
            radicadas = int((df_view["EstadoCanon"] == "Radicada").sum())
            total_valor = float(df_view["Valor"].fillna(0).sum())
            avance = round((radicadas / total) * 100, 2) if total else 0.0

            c1, c2, c3 = st.columns(3)
            c1.metric("📦 Total facturas", total)
            c2.metric("💰 Valor total", f"${total_valor:,.0f}")
            c3.metric("📊 Avance (radicadas)", f"{avance}%")

            # ----------------- Por EPS -----------------
            st.markdown("## 🏥 Por EPS")
            if {"EPS","NumeroFactura"}.issubset(df_view.columns):
                # Embudo: cantidad y % por EPS (Top 25)
                g_cnt = df_view.groupby("EPS", dropna=False)["NumeroFactura"].nunique().reset_index(name="Cuentas")
                g_cnt = g_cnt.sort_values("Cuentas", ascending=False).head(25)
                total_cnt = g_cnt["Cuentas"].sum() or 1
                g_cnt["%"] = (g_cnt["Cuentas"] / total_cnt * 100).round(1)
                g_cnt["Label"] = g_cnt["Cuentas"].astype(str) + " (" + g_cnt["%"].astype(str) + "%)"
                fig_funnel = px.funnel(g_cnt, x="Cuentas", y="EPS", title="Cantidad y % por EPS")
                fig_funnel.update_traces(text=g_cnt["Label"], textposition="inside")
                c1_, c2_ = st.columns(2)
                with c1_:
                    st.plotly_chart(fig_funnel, use_container_width=True)

                # Columnas: valor radicado por EPS (solo Radicadas)
                with c2_:
                    df_rad = df_view[df_view["EstadoCanon"] == "Radicada"].copy()
                    if not df_rad.empty:
                        g_val = df_rad.groupby("EPS", dropna=False)["Valor"].sum().reset_index()
                        g_val = g_val.sort_values("Valor", ascending=False).head(25)
                        fig_eps_valrad = px.bar(g_val, x="EPS", y="Valor", title="Valor radicado por EPS (solo Radicadas)",
                                                text="Valor")
                        fig_eps_valrad.update_traces(texttemplate="%{text:.2s}", textposition="outside")
                        fig_eps_valrad.update_layout(xaxis={'categoryorder':'total descending'}, margin=dict(t=60,b=40))
                        st.plotly_chart(fig_eps_valrad, use_container_width=True)
                    else:
                        st.info("Aún no hay facturas Radicadas para mostrar valor por EPS.")

            # ----------------- Por Vigencia -----------------
            st.markdown("## 📆 Por Vigencia")
            if {"Vigencia","NumeroFactura"}.issubset(df_view.columns):
                # Barras: Valor por Vigencia agrupado por estado (usa EstadoCanon)
                fig_vig_val = px.bar(
                    df_view, x="Vigencia", y="Valor", color="EstadoCanon", barmode="group",
                    title="Valor por Vigencia", color_discrete_map=ESTADO_COLORES, text_auto=".2s"
                )
                st.plotly_chart(fig_vig_val, use_container_width=True)

                # Donut: distribución de facturas por Vigencia (cantidad, %)
                g_vig_count = df_view.groupby("Vigencia")["NumeroFactura"].nunique().reset_index(name="Cuentas")
                fig_vig_donut = px.pie(g_vig_count, names="Vigencia", values="Cuentas",
                                       hole=0.4, title="Distribución de Facturas por Vigencia")
                fig_vig_donut.update_traces(textposition="inside", textinfo="percent")
                st.plotly_chart(fig_vig_donut, use_container_width=True)

            # ----------- Descarga Excel del Dashboard -----------
            st.divider()
            xls_bytes = exportar_dashboard_excel(df_view)
            st.download_button(
                "⬇️ Descargar Dashboard a Excel",
                data=xls_bytes,
                file_name="dashboard_radicacion.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )

    # =================== BANDEJAS ===================
    with tab2:
        st.subheader("🗂️ Bandejas por estado")
        if df.empty:
            st.info("No hay datos para mostrar.")
        else:
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

            tabs_estado = st.tabs(ESTADOS)

            for estado, tab in zip(ESTADOS, tabs_estado):
                with tab:
                    sub = filtrar_por_estado(df, estado, eps_sel, vig_sel, q)
                    sub = sub.sort_values(by=["FechaMovimiento","NumeroFactura"], ascending=[False, True])

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
                        st.markdown(f"**Página {current_page} / {total_pages}** &nbsp; &nbsp; (**{len(sub)}** registros)")

                    if prev:
                        st.session_state[pg_key] = max(1, current_page-1); st.rerun()
                    if nextb:
                        st.session_state[pg_key] = min(total_pages, current_page+1); st.rerun()

                    # Selección
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

    # =================== GESTIÓN ===================
    with tab3:
        st.subheader("📝 Gestión")

        df_g = load_data().copy()  # recarga por seguridad

        cols_needed = ["ID","NumeroFactura","Valor","EPS","Vigencia","Estado",
                       "Mes","FechaRadicacion","FechaMovimiento","Observaciones"]
        for c in cols_needed:
            if c not in df_g.columns:
                df_g[c] = pd.NA

        df_g["Valor"] = pd.to_numeric(df_g["Valor"], errors="coerce")
        for c in ["FechaRadicacion","FechaMovimiento"]:
            df_g[c] = pd.to_datetime(df_g[c], errors="coerce")

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
            # ubicar registro por NumeroFactura
            mask = df_g["NumeroFactura"].astype(str).str.strip() == str(numero_activo).strip()
            existe = mask.any()
            idx = df_g[mask].index[0] if existe else None
            fila = df_g.loc[idx] if existe else pd.Series()

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
                    "ID": "",
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
            eps_opciones = sorted([e for e in df_g["EPS"].dropna().astype(str).unique().tolist() if e]) or []
            vigencias = sorted([int(v) for v in pd.to_numeric(df_g["Vigencia"], errors="coerce").dropna().unique().tolist()] + [date.today().year])

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

            # Mostrar FechaMovimiento como texto (no editable)
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
                    eps_val = st.selectbox("EPS", options=[""] + eps_opciones, index=([""]+eps_opciones).index(def_val["EPS"]) if def_val["EPS"] in ([""]+eps_opciones) else 0)
                with c2:
                    vig_set = sorted(set(vigencias))
                    vig_val = st.selectbox("Vigencia", options=vig_set, index=vig_set.index(def_val["Vigencia"]) if def_val["Vigencia"] in vig_set else 0)
                    obs_val = st.text_area("Observaciones", value=def_val["Observaciones"], height=100)

                submitted = st.form_submit_button("💾 Guardar cambios", type="primary")

            if submitted:
                ahora = pd.Timestamp(datetime.now())
                estado_actual = st.session_state.get("estado_val", def_val["Estado"])
                frad_widget = st.session_state.get("frad_val", date.today())
                frad_ts = _to_ts(frad_widget) if estado_actual == "Radicada" else pd.NaT

                # Calcular Mes solo si está vacío y hay FechaRadicacion
                mes_val = def_val.get("Mes", "")
                is_mes_vacio = (mes_val is None) or pd.isna(mes_val) or (str(mes_val).strip() == "")
                if is_mes_vacio and pd.notna(frad_ts):
                    try:
                        mes_calc = MES_NOMBRE[int(frad_ts.month)]
                        mes_val = mes_calc
                    except Exception:
                        mes_val = def_val.get("Mes","")

                new_id = def_val["ID"] or (siguiente_id(df_g) if not existe else def_val["ID"])

                nueva = {
                    "ID": new_id,
                    "NumeroFactura": str(num_val).strip(),
                    "Valor": float(valor_val),
                    "EPS": eps_val.strip(),
                    "Vigencia": int(vig_val) if str(vig_val).isdigit() else vig_val,
                    "Estado": estado_actual,
                    "FechaRadicacion": frad_ts,
                    "Observaciones": obs_val.strip(),
                    "Mes": mes_val
                }

                # FechaMovimiento: actualizar solo si es nuevo registro o cambia el Estado
                estado_anterior = str(fila.get("Estado","")) if existe else ""
                estado_cambio = (str(estado_actual) != estado_anterior) or (not existe)
                nueva["FechaMovimiento"] = (ahora if (estado_cambio or not existe) else fila.get("FechaMovimiento", pd.NaT))

                if existe:
                    for k,v in nueva.items():
                        df_g.at[idx, k] = v
                else:
                    df_g = pd.concat([df_g, pd.DataFrame([nueva])], ignore_index=True)

                try:
                    guardar_inventario(df_g)
                    st.success("✅ Cambios guardados. El formulario fue limpiado.")
                    st.session_state["factura_activa"] = ""
                    for k in ["estado_val","frad_val","buscar_factura_input"]:
                        if k in st.session_state: del st.session_state[k]
                    _set_query_params(tab="gestion")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Error guardando el inventario: {e}")

    # =================== REPORTES ===================
    with tab4:
        st.subheader("📑 Reportes")
        if df_view.empty:
            st.info("No hay datos en el inventario para generar reportes.")
        else:
            total = len(df_view)
            valor_total = float(df_view["Valor"].fillna(0).sum())
            radicadas = int((df_view["EstadoCanon"] == "Radicada").sum())
            avance = round((radicadas / total) * 100, 2) if total else 0.0
            c1, c2, c3 = st.columns(3)
            c1.metric("Número de facturas", f"{total:,}")
            c2.metric("Valor total", f"${valor_total:,.0f}")
            c3.metric("% avance general", f"{avance}%")

            st.markdown("### Gráficos")
            if {"EPS","EstadoCanon"}.issubset(df_view.columns):
                eps_count = df_view.groupby("EPS")["NumeroFactura"].nunique().reset_index(name="Cuentas")
                eps_count = eps_count.sort_values("Cuentas", ascending=False).head(25)
                fig_eps_funnel = px.funnel(eps_count, x="Cuentas", y="EPS", title="Embudo por EPS (Top 25, # de facturas)")
                st.plotly_chart(fig_eps_funnel, use_container_width=True)

            if {"Vigencia","EstadoCanon"}.issubset(df_view.columns):
                vig_counts = df_view.groupby("Vigencia")["NumeroFactura"].nunique().reset_index(name="Cuentas")
                fig_vig_donut = px.pie(vig_counts, names="Vigencia", values="Cuentas",
                                       hole=0.4, title="Participación por Vigencia")
                fig_vig_donut.update_traces(textposition="inside", textinfo="percent+value")
                st.plotly_chart(fig_vig_donut, use_container_width=True)

            # Resúmenes
            st.markdown("### Resúmenes")
            def tabla_resumen(df_, by, nombre):
                g = df_.groupby(by, dropna=False).agg(
                    Facturas=("NumeroFactura","nunique"),
                    Valor=("Valor","sum"),
                    Radicadas=("EstadoCanon", lambda s: (s=="Radicada").sum()),
                    Pendientes=("EstadoCanon", lambda s: (s=="Pendiente").sum()),
                    Auditadas=("EstadoCanon", lambda s: (s=="Auditada").sum()),
                    Subsanadas=("EstadoCanon", lambda s: (s=="Subsanada").sum()),
                ).reset_index()
                g["% Avance"] = (g["Radicadas"] / g["Facturas"]).fillna(0) * 100
                st.subheader(f"Resumen por {nombre}")
                st.dataframe(g, use_container_width=True)
                return g

            t_eps = tabla_resumen(df_view, "EPS", "EPS") if "EPS" in df_view.columns else pd.DataFrame()
            t_vig = tabla_resumen(df_view, "Vigencia", "Vigencia") if "Vigencia" in df_view.columns else pd.DataFrame()

            # Descarga
            st.markdown("### Descarga")
            out_rep = io.BytesIO()
            with pd.ExcelWriter(out_rep, engine="openpyxl") as w:
                pd.DataFrame(
                    {"Métrica": ["# Facturas", "Valor total", "% Avance general"],
                     "Valor": [total, valor_total, avance]}
                ).to_excel(w, index=False, sheet_name="Resumen")
                if not t_eps.empty: t_eps.to_excel(w, index=False, sheet_name="Por_EPS")
                if not t_vig.empty: t_vig.to_excel(w, index=False, sheet_name="Por_Vigencia")
            st.download_button(
                "⬇️ Descargar reportes a Excel",
                data=out_rep.getvalue(),
                file_name="reportes_radicacion.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )

    # =================== AVANCE ===================
    with tab5:
        st.subheader("📈 Avance (Real vs Proyectado — Acumulado)")

        # Proyección mensual (NO acumulada) definida en sistema
        metas_mes = pd.DataFrame({
            "Mes": ["Agosto 2025","Septiembre 2025","Octubre 2025","Noviembre 2025"],
            "Cuentas estimadas": [515, 1489, 1797, 1738],
        })
        metas_mes["Cuentas estimadas acumuladas"] = metas_mes["Cuentas estimadas"].cumsum()
        total_meta = int(metas_mes["Cuentas estimadas"].sum())
        metas_mes["% proyectado acumulado"] = (metas_mes["Cuentas estimadas acumuladas"]/total_meta*100).round(2)

        if df.empty:
            st.info("No hay datos reales para comparar aún.")
        else:
            # Normalizar Mes clave real
            def _etiqueta_mes(row):
                fr = row.get("FechaRadicacion")
                if pd.notna(fr):
                    fr = pd.to_datetime(fr, errors="coerce")
                    if pd.notna(fr):
                        return f"{MES_NOMBRE[int(fr.month)]} {int(fr.year)}"
                m = str(row.get("Mes","")).strip()
                if re.search(r"\b20\d{2}\b", m):
                    return m
                vig = str(row.get("Vigencia","")).strip()
                if m and vig.isdigit():
                    return f"{m} {vig}"
                return m or "Sin Mes"

            df_tmp = df.copy()
            df_tmp["MesClave"] = df_tmp.apply(_etiqueta_mes, axis=1)

            # Solo Radicadas (usando vista canon para clasificación, pero no toca archivo)
            norm = df_tmp["Estado"].astype(str).str.strip().str.lower()
            mapa = {"radicada":"Radicada","radicadas":"Radicada"}
            df_tmp["EstadoCanon"] = norm.map(mapa).fillna(df_tmp["Estado"])

            reales = df_tmp[df_tmp["EstadoCanon"]=="Radicada"].groupby("MesClave")["NumeroFactura"].nunique().reset_index(name="Cuentas reales")

            comp = metas_mes.merge(reales, left_on="Mes", right_on="MesClave", how="left").drop(columns=["MesClave"]).fillna(0)
            comp["Cuentas reales"] = comp["Cuentas reales"].astype(int)
            comp["Cuentas reales acumuladas"] = comp["Cuentas reales"].cumsum()
            comp["% real acumulado"] = (comp["Cuentas reales acumuladas"]/total_meta*100).round(2)
            comp["Diferencia % (Real - Proy)"] = (comp["% real acumulado"] - comp["% proyectado acumulado"]).round(2)

            st.dataframe(comp, use_container_width=True)

            fig = go.Figure()
            fig.add_trace(go.Scatter(x=comp["Mes"], y=comp["% proyectado acumulado"], mode='lines+markers', name='Proyectado'))
            fig.add_trace(go.Scatter(x=comp["Mes"], y=comp["% real acumulado"], mode='lines+markers', name='Real'))
            fig.update_layout(title="Avance acumulado (%) — Real vs Proyectado", yaxis_title="% acumulado", xaxis_title="Mes")
            st.plotly_chart(fig, use_container_width=True)

            total_real = int(comp["Cuentas reales"].sum())
            avance_real_total = (total_real/total_meta*100) if total_meta else 0.0
            k1,k2,k3 = st.columns(3)
            k1.metric("Meta total (cuentas)", f"{int(total_meta):,}")
            k2.metric("Reales acumuladas", f"{total_real:,}")
            k3.metric("Avance total vs meta", f"{avance_real_total:.1f}%")

# ====== BOOT ======
if "autenticado" not in st.session_state:
    login()
elif st.session_state.get("autenticado"):
    main_app()
