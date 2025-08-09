# app_streamlit.py
APP_VERSION = "2025-08-09 01:30"

import streamlit as st
st.set_page_config(layout="wide")  # Debe ser lo primero en Streamlit

import pandas as pd
import os, re, io, zipfile
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
    df.to_excel(INVENTARIO_FILE, index=False)
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

# ====== Reportes Helpers ======
def _kpis(df: pd.DataFrame):
    total = len(df)
    valor_total = float(df["Valor"].fillna(0).sum()) if "Valor" in df.columns else 0.0
    radicadas = int((df["Estado"] == "Radicada").sum()) if "Estado" in df.columns else 0
    avance = (radicadas / total * 100) if total else 0.0
    return total, valor_total, round(avance, 2)

def _tabla_resumen(df: pd.DataFrame, by: str, nombre: str):
    g = df.groupby(by, dropna=False).agg(
        Facturas=("NumeroFactura","count"),
        Valor=("Valor","sum"),
        Radicadas=("Estado", lambda s: (s=="Radicada").sum()),
        Pendientes=("Estado", lambda s: (s=="Pendiente").sum()),
        Auditadas=("Estado", lambda s: (s=="Auditada").sum()),
        Subsanadas=("Estado", lambda s: (s=="Subsanada").sum()),
    ).reset_index().fillna(0)
    g["% Avance"] = (g["Radicadas"] / g["Facturas"]).replace([0, float('inf')], 0).fillna(0) * 100
    st.subheader(f"Resumen por {nombre}")
    st.dataframe(g, use_container_width=True)
    return g

def _exportar_reportes_excel(kpis, t_eps, t_vig, t_mes):
    """
    Intenta exportar a XLSX con openpyxl. Si no está disponible en el entorno,
    exporta CSVs dentro de un ZIP como fallback.
    Retorna (bytes, filename, mime).
    """
    # Intento XLSX con openpyxl
    try:
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            pd.DataFrame(
                {"Métrica": ["# Facturas","Valor total","% Avance general"],
                 "Valor":   [kpis[0], kpis[1], kpis[2]]}
            ).to_excel(writer, index=False, sheet_name="Resumen")
            t_eps.to_excel(writer, index=False, sheet_name="Por_EPS")
            t_vig.to_excel(writer, index=False, sheet_name="Por_Vigencia")
            t_mes.to_excel(writer, index=False, sheet_name="Por_Mes")
        return output.getvalue(), "reportes_radicacion.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    except ModuleNotFoundError:
        # Fallback: CSV a ZIP
        output = io.BytesIO()
        with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            # Resumen
            df_res = pd.DataFrame(
                {"Métrica": ["# Facturas","Valor total","% Avance general"],
                 "Valor":   [kpis[0], kpis[1], kpis[2]]}
            )
            zf.writestr("Resumen.csv", df_res.to_csv(index=False, encoding="utf-8-sig"))
            zf.writestr("Por_EPS.csv", t_eps.to_csv(index=False, encoding="utf-8-sig"))
            zf.writestr("Por_Vigencia.csv", t_vig.to_csv(index=False, encoding="utf-8-sig"))
            zf.writestr("Por_Mes.csv", t_mes.to_csv(index=False, encoding="utf-8-sig"))
        return output.getvalue(), "reportes_radicacion.zip", "application/zip"

