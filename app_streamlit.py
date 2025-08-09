# app_streamlit.py
# -*- coding: utf-8 -*-
APP_VERSION = "2025-08-09 04:25"

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
        with pd.ExcelWriter(INVENTARIO_FILE, engine="openpyxl") as w:
            df.to_excel(w, index=False)
    except Exception:
        df.to_csv("inventario_cuentas.csv", index=False, encoding="utf-8-sig")
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
    """Extrae el número del ID con formato CHIA-0001; si no coincide, intenta convertir a int."""
    s = str(id_str).strip()
    m = re.match(r"^CHIA-(\d+)$", s)
    if m:
        try:
            return int(m.group(1))
        except:
            return None
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

# ====== DATA ======
@st.cache_data
def load_data():
    if not os.path.exists(INVENTARIO_FILE):
        cols = ["ID","NumeroFactura","Valor","EPS","Vigencia","Estado",
                "Mes","FechaRadicacion","FechaMovimiento","Observaciones"]
        return pd.DataFrame(columns=cols)
    df = pd.read_excel(INVENTARIO_FILE)

    # Normalizar fechas
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

    # Normalizar estado
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
            df.at[idx, "FechaRadicacion"] = ahora.normalize()
            df.at[idx, "Mes"] = MES_NOMBRE.get(int(ahora.month), "")
        df.at[idx, "FechaMovimiento"] = ahora
    guardar_inventario(df)

# ====== Export helpers (Excel) ======
def exportar_dashboard_excel(df: pd.DataFrame) -> bytes:
    output = io.BytesIO()
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

