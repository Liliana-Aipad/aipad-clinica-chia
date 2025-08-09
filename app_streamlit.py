# app_streamlit.py
# -*- coding: utf-8 -*-
APP_VERSION = "2025-08-09 04:40 (no-touch inventory on load)"

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

# Colores por estado (solo para visual)
ESTADO_COLORES = {
    "Radicada": "green",
    "Pendiente": "red",
    "Auditada":  "orange",
    "Subsanada": "blue",
}

# Estados conocidos (NO se usan para reescribir datos, solo para ordenar/colorear)
ESTADOS_CONOCIDOS = ["Pendiente","Auditada","Subsanada","Radicada"]

MES_NOMBRE = {
    1:"Enero",2:"Febrero",3:"Marzo",4:"Abril",5:"Mayo",6:"Junio",
    7:"Julio",8:"Agosto",9:"Septiembre",10:"Octubre",11:"Noviembre",12:"Diciembre"
}

# ====== Helpers ======
def _to_ts(d):
    """Convierte date/datetime/str a Timestamp o NaT (sin escribir a archivo)."""
    return pd.to_datetime(d, errors="coerce") if d not in (None, "", pd.NaT) else pd.NaT

def _estado_norm(s):
    """Normaliza SOLO PARA VISUALIZAR/FILTRAR. Nunca se escribe al inventario."""
    if pd.isna(s): return "Desconocido"
    t = str(s).strip()
    return t

def _build_estado_color_map(unique_estados):
    cmap = ESTADO_COLORES.copy()
    # Estados no mapeados: asignar color por defecto
    for e in unique_estados:
        if e not in cmap:
            cmap[e] = "#777777"
    return cmap

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