# ====== APP ======
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
    elif qp.get("tab", [""])[0] == "reportes":
        _select_tab("📑 Reportes")

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

                    # Selección por fila en la página (sin listar textos; todo dentro del editor)
                    st.divider()
                    sel_all_key = f"sel_all_{estado}_{current_page}"
                    sel_all = st.checkbox("Seleccionar todo (esta página)", key=sel_all_key, value=False)

                    # Vista de la página con columna 'Seleccionar' editable y un índice oculto
                    cols_mostrar = ["ID","NumeroFactura","EPS","Vigencia","Valor","FechaRadicacion","FechaMovimiento","Observaciones"]
                    view = sub_page[cols_mostrar].copy()
                    view.insert(0, "Seleccionar", sel_all)   # por defecto según el checkbox global
                    view.insert(1, "__idx", sub_page.index)   # índice original para mapear

                    # Definir orden de columnas para "ocultar" __idx
                    column_order = ["Seleccionar","ID","NumeroFactura","EPS","Vigencia","Valor","FechaRadicacion","FechaMovimiento","Observaciones","__idx"]

                    edited = st.data_editor(
                        view,
                        hide_index=True,
                        use_container_width=True,
                        num_rows="fixed",
                        column_config={
                            "Seleccionar": st.column_config.CheckboxColumn("Seleccionar", help="Marca las filas a mover", default=False),
                            "__idx": st.column_config.Column("", width="small", disabled=True),  # sin 'hidden'
                            "ID": st.column_config.Column("ID", disabled=True, width="small"),
                            "NumeroFactura": st.column_config.Column("Número de factura", disabled=True),
                            "EPS": st.column_config.Column("EPS", disabled=True),
                            "Vigencia": st.column_config.Column("Vigencia", disabled=True, width="small"),
                            "Valor": st.column_config.Column("Valor", disabled=True),
                            "FechaRadicacion": st.column_config.Column("Fecha Radicación", disabled=True),
                            "FechaMovimiento": st.column_config.Column("Fecha Movimiento", disabled=True),
                            "Observaciones": st.column_config.Column("Observaciones", disabled=True),
                        },
                        column_order=column_order[:-1],  # no mostrar __idx
                        key=f"editor_{estado}_{current_page}",
                    )

                    # Determinar seleccionados
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
                    "Vigencia": int(fila.get("Vigencia", date.today().year)) if pd.notna(fila.get("Vigencia", pd.NaT)) else date.today().year,
                    "Estado": str(fila.get("Estado","Pendiente") if pd.notna(fila.get("Estado", pd.NaT)) else "Pendiente"),
                    "FechaRadicacion": fila.get("FechaRadicacion", pd.NaT),
                    "FechaMovimiento": fila.get("FechaMovimiento", pd.NaT),
                    "Observaciones": str(fila.get("Observaciones","") if pd.notna(fila.get("Observaciones", pd.NaT)) else ""),
                    "Mes": str(fila.get("Mes","") if pd.notna(fila.get("Mes", pd.NaT)) else ""),
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
            st.info("No hay datos en el inventario.")
        else:
            # Asegurar 'Mes' calculado desde FechaRadicacion si falta o está vacío
            if "Mes" not in df.columns or df["Mes"].isna().all():
                if "FechaRadicacion" in df.columns:
                    fr = pd.to_datetime(df["FechaRadicacion"], errors="coerce")
                    df["Mes"] = fr.dt.month.map(MES_NOMBRE).fillna("")
                else:
                    df["Mes"] = ""

            # KPIs
            total, valor_total, avance = _kpis(df)
            c1, c2, c3 = st.columns(3)
            c1.metric("Número de facturas", f"{total:,}")
            c2.metric("Valor total", f"${valor_total:,.0f}")
            c3.metric("% avance general", f"{avance:.1f}%")

            st.divider()
            st.subheader("Gráficos")

            # 1) EPS - barras con etiquetas
            if "EPS" in df.columns:
                eps_count = df.groupby("EPS")["NumeroFactura"].count().reset_index(name="Facturas")
                fig_eps = px.bar(
                    eps_count.sort_values("Facturas", ascending=False).head(25),
                    x="EPS", y="Facturas", title="Facturas por EPS (Top 25)",
                    text="Facturas"
                )
                fig_eps.update_traces(texttemplate="%{text}", textposition="outside")
                fig_eps.update_layout(xaxis_tickangle=-45, uniformtext_minsize=10, uniformtext_mode="hide")
                st.plotly_chart(fig_eps, use_container_width=True)

            # 2) Vigencia - barras apiladas por Estado
            if {"Vigencia","Estado"}.issubset(df.columns):
                vig_estado = df.groupby(["Vigencia", "Estado"]).size().reset_index(name="Facturas")
                fig_vig = px.bar(
                    vig_estado, x="Vigencia", y="Facturas", color="Estado",
                    title="Distribución por Vigencia y Estado",
                    color_discrete_map=ESTADO_COLORES
                )
                st.plotly_chart(fig_vig, use_container_width=True)

            # 3) Mes - área apilada por Estado
            if {"Mes","Estado"}.issubset(df.columns):
                mes_estado = df.groupby(["Mes", "Estado"]).size().reset_index(name="Facturas").sort_values("Mes")
                fig_mes = px.area(
                    mes_estado, x="Mes", y="Facturas", color="Estado",
                    title="Evolución mensual por Estado",
                    color_discrete_map=ESTADO_COLORES
                )
                st.plotly_chart(fig_mes, use_container_width=True)

            # Tablas de resumen
            t_eps = _tabla_resumen(df, "EPS", "EPS") if "EPS" in df.columns else pd.DataFrame()
            t_vig = _tabla_resumen(df, "Vigencia", "Vigencia") if "Vigencia" in df.columns else pd.DataFrame()
            t_mes = _tabla_resumen(df, "Mes", "Mes") if "Mes" in df.columns else pd.DataFrame()

            # Descarga
            st.subheader("Descarga")
            bytes_data, fname, mime = _exportar_reportes_excel((total, valor_total, avance), t_eps, t_vig, t_mes)
            st.download_button(
                "⬇️ Descargar reportes",
                data=bytes_data,
                file_name=fname,
                mime=mime,
                use_container_width=True
            )

# ====== BOOT ======
if "autenticado" not in st.session_state:
    login()
elif st.session_state.get("autenticado"):
    main_app()