# ====== APP ======
def main_app():
    st.caption(f"🆔 Versión: {APP_VERSION}")
    st.title("📊 AIPAD • Control de Radicación")
    if "usuario" in st.session_state and "rol" in st.session_state:
        st.markdown(f"👤 Usuario: `{st.session_state['usuario']}`  |  🔐 Rol: `{st.session_state['rol']}`")

    qp = {}
    try:
        qp = dict(st.query_params)
    except Exception:
        qp = st.experimental_get_query_params()

    df = load_data()

    tab_labels = ["📋 Dashboard", "🗂️ Bandejas", "📝 Gestión", "📑 Reportes", "📈 Avance"]
    tab1, tab2, tab3, tab4, tab5 = st.tabs(tab_labels)

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
                fig_estado.update_traces(textposition="inside", textinfo="percent+value")
                st.plotly_chart(fig_estado, use_container_width=True)

            # --- EPS ---
            st.markdown("## 🏥 Por EPS")
            if {"EPS","NumeroFactura"}.issubset(df.columns):
                g = df.groupby("EPS", dropna=False).agg(
                    N_Facturas=("NumeroFactura","count"),
                    Radicadas=("Estado", lambda x: (x=="Radicada").sum())
                ).fillna(0).sort_values("N_Facturas", ascending=False)
                g["% del total"] = (g["N_Facturas"] / g["N_Facturas"].sum() * 100).round(2) if g["N_Facturas"].sum() else 0

                # Un solo gráfico: embudo con cantidad y %
                fig_funnel = px.funnel(g.reset_index().head(25), x="N_Facturas", y="EPS",
                                       title="Cantidad y % por EPS")
                # Mostrar % en etiqueta
                fig_funnel.update_traces(texttemplate="%{x} (%{customdata}%)",
                                         customdata=g.reset_index().head(25)["% del total"])
                st.plotly_chart(fig_funnel, use_container_width=True)

            # --- Mes ---
            st.markdown("## 📅 Por Mes")
            if {"Mes","NumeroFactura"}.issubset(df.columns):
                g_mes_full = df.groupby(["Mes","Estado"], dropna=False).agg(Valor=("Valor","sum")).reset_index()
                fig_mes_val = px.area(
                    g_mes_full, x="Mes", y="Valor", color="Estado",
                    title="Estados por Mes", line_group="Estado",
                    color_discrete_map=ESTADO_COLORES
                )
                st.plotly_chart(fig_mes_val, use_container_width=True)

                g_mes_cnt = df.groupby("Mes", dropna=False)["NumeroFactura"].count().reset_index(name="Cantidad")
                fig_mes_cnt = px.bar(g_mes_cnt, x="Mes", y="Cantidad", title="Cantidad de facturas por Mes", text="Cantidad")
                st.plotly_chart(fig_mes_cnt, use_container_width=True)

            # --- Vigencia ---
            st.markdown("## 📆 Por Vigencia")
            if {"Vigencia","NumeroFactura"}.issubset(df.columns):
                g_vig_val = df.groupby(["Vigencia","Estado"], dropna=False).agg(Valor=("Valor","sum")).reset_index()
                fig_vig_val = px.bar(
                    g_vig_val, x="Vigencia", y="Valor", color="Estado", barmode="group",
                    title="Valor por Vigencia", color_discrete_map=ESTADO_COLORES, text_auto=".2s"
                )
                st.plotly_chart(fig_vig_val, use_container_width=True)

                g_vig_cnt = df.groupby("Vigencia", dropna=False)["NumeroFactura"].count().reset_index(name="Cantidad")
                fig_vig_cnt = px.bar(g_vig_cnt, x="Vigencia", y="Cantidad", title="Cantidad por Vigencia", text="Cantidad")
                st.plotly_chart(fig_vig_cnt, use_container_width=True)

            # --- Descarga Excel Dashboard ---
            st.divider()
            xls_bytes = exportar_dashboard_excel(df)
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

    # ---- GESTIÓN ----
    with tab3:
        st.subheader("📝 Gestión")

        df = load_data().copy()

        cols_needed = ["ID","NumeroFactura","Valor","EPS","Vigencia","Estado",
                    "Mes","FechaRadicacion","FechaMovimiento","Observaciones"]
        for c in cols_needed:
            if c not in df.columns:
                df[c] = pd.NA

        df["Valor"] = pd.to_numeric(df["Valor"], errors="coerce")
        for c in ["FechaRadicacion","FechaMovimiento"]:
            df[c] = pd.to_datetime(df[c], errors="coerce")

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
            eps_opciones = sorted([e for e in df["EPS"].dropna().astype(str).unique().tolist() if e]) or []
            vigencias = sorted([int(v) for v in pd.to_numeric(df["Vigencia"], errors="coerce").dropna().unique().tolist()] + [date.today().year])

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

                submit = st.form_submit_button("💾 Guardar cambios", type="primary")

            if submit:
                ahora = pd.Timestamp(datetime.now())
                estado_actual = st.session_state.get("estado_val", def_val["Estado"])
                frad_widget = st.session_state.get("frad_val", date.today())
                frad_ts = _to_ts(frad_widget) if estado_actual == "Radicada" else pd.NaT
                mes_calc = MES_NOMBRE.get(int(frad_ts.month), "") if pd.notna(frad_ts) else def_val["Mes"]

                new_id = def_val["ID"]
                if not new_id:
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

                estado_anterior = str(fila.get("Estado","")) if existe else ""
                estado_cambio = (str(estado_actual) != estado_anterior) or (not existe)

                if existe:
                    nueva["FechaMovimiento"] = (ahora if estado_cambio else fila.get("FechaMovimiento", pd.NaT))
                else:
                    nueva["FechaMovimiento"] = ahora

                if existe:
                    for k, v in nueva.items():
                        df.at[idx, k] = v
                else:
                    df = pd.concat([df, pd.DataFrame([nueva])], ignore_index=True)

                try:
                    guardar_inventario(df)
                    st.success("✅ Cambios guardados. El formulario fue limpiado.")
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
            total = len(df)
            valor_total = float(df["Valor"].fillna(0).sum())
            radicadas = int((df["Estado"] == "Radicada").sum())
            avance = round((radicadas / total) * 100, 2) if total else 0.0
            c1, c2, c3 = st.columns(3)
            c1.metric("Número de facturas", f"{total:,}")
            c2.metric("Valor total", f"${valor_total:,.0f}")
            c3.metric("% avance general", f"{avance}%")

            if "Mes" not in df.columns:
                if "FechaRadicacion" in df.columns:
                    df["Mes"] = pd.to_datetime(df["FechaRadicacion"], errors="coerce").dt.to_period("M").astype(str)
                else:
                    df["Mes"] = "Sin Mes"

            st.markdown("### Gráficos")
            if {"EPS","Estado"}.issubset(df.columns):
                eps_count = df.groupby("EPS")["Estado"].count().reset_index(name="Facturas")
                eps_count["% del total"] = (eps_count["Facturas"] / eps_count["Facturas"].sum() * 100).round(2) if eps_count["Facturas"].sum() else 0
                eps_count = eps_count.sort_values("Facturas", ascending=False).head(25)
                fig_eps_funnel = px.funnel(eps_count, x="Facturas", y="EPS", title="Cantidad y % por EPS")
                fig_eps_funnel.update_traces(texttemplate="%{x} (%{customdata}%)",
                                             customdata=eps_count["% del total"])
                st.plotly_chart(fig_eps_funnel, use_container_width=True)

            if {"Vigencia","Estado"}.issubset(df.columns):
                vig_estado = df.groupby(["Vigencia", "Estado"]).size().reset_index(name="Facturas")
                fig_vig_donut = px.pie(vig_estado.groupby("Vigencia")["Facturas"].sum().reset_index(),
                                       names="Vigencia", values="Facturas",
                                       hole=0.4, title="Participación por Vigencia")
                fig_vig_donut.update_traces(textposition="inside", textinfo="percent+value")
                st.plotly_chart(fig_vig_donut, use_container_width=True)

            if {"Mes","Estado"}.issubset(df.columns):
                mes_estado = df.groupby(["Mes", "Estado"]).size().reset_index(name="Facturas")
                mes_sum = mes_estado.groupby("Mes")["Facturas"].sum().reset_index()
                fig_mes_donut = px.pie(mes_sum, names="Mes", values="Facturas",
                                       hole=0.4, title="Participación por Mes")
                fig_mes_donut.update_traces(textposition="inside", textinfo="percent+value")
                st.plotly_chart(fig_mes_donut, use_container_width=True)

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

        # Proyección mensual (NO acumulada). A partir de esto se calcula acumulado y %.
        proy_base = pd.DataFrame({
            "Mes": ["Agosto 2025", "Septiembre 2025", "Octubre 2025", "Noviembre 2025"],
            "Cuentas estimadas": [515, 1489, 1797, 1738],
        })
        proy = proy_base.copy()
        proy["Cuentas estimadas acumuladas"] = proy["Cuentas estimadas"].cumsum()
        total_meta = int(proy["Cuentas estimadas"].sum())
        proy["% proyectado acumulado"] = (proy["Cuentas estimadas acumuladas"] / total_meta * 100).round(2) if total_meta else 0.0

        if df.empty:
            st.info("No hay datos reales para comparar aún.")
        else:
            # === Normalizar llave de mes para los datos REALES ===
            import re as _re
            def _etiqueta_mes(row):
                fr = row.get("FechaRadicacion")
                if pd.notna(fr):
                    fr = pd.to_datetime(fr, errors="coerce")
                    if pd.notna(fr):
                        return f"{MES_NOMBRE[int(fr.month)]} {int(fr.year)}"
                m = str(row.get("Mes", "")).strip()
                if _re.search(r"\\b20\\d{2}\\b", m):
                    return m
                vig = str(row.get("Vigencia", "")).strip()
                if m and vig.isdigit():
                    return f"{m} {vig}"
                return m or "Sin Mes"

            # Solo RADICADAS
            df_rad = df[df["Estado"] == "Radicada"].copy()
            if df_rad.empty:
                st.info("Aún no hay cuentas 'Radicada' para calcular avance real.")
                reales = pd.DataFrame(columns=["MesClave","Cuentas reales"])
            else:
                df_rad["MesClave"] = df_rad.apply(_etiqueta_mes, axis=1)
                reales = df_rad.groupby("MesClave")["NumeroFactura"].nunique().reset_index(name="Cuentas reales")

            # Unir proyección con real
            comp = proy.merge(reales, left_on="Mes", right_on="MesClave", how="left").drop(columns=["MesClave"], errors="ignore").fillna(0)
            comp["Cuentas reales"] = comp["Cuentas reales"].astype(int)
            comp["Cuentas reales acumuladas"] = comp["Cuentas reales"].cumsum()
            comp["% real acumulado"] = (comp["Cuentas reales acumuladas"] / total_meta * 100).round(2) if total_meta else 0.0
            comp["Diferencia % (Real - Proy)"] = (comp["% real acumulado"] - comp["% proyectado acumulado"]).round(2)

            st.dataframe(comp, use_container_width=True)

            # Gráfico comparación
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=comp["Mes"], y=comp["% proyectado acumulado"],
                                     mode='lines+markers', name='Proyectado'))
            fig.add_trace(go.Scatter(x=comp["Mes"], y=comp["% real acumulado"],
                                     mode='lines+markers', name='Real'))
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