# ====== DATA (solo lectura) ======
@st.cache_data
def load_data():
    """Carga el inventario SIN modificarlo ni normalizarlo destructivamente."""
    if not os.path.exists(INVENTARIO_FILE):
        # Estructura vacía si no existe
        cols = ["ID","NumeroFactura","Valor","EPS","Vigencia","Estado",
                "Mes","FechaRadicacion","FechaMovimiento","Observaciones"]
        return pd.DataFrame(columns=cols)

    df = pd.read_excel(INVENTARIO_FILE)
    # Convertir fechas a datetime SOLO en una copia en memoria (no se guarda)
    for col in ["FechaRadicacion", "FechaMovimiento"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    # No forzamos tipos ni rellenamos valores en el archivo; solo trabajamos con df en memoria
    return df

# ====== Guardado explícito (solo cuando el usuario lo pide) ======
def guardar_inventario(df: pd.DataFrame):
    """Guarda EXPLÍCITAMENTE al Excel. Esta es la ÚNICA función que escribe al archivo."""
    with pd.ExcelWriter(INVENTARIO_FILE, engine="openpyxl") as w:
        df.to_excel(w, index=False)
    st.cache_data.clear()

def registro_por_factura(df: pd.DataFrame, numero_factura: str):
    """Devuelve (existe, idx, fila_series) según NumeroFactura (sin modificar)."""
    if "NumeroFactura" not in df.columns:
        return False, None, None
    mask = df["NumeroFactura"].astype(str).str.strip() == str(numero_factura).strip()
    if mask.any():
        idx = df[mask].index[0]
        return True, idx, df.loc[idx]
    return False, None, None

def siguiente_id(df: pd.DataFrame):
    """Genera siguiente ID con patrón CHIA-#### sin alterar datos existentes."""
    def _id_num(id_str):
        s = str(id_str).strip()
        m = re.match(r"^CHIA-(\d+)$", s)
        if m:
            try: return int(m.group(1))
            except: return None
        try: return int(float(s))
        except: return None

    if "ID" not in df.columns or df["ID"].dropna().empty:
        return "CHIA-0001"
    nums = df["ID"].apply(_id_num).dropna()
    n = int(nums.max()) + 1 if not nums.empty else 1
    return f"CHIA-{n:04d}"

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

# ====== Filtros / Bandejas (sin tocar archivo) ======
def filtrar_por_estado(df: pd.DataFrame, estado: str, eps: str, vigencia, q: str):
    # Usar EstadoNorm para comparar
    dfv = df.copy()
    dfv["EstadoNorm"] = dfv["Estado"].apply(_estado_norm)
    sub = dfv[dfv["EstadoNorm"] == estado].copy()
    if eps and eps != "Todos":
        sub = sub[sub["EPS"].astype(str) == eps]
    if vigencia and vigencia != "Todos":
        sub = sub[sub["Vigencia"].astype(str) == str(vigencia)]
    if q:
        qn = str(q).strip().lower()
        sub = sub[sub["NumeroFactura"].astype(str).str.lower().str.contains(qn)]
    return sub

def aplicar_movimiento_masivo(df: pd.DataFrame, indices, nuevo_estado: str):
    """Esta acción SÍ modifica archivo porque es un comando explícito del usuario."""
    ahora = pd.Timestamp(datetime.now())
    for idx in indices:
        if "Estado" in df.columns:
            df.at[idx, "Estado"] = nuevo_estado
        # Reglas de fechas derivadas (opcionales)
        if nuevo_estado == "Radicada" and "FechaRadicacion" in df.columns and pd.isna(df.at[idx, "FechaRadicacion"]):
            df.at[idx, "FechaRadicacion"] = ahora.normalize()
            if "Mes" in df.columns:
                df.at[idx, "Mes"] = f"{MES_NOMBRE.get(ahora.month,'')}"  # solo nombre, no pisa si no existe
        if "FechaMovimiento" in df.columns:
            df.at[idx, "FechaMovimiento"] = ahora
    guardar_inventario(df)

# ====== Export helpers (Excel) ======
def exportar_dashboard_excel(df: pd.DataFrame) -> bytes:
    output = io.BytesIO()
    dfv = df.copy()
    dfv["EstadoNorm"] = dfv["Estado"].apply(_estado_norm)

    total = len(dfv)
    radicadas = int((dfv["EstadoNorm"] == "Radicada").sum())
    total_valor = float(pd.to_numeric(dfv.get("Valor", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
    avance = round((radicadas / total) * 100, 2) if total else 0.0

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame({
            "Métrica": ["Total facturas", "Valor total", "% Avance (radicadas)"],
            "Valor": [total, total_valor, avance]
        }).to_excel(writer, index=False, sheet_name="Resumen")

        if {"EPS","NumeroFactura"}.issubset(dfv.columns):
            g_eps = dfv.groupby("EPS", dropna=False).agg(
                N_Facturas=("NumeroFactura","count"),
                Valor_Total=("Valor", lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum()),
                Radicadas=("EstadoNorm", lambda x: (x=="Radicada").sum())
            ).fillna(0)
            g_eps["% Avance"] = (g_eps["Radicadas"] / g_eps["N_Facturas"].replace(0, float("nan")) * 100).fillna(0).round(2)
            g_eps.to_excel(writer, sheet_name="Por_EPS")

        if {"Mes","NumeroFactura"}.issubset(dfv.columns):
            g_mes = dfv.groupby("Mes", dropna=False).agg(
                N_Facturas=("NumeroFactura","count"),
                Valor_Total=("Valor", lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum()),
                Radicadas=("EstadoNorm", lambda x: (x=="Radicada").sum())
            ).fillna(0)
            g_mes["% Avance"] = (g_mes["Radicadas"] / g_mes["N_Facturas"].replace(0, float("nan")) * 100).fillna(0).round(2)
            g_mes.to_excel(writer, sheet_name="Por_Mes")

        if {"Vigencia","NumeroFactura"}.issubset(dfv.columns):
            g_vig = dfv.groupby("Vigencia", dropna=False).agg(
                N_Facturas=("NumeroFactura","count"),
                Valor_Total=("Valor", lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum()),
                Radicadas=("EstadoNorm", lambda x: (x=="Radicada").sum())
            ).fillna(0)
            g_vig["% Avance"] = (g_vig["Radicadas"] / g_vig["N_Facturas"].replace(0, float("nan")) * 100).fillna(0).round(2)
            g_vig.to_excel(writer, sheet_name="Por_Vigencia")
    return output.getvalue()

# ====== APP ======
def main_app():
    st.caption(f"🆔 Versión: {APP_VERSION}")
    st.title("📊 AIPAD • Control de Radicación (modo seguro: no toca inventario al cargar)")
    if "usuario" in st.session_state and "rol" in st.session_state:
        st.markdown(f"👤 Usuario: `{st.session_state['usuario']}`  |  🔐 Rol: `{st.session_state['rol']}`")

    qp = {}
    try:
        qp = dict(st.query_params)
    except Exception:
        qp = st.experimental_get_query_params()

    df = load_data()
    dfv = df.copy()  # vista en memoria
    dfv["EstadoNorm"] = dfv["Estado"].apply(_estado_norm)
    color_map = _build_estado_color_map(sorted(dfv["EstadoNorm"].dropna().unique()))

    tab_labels = ["📋 Dashboard", "🗂️ Bandejas", "📝 Gestión", "📑 Reportes", "📈 Avance"]
    tab1, tab2, tab3, tab4, tab5 = st.tabs(tab_labels)

    # ---- DASHBOARD ----
    with tab1:
        st.subheader("📈 Avance general del proyecto")
        if dfv.empty:
            st.info("No hay datos en el inventario.")
        else:
            total = len(dfv)
            radicadas = int((dfv["EstadoNorm"] == "Radicada").sum())
            total_valor = float(pd.to_numeric(dfv.get("Valor", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
            avance = round((radicadas / total) * 100, 2) if total else 0.0

            c1, c2, c3 = st.columns(3)
            c1.metric("📦 Total facturas", total)
            c2.metric("💰 Valor total", f"${total_valor:,.0f}")
            c3.metric("📊 Avance (radicadas)", f"{avance}%")

            # Distribución por Estado (donut)
            if "EstadoNorm" in dfv.columns:
                fig_estado = px.pie(
                    dfv, names="EstadoNorm", hole=0.4, title="Distribución por Estado",
                    color="EstadoNorm", color_discrete_map=color_map
                )
                fig_estado.update_traces(textposition="inside", textinfo="percent+value")
                st.plotly_chart(fig_estado, use_container_width=True)

            # --- EPS ---
            st.markdown("## 🏥 Por EPS")
            if {"EPS","NumeroFactura"}.issubset(dfv.columns):
                g = dfv.groupby("EPS", dropna=False).agg(
                    N_Facturas=("NumeroFactura","count"),
                    Valor_Total=("Valor", lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum()),
                    Radicadas=("EstadoNorm", lambda x: (x=="Radicada").sum())
                ).fillna(0).sort_values("N_Facturas", ascending=False)

                # Embudo único: cantidad y % por EPS
                top = g.reset_index().head(25)
                top["Porcentaje"] = (top["N_Facturas"] / top["N_Facturas"].sum() * 100).round(2) if top["N_Facturas"].sum() else 0
                fig_funnel = px.funnel(top, x="N_Facturas", y="EPS", title="Cantidad y % por EPS")
                fig_funnel.update_traces(text=top["Porcentaje"].astype(str) + "%", textposition="inside")
                st.plotly_chart(fig_funnel, use_container_width=True)

                # NUEVO: columnas Valor radicado por EPS (solo Radicadas)
                df_rad = dfv[dfv["EstadoNorm"]=="Radicada"].copy()
                if {"EPS","Valor"}.issubset(df_rad.columns):
                    g_val_rad = df_rad.groupby("EPS", dropna=False)["Valor"].apply(lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum()).reset_index(name="ValorRadicado")
                    g_val_rad = g_val_rad.sort_values("ValorRadicado", ascending=False)
                    fig_val_rad = px.bar(g_val_rad, x="EPS", y="ValorRadicado",
                                         title="Valor radicado por EPS (solo Radicadas)", text_auto=".2s")
                    fig_val_rad.update_layout(xaxis={'categoryorder':'total descending'})
                    st.plotly_chart(fig_val_rad, use_container_width=True)

            # --- Mes ---
            st.markdown("## 📅 Por Mes")
            if {"Mes","NumeroFactura"}.issubset(dfv.columns):
                g = dfv.groupby("Mes", dropna=False).agg(
                    N_Facturas=("NumeroFactura","count"),
                    Valor_Total=("Valor", lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum()),
                    Radicadas=("EstadoNorm", lambda x: (x=="Radicada").sum())
                ).fillna(0)
                g["% Avance"] = (g["Radicadas"].astype(float)/g["N_Facturas"].replace(0, float("nan"))*100).fillna(0).round(2)

                c1, c2 = st.columns(2)
                with c1:
                    fig_mes_val = px.area(
                        dfv, x="Mes", y="Valor", color="EstadoNorm",
                        title="Estados por Mes", line_group="EstadoNorm",
                        color_discrete_map=color_map
                    )
                    st.plotly_chart(fig_mes_val, use_container_width=True)
                with c2:
                    fig_mes_cnt = px.bar(
                        g.reset_index(), x="Mes", y="N_Facturas", title="Cantidad de facturas por Mes",
                        text="N_Facturas"
                    )
                    st.plotly_chart(fig_mes_cnt, use_container_width=True)

            # --- Vigencia ---
            st.markdown("## 📆 Por Vigencia")
            if {"Vigencia","NumeroFactura"}.issubset(dfv.columns):
                g = dfv.groupby("Vigencia", dropna=False).agg(
                    N_Facturas=("NumeroFactura","count"),
                    Valor_Total=("Valor", lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum()),
                    Radicadas=("EstadoNorm", lambda x: (x=="Radicada").sum())
                ).fillna(0)
                g["% Avance"] = (g["Radicadas"].astype(float)/g["N_Facturas"].replace(0, float("nan"))*100).fillna(0).round(2)

                c1, c2 = st.columns(2)
                with c1:
                    fig_vig_val = px.bar(
                        dfv, x="Vigencia", y="Valor", color="EstadoNorm", barmode="group",
                        title="Valor por Vigencia", color_discrete_map=color_map, text_auto=".2s"
                    )
                    st.plotly_chart(fig_vig_val, use_container_width=True)
                with c2:
                    fig_vig_cnt = px.bar(
                        g.reset_index(), x="Vigencia", y="N_Facturas", title="Cantidad por Vigencia",
                        text="N_Facturas"
                    )
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

    # ---- BANDEJAS (usa EstadoNorm para visualizar, no escribe) ----
    with tab2:
        st.subheader("🗂️ Bandejas por estado")
        if dfv.empty:
            st.info("No hay datos para mostrar.")
        else:
            estados_opts = sorted(dfv["EstadoNorm"].dropna().unique().tolist(), key=lambda x: (x not in ESTADOS_CONOCIDOS, x))
            fc1, fc2, fc3, fc4 = st.columns([1.2,1,1,1])
            with fc1:
                q = st.text_input("🔎 Buscar factura (contiene)", key="bandeja_q")
            with fc2:
                eps_opts = ["Todos"] + sorted([e for e in dfv["EPS"].dropna().astype(str).unique().tolist() if e])
                eps_sel = st.selectbox("EPS", eps_opts, index=0, key="bandeja_eps")
            with fc3:
                vig_opts = ["Todos"] + sorted([str(int(v)) for v in pd.to_numeric(dfv.get("Vigencia", pd.Series(dtype=float)), errors="coerce").dropna().unique().tolist()])
                vig_sel = st.selectbox("Vigencia", vig_opts, index=0, key="bandeja_vig")
            with fc4:
                per_page = st.selectbox("Filas por página", [50, 100, 200], index=1, key="bandeja_pp")

            tabs_estado = st.tabs(estados_opts)

            def paginar(df_, page, per_page_):
                total = len(df_)
                total_pages = max((total - 1) // per_page_ + 1, 1)
                page = max(1, min(page, total_pages))
                start = (page - 1) * per_page_
                end = start + per_page_
                return df_.iloc[start:end], total_pages, page

            for estado, tab in zip(estados_opts, tabs_estado):
                with tab:
                    sub = filtrar_por_estado(df, estado, eps_sel, vig_sel, q)
                    sub = sub.sort_values(by=["FechaMovimiento","NumeroFactura"], ascending=[False, True], na_position="last")

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

                    st.divider()
                    sel_all_key = f"sel_all_{estado}_{current_page}"
                    sel_all = st.checkbox("Seleccionar todo (esta página)", key=sel_all_key, value=False)

                    cols_mostrar = [c for c in ["ID","NumeroFactura","EPS","Vigencia","Valor","FechaRadicacion","FechaMovimiento","Observaciones"] if c in sub_page.columns]
                    view = sub_page[cols_mostrar].copy()
                    view.insert(0, "Seleccionar", sel_all)
                    view.insert(1, "__idx", sub_page.index)

                    edited = st.data_editor(
                        view,
                        hide_index=True,
                        use_container_width=True,
                        num_rows="fixed",
                        column_config={
                            "Seleccionar": st.column_config.CheckboxColumn("Seleccionar", help="Marca las filas a mover", default=False),
                            "__idx": st.column_config.Column("", width="small", disabled=True),
                        },
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
                        nuevo_estado = st.selectbox("Mover seleccionadas a:", ESTADOS_CONOCIDOS, key=f"move_to_{estado}")
                    with c2:
                        mover = st.button("Aplicar movimiento", type="primary", key=f"aplicar_{estado}", disabled=(len(seleccionados)==0))

                    if mover:
                        df_editable = load_data().copy()  # recargar para escribir sobre el archivo real
                        aplicar_movimiento_masivo(df_editable, seleccionados, nuevo_estado)
                        st.success(f"Se movieron {len(seleccionados)} facturas a {nuevo_estado}")
                        _set_query_params(tab="🗂️ Bandejas")
                        st.rerun()

    # ---- GESTIÓN (solo guarda al presionar 'Guardar cambios') ----
    with tab3:
        st.subheader("📝 Gestión")
        df_edit = load_data().copy()

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
            existe, idx, fila = registro_por_factura(df_edit, numero_activo)
            st.caption(f"Factura seleccionada: **{numero_activo}** {'(existente)' if existe else '(nueva)'}")

            # Valores por defecto leídos del archivo (no se guardan hasta confirmar)
            def_val = {}
            if existe:
                for c in ["ID","NumeroFactura","Valor","EPS","Vigencia","Estado",
                          "FechaRadicacion","FechaMovimiento","Observaciones","Mes"]:
                    def_val[c] = fila.get(c, pd.NA)
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

            estados_opciones = sorted(set(ESTADOS_CONOCIDOS + [str(x) for x in df_edit.get("Estado", pd.Series([], dtype=str)).dropna().unique().tolist()]))
            eps_opciones = sorted([e for e in df_edit.get("EPS", pd.Series([], dtype=str)).dropna().astype(str).unique().tolist() if e])
            vigencias = sorted([int(v) for v in pd.to_numeric(df_edit.get("Vigencia", pd.Series(dtype=float)), errors="coerce").dropna().unique().tolist()] + [date.today().year])

            ctop1, ctop2, ctop3 = st.columns(3)
            with ctop1:
                st.text_input("ID (automático)", value=str(def_val.get("ID") or ""), disabled=True)
            with ctop2:
                est_val = st.selectbox("Estado", options=estados_opciones,
                                       index=estados_opciones.index(str(def_val.get("Estado") or "Pendiente")) if str(def_val.get("Estado") or "Pendiente") in estados_opciones else 0,
                                       key="estado_val")
            with ctop3:
                frad_disabled = (est_val != "Radicada")
                frad_default = def_val.get("FechaRadicacion")
                frad_value = frad_default.date() if isinstance(frad_default, pd.Timestamp) and pd.notna(frad_default) else date.today()
                frad_val = st.date_input("Fecha de Radicación", value=frad_value, disabled=frad_disabled, key="frad_val")

            st.text_input("Fecha de Movimiento (automática)",
                          value=str(def_val.get("FechaMovimiento") or ""), disabled=True)

            with st.form("form_factura", clear_on_submit=False):
                c1, c2 = st.columns(2)
                with c1:
                    num_val = st.text_input("Número de factura", value=str(def_val.get("NumeroFactura") or ""))
                    valor_def = def_val.get("Valor")
                    try: valor_def = float(valor_def) if pd.notna(valor_def) else 0.0
                    except: valor_def = 0.0
                    valor_val = st.number_input("Valor", min_value=0.0, step=1000.0, value=valor_def)
                    eps_val = st.selectbox("EPS", options=[""] + eps_opciones,
                                           index=([""]+eps_opciones).index(str(def_val.get("EPS") or "")) if str(def_val.get("EPS") or "") in ([""]+eps_opciones) else 0)
                with c2:
                    vig_set = sorted(set(vigencias))
                    vig_default = def_val.get("Vigencia")
                    if pd.isna(vig_default): vig_default = date.today().year
                    vig_val = st.selectbox("Vigencia", options=vig_set, index=vig_set.index(int(vig_default)) if int(vig_default) in vig_set else 0)
                    obs_val = st.text_area("Observaciones", value=str(def_val.get("Observaciones") or ""), height=100)

                submit = st.form_submit_button("💾 Guardar cambios", type="primary")

            if submit:
                ahora = pd.Timestamp(datetime.now())
                estado_actual = st.session_state.get("estado_val", def_val.get("Estado") or "Pendiente")
                frad_widget = st.session_state.get("frad_val", date.today())
                frad_ts = _to_ts(frad_widget) if estado_actual == "Radicada" else def_val.get("FechaRadicacion")

                # Mes: si tienes lógica propia, no la pisamos. Solo derivamos si no hay.
                mes_val = def_val.get("Mes")
                if (mes_val in (None, "", pd.NA)) and pd.notna(frad_ts):
                    mes_val = MES_NOMBRE.get(int(frad_ts.month), "")

                new_id = def_val.get("ID") or ""
                if not new_id:
                    new_id = siguiente_id(df_edit) if not existe else def_val.get("ID")

                nueva = {
                    "ID": new_id,
                    "NumeroFactura": str(num_val).strip(),
                    "Valor": float(valor_val),
                    "EPS": (eps_val or "").strip(),
                    "Vigencia": int(vig_val) if str(vig_val).isdigit() else vig_val,
                    "Estado": estado_actual,
                    "FechaRadicacion": frad_ts,
                    "Observaciones": (obs_val or "").strip(),
                    "Mes": mes_val
                }

                # FechaMovimiento solo si cambia estado o es nueva
                estado_anterior = str(def_val.get("Estado") or "")
                estado_cambio = (str(estado_actual) != estado_anterior) or (not existe)
                nueva["FechaMovimiento"] = (pd.Timestamp(datetime.now()) if estado_cambio else def_val.get("FechaMovimiento"))

                if existe:
                    for k, v in nueva.items():
                        df_edit.at[idx, k] = v
                else:
                    df_edit = pd.concat([df_edit, pd.DataFrame([nueva])], ignore_index=True)

                try:
                    guardar_inventario(df_edit)  # Único punto donde se escribe al archivo
                    st.success("✅ Cambios guardados.")
                    st.session_state["factura_activa"] = ""
                    for k in ["estado_val", "frad_val", "buscar_factura_input"]:
                        if k in st.session_state: del st.session_state[k]
                    _set_query_params(tab="📝 Gestión")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Error guardando el inventario: {e}")

    # ---- REPORTES ----
    with tab4:
        st.subheader("📑 Reportes")
        if dfv.empty:
            st.info("No hay datos en el inventario para generar reportes.")
        else:
            total = len(dfv)
            valor_total = float(pd.to_numeric(dfv.get("Valor", pd.Series(dtype=float)), errors="coerce").fillna(0).sum())
            radicadas = int((dfv["EstadoNorm"] == "Radicada").sum())
            avance = round((radicadas / total) * 100, 2) if total else 0.0
            c1, c2, c3 = st.columns(3)
            c1.metric("Número de facturas", f"{total:,}")
            c2.metric("Valor total", f"${valor_total:,.0f}")
            c3.metric("% avance general", f"{avance}%")

            if "Mes" not in dfv.columns:
                st.info("No hay columna 'Mes' en el inventario; se omiten algunos gráficos.")
            else:
                st.markdown("### Gráficos")
                if {"EPS","EstadoNorm"}.issubset(dfv.columns):
                    eps_count = dfv.groupby("EPS")["EstadoNorm"].count().reset_index(name="Facturas")
                    fig_eps_funnel = px.funnel(eps_count.sort_values("Facturas", ascending=False).head(25),
                                               x="Facturas", y="EPS", title="Embudo por EPS (Top 25, # de facturas)")
                    st.plotly_chart(fig_eps_funnel, use_container_width=True)

                if {"Vigencia","EstadoNorm"}.issubset(dfv.columns):
                    vig_estado = dfv.groupby(["Vigencia", "EstadoNorm"]).size().reset_index(name="Facturas")
                    fig_vig_donut = px.pie(vig_estado.groupby("Vigencia")["Facturas"].sum().reset_index(),
                                           names="Vigencia", values="Facturas",
                                           hole=0.4, title="Participación por Vigencia")
                    fig_vig_donut.update_traces(textposition="inside", textinfo="percent+value")
                    st.plotly_chart(fig_vig_donut, use_container_width=True)

                if {"Mes","EstadoNorm"}.issubset(dfv.columns):
                    mes_estado = dfv.groupby(["Mes", "EstadoNorm"]).size().reset_index(name="Facturas")
                    mes_sum = mes_estado.groupby("Mes")["Facturas"].sum().reset_index()
                    fig_mes_donut = px.pie(mes_sum, names="Mes", values="Facturas",
                                           hole=0.4, title="Participación por Mes")
                    fig_mes_donut.update_traces(textposition="inside", textinfo="percent+value")
                    st.plotly_chart(fig_mes_donut, use_container_width=True)

            st.markdown("### Resúmenes")
            def tabla_resumen(df_, by, nombre):
                g = df_.groupby(by, dropna=False).agg(
                    Facturas=("EstadoNorm", "count"),
                    Valor=("Valor", lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum()),
                    Radicadas=("EstadoNorm", lambda s: (s == "Radicada").sum()),
                    Pendientes=("EstadoNorm", lambda s: (s == "Pendiente").sum()),
                    Auditadas=("EstadoNorm", lambda s: (s == "Auditada").sum()),
                    Subsanadas=("EstadoNorm", lambda s: (s == "Subsanada").sum()),
                ).reset_index()
                g["% Avance"] = (g["Radicadas"] / g["Facturas"]).fillna(0) * 100
                st.subheader(f"Resumen por {nombre}")
                st.dataframe(g, use_container_width=True)
                return g

            t_eps = tabla_resumen(dfv, "EPS", "EPS") if "EPS" in dfv.columns else pd.DataFrame()
            t_vig = tabla_resumen(dfv, "Vigencia", "Vigencia") if "Vigencia" in dfv.columns else pd.DataFrame()
            t_mes = tabla_resumen(dfv, "Mes", "Mes") if "Mes" in dfv.columns else pd.DataFrame()

            st.markdown("### Descarga")
            xls_bytes_rep = exportar_dashboard_excel(df)  # reutilizo export que ya incluye resúmenes
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

        # Proyección mensual NO acumulada (según indicación), luego calculamos acumulado:
        base = pd.DataFrame({
            "Mes": ["Agosto 2025", "Septiembre 2025", "Octubre 2025", "Noviembre 2025"],
            "Cuentas estimadas": [515, 1489, 1797, 1738],
        })
        base["Cuentas estimadas acumuladas"] = base["Cuentas estimadas"].cumsum()
        meta_total = int(base["Cuentas estimadas"].sum())
        base["% proyectado acumulado"] = (base["Cuentas estimadas acumuladas"] / meta_total * 100).round(2) if meta_total else 0.0

        if dfv.empty:
            st.info("No hay datos reales para comparar aún.")
        else:
            # Normalizar etiqueta de mes/año real
            import re as _re
            def _etiqueta_mes(row):
                fr = row.get("FechaRadicacion")
                if pd.notna(fr):
                    fr = pd.to_datetime(fr, errors="coerce")
                    if pd.notna(fr):
                        return f"{MES_NOMBRE[int(fr.month)]} {int(fr.year)}"
                m = str(row.get("Mes", "")).strip()
                if _re.search(r"\b20\d{2}\b", m):
                    return m
                vig = str(row.get("Vigencia", "")).strip()
                if m and vig.isdigit():
                    return f"{m} {vig}"
                return m or "Sin Mes"

            df_rad = dfv[dfv["EstadoNorm"] == "Radicada"].copy()
            df_rad["MesClave"] = df_rad.apply(_etiqueta_mes, axis=1)

            reales = df_rad.groupby("MesClave")["NumeroFactura"].nunique().reset_index(name="Cuentas reales")

            comp = base.merge(reales, left_on="Mes", right_on="MesClave", how="left").drop(columns=["MesClave"]).fillna(0)
            comp["Cuentas reales"] = comp["Cuentas reales"].astype(int)
            comp["Cuentas reales acumuladas"] = comp["Cuentas reales"].cumsum()
            comp["% real acumulado"] = (comp["Cuentas reales acumuladas"] / meta_total * 100).round(2) if meta_total else 0.0
            comp["Diferencia % (Real - Proy)"] = (comp["% real acumulado"] - comp["% proyectado acumulado"]).round(2)

            st.dataframe(comp, use_container_width=True)

            fig = go.Figure()
            fig.add_trace(go.Scatter(x=comp["Mes"], y=comp["% proyectado acumulado"],
                                     mode='lines+markers', name='Proyectado'))
            fig.add_trace(go.Scatter(x=comp["Mes"], y=comp["% real acumulado"],
                                     mode='lines+markers', name='Real'))
            fig.update_layout(title="Avance acumulado (%) — Real vs Proyectado", yaxis_title="% acumulado", xaxis_title="Mes")
            st.plotly_chart(fig, use_container_width=True)

            total_real = int(comp["Cuentas reales"].sum())
            avance_real_total = (total_real / meta_total * 100) if meta_total else 0.0
            c1, c2, c3 = st.columns(3)
            c1.metric("Meta total (cuentas)", f"{meta_total:,}")
            c2.metric("Reales acumuladas", f"{total_real:,}")
            c3.metric("Avance total vs meta", f"{avance_real_total:.1f}%")

# ====== BOOT ======
if "autenticado" not in st.session_state:
    login()
elif st.session_state.get("autenticado"):
    main_app()
