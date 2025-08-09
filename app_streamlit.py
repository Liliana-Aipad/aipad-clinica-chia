
# app_streamlit.py
# -*- coding: utf-8 -*-
APP_VERSION = "2025-08-09 08:15"

import streamlit as st
st.set_page_config(layout="wide", page_title="AIPAD • Control de Radicación")

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, date
import io, os, re, time, tempfile
import streamlit.components.v1 as components

# === Rutas absolutas ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INVENTARIO_FILE = os.path.join(BASE_DIR, "inventario_cuentas.xlsx")
USUARIOS_FILE   = os.path.join(BASE_DIR, "usuarios.xlsx")
LOCK_FILE       = os.path.join(BASE_DIR, ".inventario.lock")

# Colores por estado (solo vistas)
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

# ===================== Helpers base =====================
def _to_ts(d):
    """Convierte date/datetime/str a Timestamp o NaT."""
    return pd.to_datetime(d, errors="coerce") if d not in (None, "", pd.NaT) else pd.NaT

def _acquire_lock(timeout=10.0, poll=0.25):
    """Archivo lock sencillo para multiusuario en red local/Cloud. Espera hasta timeout."""
    start = time.time()
    while True:
        try:
            # O_EXCL asegura exclusividad
            fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return True
        except FileExistsError:
            if time.time() - start > timeout:
                return False
            time.sleep(poll)

def _release_lock():
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    except Exception:
        pass

def guardar_inventario(df: pd.DataFrame):
    """Escritura atómica y con lock. Solo se llama cuando el usuario guarda o mueve."""
    if not _acquire_lock():
        raise RuntimeError("No se pudo obtener el bloqueo de escritura (varios usuarios escribiendo). Intenta de nuevo.")
    try:
        dir_dest = os.path.dirname(INVENTARIO_FILE) or "."
        with tempfile.NamedTemporaryFile(suffix=".xlsx", dir=dir_dest, delete=False) as tf:
            tmp_path = tf.name
        with pd.ExcelWriter(tmp_path, engine="openpyxl") as w:
            df.to_excel(w, index=False)
        os.replace(tmp_path, INVENTARIO_FILE)
        st.cache_data.clear()
    finally:
        _release_lock()

@st.cache_data
def load_data():
    """Carga sin normalizar ni alterar datos. No rellena valores."""
    if not os.path.exists(INVENTARIO_FILE):
        cols = ["ID","NumeroFactura","Valor","EPS","Vigencia","Estado",
                "Mes","FechaRadicacion","FechaMovimiento","Observaciones"]
        return pd.DataFrame(columns=cols)
    df = pd.read_excel(INVENTARIO_FILE)
    for col in ["FechaRadicacion","FechaMovimiento"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    if "Valor" in df.columns:
        df["Valor"] = pd.to_numeric(df["Valor"], errors="coerce")
    if "Vigencia" in df.columns:
        df["Vigencia"] = pd.to_numeric(df["Vigencia"], errors="coerce")
    return df

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

# ===================== Auth =====================
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

# ===================== Movimiento masivo (sin tocar FechaRadicacion) =====================
def aplicar_movimiento_masivo(df: pd.DataFrame, indices, nuevo_estado: str):
    ahora = pd.Timestamp(datetime.now())
    for idx in indices:
        df.at[idx, "Estado"] = nuevo_estado
        df.at[idx, "FechaMovimiento"] = ahora
    guardar_inventario(df)

# ===================== Excel export =====================
def exportar_dashboard_excel(df: pd.DataFrame, df_view: pd.DataFrame) -> bytes:
    out = io.BytesIO()
    total = len(df)
    radicadas = int((df_view["EstadoCanon"] == "Radicada").sum())
    total_valor = float(df.get("Valor", pd.Series(dtype=float)).fillna(0).sum())
    avance = round((radicadas / total) * 100, 2) if total else 0.0

    with pd.ExcelWriter(out, engine="openpyxl") as w:
        pd.DataFrame({
            "Métrica": ["Total facturas", "Valor total", "% Avance (radicadas)"],
            "Valor": [total, total_valor, avance]
        }).to_excel(w, index=False, sheet_name="Resumen")

        if {"EPS","NumeroFactura"}.issubset(df.columns):
            g_eps = df.groupby("EPS", dropna=False).agg(
                N_Facturas=("NumeroFactura","count"),
                Valor_Total=("Valor", "sum")
            ).reset_index()
            g_eps.to_excel(w, index=False, sheet_name="Por_EPS")

        if {"Vigencia","NumeroFactura"}.issubset(df.columns):
            g_vig = df.groupby("Vigencia", dropna=False).agg(
                N_Facturas=("NumeroFactura","count"),
                Valor_Total=("Valor", "sum")
            ).reset_index()
            g_vig.to_excel(w, index=False, sheet_name="Por_Vigencia")
    return out.getvalue()

def exportar_reportes_excel(total, valor_total, avance, t_eps, t_vig, t_mes):
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        pd.DataFrame(
            {"Métrica": ["# Facturas", "Valor total", "% Avance general"],
             "Valor": [total, valor_total, avance]}
        ).to_excel(w, index=False, sheet_name="Resumen")
        if t_eps is not None and not t_eps.empty: t_eps.to_excel(w, index=False, sheet_name="Por_EPS")
        if t_vig is not None and not t_vig.empty: t_vig.to_excel(w, index=False, sheet_name="Por_Vigencia")
        if t_mes is not None and not t_mes.empty: t_mes.to_excel(w, index=False, sheet_name="Por_Mes")
    return out.getvalue()

# ===================== App =====================
def main_app():
    st.caption(f"🆔 Versión: {APP_VERSION}")
    st.title("📊 AIPAD • Control de Radicación")
    if "usuario" in st.session_state and "rol" in st.session_state:
        st.markdown(f"👤 Usuario: `{st.session_state['usuario']}`  |  🔐 Rol: `{st.session_state['rol']}`")

    # Carga de datos (sin tocar archivo)
    df = load_data()
    df_view = df.copy()

    # Normalización SOLO para vistas
    if "Estado" in df_view.columns:
        norm = df_view["Estado"].astype(str).str.strip().str.lower()
        mapa = {
            "radicada": "Radicada", "radicadas": "Radicada",
            "pendiente": "Pendiente",
            "auditada": "Auditada", "auditadas": "Auditada",
            "subsanada": "Subsanada", "subsanadas": "Subsanada",
        }
        df_view["EstadoCanon"] = norm.map(mapa).fillna(df_view["Estado"])
    else:
        df_view["EstadoCanon"] = ""

    tabs = st.tabs(["📋 Dashboard", "🗂️ Bandejas", "📝 Gestión", "📑 Reportes", "📈 Avance"])
    tab_dash, tab_bandejas, tab_gestion, tab_reportes, tab_avance = tabs

    # --------------------- Dashboard ---------------------
    with tab_dash:
        st.subheader("📈 Avance general")
        if df.empty:
            st.info("No hay datos en el inventario.")
        else:
            total = len(df)
            radicadas = int((df_view["EstadoCanon"] == "Radicada").sum())
            total_valor = float(df.get("Valor", pd.Series(dtype=float)).fillna(0).sum())
            avance = round((radicadas / total) * 100, 2) if total else 0.0

            c1, c2, c3 = st.columns(3)
            c1.metric("📦 Total facturas", total)
            c2.metric("💰 Valor total", f"${total_valor:,.0f}")
            c3.metric("📊 Avance (radicadas)", f"{avance}%")

            # ---- EPS (una sola línea con dos gráficos) ----
            st.markdown("## 🏥 Por EPS")
            e1, e2 = st.columns(2)

            if {"EPS","NumeroFactura"}.issubset(df.columns):
                g_cnt = df.groupby("EPS", dropna=False)["NumeroFactura"].count().reset_index(name="Cantidad")
                g_cnt = g_cnt.sort_values("Cantidad", ascending=False).head(25)
                total_cnt = g_cnt["Cantidad"].sum() if not g_cnt.empty else 0
                g_cnt["%"] = (g_cnt["Cantidad"]/total_cnt*100).round(1) if total_cnt else 0

                with e1:
                    fig_funnel = px.funnel(g_cnt, x="Cantidad", y="EPS", title="Cantidad y % por EPS")
                    fig_funnel.update_traces(text=g_cnt.apply(lambda r: f"{int(r['Cantidad'])} ({r['%']}%)", axis=1),
                                             textposition="inside")
                    st.plotly_chart(fig_funnel, use_container_width=True)

                with e2:
                    if {"Valor","Estado"}.issubset(df.columns):
                        df_rad = df_view[df_view["EstadoCanon"]=="Radicada"].copy()
                        g_val = df_rad.groupby("EPS", dropna=False)["Valor"].sum().reset_index(name="ValorRadicado")
                        g_val = g_val.sort_values("ValorRadicado", ascending=False)
                        fig_eps_val = px.bar(g_val, x="EPS", y="ValorRadicado",
                                             title="Valor radicado por EPS (solo Radicadas)",
                                             text_auto=".2s")
                        fig_eps_val.update_layout(xaxis={'categoryorder':'total descending'})
                        st.plotly_chart(fig_eps_val, use_container_width=True)

            # ---- Vigencia (una sola línea con dos gráficos) ----
            st.markdown("## 📆 Por Vigencia")
            v1, v2 = st.columns(2)

            if {"Vigencia","Estado","Valor"}.issubset(df.columns):
                with v1:
                    fig_vig_val = px.bar(df, x="Vigencia", y="Valor", color="Estado",
                                         title="Valor por Vigencia (por Estado)",
                                         barmode="group", color_discrete_map=ESTADO_COLORES, text_auto=".2s")
                    st.plotly_chart(fig_vig_val, use_container_width=True)

                with v2:
                    g_vig_cnt = df.groupby("Vigencia", dropna=False)["NumeroFactura"].count().reset_index(name="Cantidad")
                    fig_vig_donut = px.pie(g_vig_cnt, names="Vigencia", values="Cantidad",
                                           hole=0.4, title="Distribución de Facturas por Vigencia")
                    fig_vig_donut.update_traces(textposition="inside", textinfo="percent+value")
                    st.plotly_chart(fig_vig_donut, use_container_width=True)

            # Descarga Excel de Dashboard
            st.divider()
            xls_bytes = exportar_dashboard_excel(df, df_view)
            st.download_button(
                "⬇️ Descargar Dashboard a Excel",
                data=xls_bytes,
                file_name="dashboard_radicacion.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )

            # Panel de diagnóstico
            with st.expander("🧪 Diagnóstico de inventario"):
                st.code(f"Inventario: {INVENTARIO_FILE}", language="bash")
                cdx1, cdx2 = st.columns(2)
                if cdx1.button("🔄 Forzar recarga desde disco"):
                    st.cache_data.clear(); st.rerun()
                if cdx2.button("👀 Ver últimas 5 filas (desde disco)"):
                    try:
                        df_disk = pd.read_excel(INVENTARIO_FILE)
                        st.dataframe(df_disk.tail(5), use_container_width=True)
                    except Exception as e:
                        st.error(f"No pude leer el archivo: {e}")

    # --------------------- Bandejas ---------------------
    with tab_bandejas:
        st.subheader("🗂️ Bandejas por estado")
        if df.empty:
            st.info("No hay datos para mostrar.")
        else:
            c1, c2, c3, c4 = st.columns([1.4,1,1,1])
            q = c1.text_input("🔎 Buscar factura (contiene)")
            eps_opts = ["Todos"] + sorted([e for e in df.get("EPS", pd.Series(dtype=str)).dropna().astype(str).unique().tolist() if e])
            eps_sel = c2.selectbox("EPS", eps_opts, index=0)
            vig_opts = ["Todos"] + sorted([str(int(v)) for v in pd.to_numeric(df.get("Vigencia", pd.Series(dtype=float)), errors="coerce").dropna().unique().tolist()])
            vig_sel = c3.selectbox("Vigencia", vig_opts, index=0)
            per_page = c4.selectbox("Filas por página", [50,100,200], index=1)

            estado_tabs = st.tabs(ESTADOS)
            def _filtrar(df_, estado, eps, vig, qtext):
                sub = df_[df_["Estado"] == estado].copy()
                if eps and eps != "Todos":
                    sub = sub[sub["EPS"].astype(str) == eps]
                if vig and vig != "Todos":
                    sub = sub[sub["Vigencia"].astype(str) == str(vig)]
                if qtext:
                    qn = str(qtext).strip().lower()
                    sub = sub[sub["NumeroFactura"].astype(str).str.lower().str.contains(qn)]
                return sub

            def _paginar(df_, page, per_page_):
                total = len(df_)
                total_pages = max((total - 1)//per_page_ + 1, 1)
                page = max(1, min(page, total_pages))
                a = (page-1)*per_page_
                b = a + per_page_
                return df_.iloc[a:b], total_pages, page

            for estado, tab in zip(ESTADOS, estado_tabs):
                with tab:
                    sub = _filtrar(df, estado, eps_sel, vig_sel, q)
                    sub = sub.sort_values(by=["FechaMovimiento","NumeroFactura"], ascending=[False, True])

                    key_page = f"page_{estado}"
                    if key_page not in st.session_state:
                        st.session_state[key_page] = 1

                    page_df, total_pages, current_page = _paginar(sub, st.session_state[key_page], per_page)
                    st.session_state[key_page] = current_page

                    cpa, cpb, cpc = st.columns([1,2,1])
                    prevb = cpa.button("⬅️ Anterior", disabled=(current_page<=1), key=f"prev_{estado}")
                    cpb.markdown(f"**Página {current_page} / {total_pages}** &nbsp; (**{len(sub)}** registros)")
                    nextb = cpc.button("Siguiente ➡️", disabled=(current_page>=total_pages), key=f"next_{estado}")
                    if prevb:
                        st.session_state[key_page] = max(1, current_page-1); st.rerun()
                    if nextb:
                        st.session_state[key_page] = min(total_pages, current_page+1); st.rerun()

                    st.divider()
                    sel_all = st.checkbox("Seleccionar todo (esta página)", key=f"selall_{estado}_{current_page}", value=False)
                    cols = ["ID","NumeroFactura","EPS","Vigencia","Valor","FechaRadicacion","FechaMovimiento","Observaciones"]
                    view = page_df[cols].copy()
                    view.insert(0, "Seleccionar", sel_all)
                    edited = st.data_editor(
                        view, hide_index=True, use_container_width=True, num_rows="fixed",
                        column_config={"Seleccionar": st.column_config.CheckboxColumn("Seleccionar", default=False)},
                        key=f"editor_{estado}_{current_page}",
                    )
                    try:
                        mask = edited["Seleccionar"].fillna(False).tolist()
                    except Exception:
                        mask = [False]*len(page_df)
                    seleccionados = [idx for pos, idx in enumerate(page_df.index.tolist()) if pos < len(mask) and mask[pos]]

                    st.divider()
                    c1m, c2m = st.columns([2,1])
                    nuevo_estado = c1m.selectbox("Mover seleccionadas a:", [e for e in ESTADOS if e != estado])
                    mover = c2m.button("Aplicar movimiento", type="primary", disabled=(len(seleccionados)==0), key=f"mover_{estado}")
                    if mover:
                        aplicar_movimiento_masivo(df, seleccionados, nuevo_estado)
                        st.success(f"✅ Se movieron {len(seleccionados)} facturas de {estado} → {nuevo_estado}")
                        st.rerun()

    # --------------------- Gestión (captura y edición) ---------------------
    with tab_gestion:
        st.subheader("📝 Gestión")
        # Búsqueda
        c1, c2 = st.columns([2,1])
        q_factura = c1.text_input("🔎 Buscar por Número de factura", key="buscar_factura_input")
        buscar = c2.button("Buscar / Cargar", type="primary")
        if buscar and q_factura.strip():
            st.session_state["factura_activa"] = q_factura.strip()
        numero_activo = st.session_state.get("factura_activa", "")

        if not numero_activo:
            st.info("Ingresa un número de factura y presiona **Buscar / Cargar** para editar o crear.")
        else:
            # Localizar
            df = load_data()  # recargar por si otro usuario guardó mientras tanto
            mask = df.get("NumeroFactura", pd.Series(dtype=str)).astype(str).str.strip() == str(numero_activo).strip()
            existe = bool(mask.any())
            idx = df[mask].index[0] if existe else None
            fila = df.loc[idx] if existe else pd.Series(dtype=object)

            # Defaults
            def getv(s, k, default=None):
                v = s.get(k, default) if isinstance(s, pd.Series) else default
                if v is None: return default
                try:
                    return v if not pd.isna(v) else default
                except Exception:
                    return v

            def_val = {
                "ID": getv(fila, "ID", ""),
                "NumeroFactura": str(getv(fila, "NumeroFactura", numero_activo) or numero_activo),
                "Valor": float(getv(fila, "Valor", 0) or 0.0),
                "EPS": str(getv(fila, "EPS", "") or ""),
                "Vigencia": getv(fila, "Vigencia", date.today().year),
                "Estado": str(getv(fila, "Estado", "Pendiente") or "Pendiente"),
                "FechaRadicacion": getv(fila, "FechaRadicacion", pd.NaT),
                "FechaMovimiento": getv(fila, "FechaMovimiento", pd.NaT),
                "Observaciones": str(getv(fila, "Observaciones","") or ""),
                "Mes": str(getv(fila, "Mes","") or ""),
            }

            # Estado y fecha de radicación
            ctop1, ctop2, ctop3 = st.columns(3)
            ctop1.text_input("ID (automático)", value=def_val["ID"], disabled=True)
            estados_opciones = ESTADOS
            est_val = ctop2.selectbox("Estado", options=estados_opciones,
                                      index=estados_opciones.index(def_val["Estado"]) if def_val["Estado"] in estados_opciones else 0,
                                      key="estado_val")
            frad_disabled = (est_val != "Radicada")
            frad_val = ctop3.date_input("Fecha de Radicación",
                                        value=(def_val["FechaRadicacion"].date() if pd.notna(def_val["FechaRadicacion"]) else date.today()),
                                        disabled=frad_disabled, key="frad_val")

            # Formulario principal
            with st.form("form_factura", clear_on_submit=False):
                cfa, cfb = st.columns(2)
                num_val = cfa.text_input("Número de factura", value=def_val["NumeroFactura"])
                valor_val = cfa.number_input("Valor", min_value=0.0, step=1000.0, value=float(def_val["Valor"]))
                eps_val = cfa.text_input("EPS", value=def_val["EPS"])
                vig_val = cfb.text_input("Vigencia", value=str(def_val["Vigencia"]))
                obs_val = cfb.text_area("Observaciones", value=def_val["Observaciones"], height=100)

                submit = st.form_submit_button("💾 Guardar cambios", type="primary")

            if submit:
                ahora = pd.Timestamp(datetime.now())

                # Re-localizar por si cambió NumeroFactura en el form (edición de clave)
                mask2 = df.get("NumeroFactura", pd.Series(dtype=str)).astype(str).str.strip() == str(num_val).strip()
                existe2 = bool(mask2.any())
                idx2 = df[mask2].index[0] if existe2 else None

                estado_anterior = (str(df.loc[idx2, "Estado"]).strip() if existe2 else (str(def_val["Estado"]) or "")).strip()
                estado_actual = st.session_state.get("estado_val", estado_anterior or "Pendiente")

                # Fecha de radicación
                frad_widget = st.session_state.get("frad_val", def_val["FechaRadicacion"] if pd.notna(def_val["FechaRadicacion"]) else date.today())
                frad_ts = _to_ts(frad_widget) if estado_actual == "Radicada" else (df.loc[idx2, "FechaRadicacion"] if (existe2 and "FechaRadicacion" in df.columns) else def_val["FechaRadicacion"])

                # Mes: conservar; recalcular solo si frad_ts válido
                mes_anterior = (df.loc[idx2, "Mes"] if existe2 and "Mes" in df.columns else def_val["Mes"])
                mes_nuevo = mes_anterior
                if pd.notna(frad_ts):
                    mes_nuevo = f"{MES_NOMBRE[int(pd.to_datetime(frad_ts).month)]}"

                # FechaMovimiento: SOLO si cambia Estado o es nuevo
                estado_cambio = (estado_actual != estado_anterior) or (not existe2)
                fecha_mov = (ahora if estado_cambio else (df.loc[idx2, "FechaMovimiento"] if (existe2 and "FechaMovimiento" in df.columns) else def_val["FechaMovimiento"]))

                # ID
                if existe2 and "ID" in df.columns:
                    new_id = df.loc[idx2, "ID"]
                else:
                    # generar
                    if "ID" in df.columns and pd.to_numeric(df["ID"].astype(str).str.extract(r'(\d+)$')[0], errors="coerce").notna().any():
                        nums = pd.to_numeric(df["ID"].astype(str).str.extract(r'(\d+)$')[0], errors="coerce").dropna()
                        seq = int(nums.max()) + 1 if not nums.empty else 1
                    else:
                        seq = 1
                    new_id = f"CHIA-{seq:04d}"

                # Construcción registro
                registro = {
                    "ID": new_id,
                    "NumeroFactura": str(num_val).strip(),
                    "Valor": float(valor_val),
                    "EPS": str(eps_val).strip(),
                    "Vigencia": int(vig_val) if str(vig_val).isdigit() else vig_val,
                    "Estado": estado_actual,
                    "FechaRadicacion": frad_ts,
                    "FechaMovimiento": fecha_mov,
                    "Observaciones": str(obs_val).strip(),
                    "Mes": mes_nuevo,
                }

                # Escribir y guardar
                if existe2:
                    for k,v in registro.items():
                        df.at[idx2, k] = v
                else:
                    df = pd.concat([df, pd.DataFrame([registro])], ignore_index=True)

                try:
                    guardar_inventario(df)
                    st.success(f"✅ Cambios guardados — Factura **{str(num_val).strip()}**")
                    # limpiar selección para evitar sobrescrituras no deseadas
                    st.session_state["factura_activa"] = ""
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Error guardando el inventario: {e}")

    # --------------------- Reportes ---------------------
    with tab_reportes:
        st.subheader("📑 Reportes")
        if df.empty:
            st.info("No hay datos en el inventario para generar reportes.")
        else:
            total = len(df)
            valor_total = float(df.get("Valor", pd.Series(dtype=float)).fillna(0).sum())
            radicadas = int((df_view["EstadoCanon"] == "Radicada").sum())
            avance = round((radicadas / total) * 100, 2) if total else 0.0

            k1,k2,k3 = st.columns(3)
            k1.metric("Número de facturas", f"{total:,}")
            k2.metric("Valor total", f"${valor_total:,.0f}")
            k3.metric("% avance general", f"{avance}%")

            st.markdown("### Gráficos")
            if {"EPS","NumeroFactura"}.issubset(df.columns):
                eps_count = df.groupby("EPS")["NumeroFactura"].count().reset_index(name="Facturas")
                fig_eps_funnel = px.funnel(eps_count.sort_values("Facturas", ascending=False).head(25),
                                           x="Facturas", y="EPS", title="Embudo por EPS (Top 25, # de facturas)")
                st.plotly_chart(fig_eps_funnel, use_container_width=True)

            if {"Vigencia","NumeroFactura"}.issubset(df.columns):
                vig_cnt = df.groupby("Vigencia")["NumeroFactura"].count().reset_index(name="Facturas")
                fig_vig_donut = px.pie(vig_cnt, names="Vigencia", values="Facturas",
                                       hole=0.4, title="Participación por Vigencia")
                fig_vig_donut.update_traces(textposition="inside", textinfo="percent+value")
                st.plotly_chart(fig_vig_donut, use_container_width=True)

            if {"Mes","NumeroFactura"}.issubset(df.columns):
                mes_cnt = df.groupby("Mes")["NumeroFactura"].count().reset_index(name="Facturas")
                fig_mes_donut = px.pie(mes_cnt, names="Mes", values="Facturas",
                                       hole=0.4, title="Participación por Mes")
                fig_mes_donut.update_traces(textposition="inside", textinfo="percent+value")
                st.plotly_chart(fig_mes_donut, use_container_width=True)

            st.markdown("### Resúmenes")
            def tabla_resumen(df_, by, nombre):
                g = df_.groupby(by, dropna=False).agg(
                    Facturas=("NumeroFactura","count"),
                    Valor=("Valor","sum"),
                ).reset_index()
                st.subheader(f"Resumen por {nombre}")
                st.dataframe(g, use_container_width=True)
                return g

            t_eps = tabla_resumen(df, "EPS", "EPS") if "EPS" in df.columns else pd.DataFrame()
            t_vig = tabla_resumen(df, "Vigencia", "Vigencia") if "Vigencia" in df.columns else pd.DataFrame()
            t_mes = tabla_resumen(df, "Mes", "Mes") if "Mes" in df.columns else pd.DataFrame()

            st.markdown("### Descarga")
            xls_rep = exportar_reportes_excel(total, valor_total, avance, t_eps, t_vig, t_mes)
            st.download_button(
                "⬇️ Descargar reportes a Excel",
                data=xls_rep,
                file_name="reportes_radicacion.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )

    # --------------------- Avance ---------------------
    with tab_avance:
        st.subheader("📈 Avance (Real vs Proyectado — Acumulado)")

        base = pd.DataFrame({
            "Mes": ["Agosto 2025","Septiembre 2025","Octubre 2025","Noviembre 2025"],
            "Cuentas estimadas": [515, 1489, 1797, 1738],
        })
        base["Cuentas estimadas acumuladas"] = base["Cuentas estimadas"].cumsum()
        total_meta = int(base["Cuentas estimadas"].sum())
        base["% proyectado acumulado"] = (base["Cuentas estimadas acumuladas"] / total_meta * 100).round(2) if total_meta else 0.0

        def _etq_mes(row):
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

        df_view = load_data().copy()
        if "Estado" in df_view.columns:
            norm = df_view["Estado"].astype(str).str.strip().str.lower()
            mapa = {
                "radicada": "Radicada", "radicadas": "Radicada",
                "pendiente": "Pendiente",
                "auditada": "Auditada", "auditadas": "Auditada",
                "subsanada": "Subsanada", "subsanadas": "Subsanada",
            }
            df_view["EstadoCanon"] = norm.map(mapa).fillna(df_view["Estado"])
        else:
            df_view["EstadoCanon"] = ""

        df_rad = df_view[df_view["EstadoCanon"]=="Radicada"].copy()
        if df_rad.empty:
            st.info("Aún no hay cuentas radicadas para comparar.")
        else:
            df_rad["MesClave"] = df_rad.apply(_etq_mes, axis=1)
            reales = df_rad.groupby("MesClave")["NumeroFactura"].nunique().reset_index(name="Cuentas reales")
            comp = base.merge(reales, left_on="Mes", right_on="MesClave", how="left").drop(columns=["MesClave"]).fillna(0)
            comp["Cuentas reales"] = comp["Cuentas reales"].astype(int)
            comp["Cuentas reales acumuladas"] = comp["Cuentas reales"].cumsum()
            comp["% real acumulado"] = (comp["Cuentas reales acumuladas"] / total_meta * 100).round(2) if total_meta else 0.0
            comp["Diferencia % (Real - Proy)"] = (comp["% real acumulado"] - base["% proyectado acumulado"]).round(2)

            st.dataframe(comp, use_container_width=True)

            fig = go.Figure()
            fig.add_trace(go.Scatter(x=base["Mes"], y=base["% proyectado acumulado"],
                                     mode='lines+markers', name='Proyectado'))
            fig.add_trace(go.Scatter(x=comp["Mes"], y=comp["% real acumulado"],
                                     mode='lines+markers', name='Real'))
            fig.update_layout(title="Avance acumulado (%) — Real vs Proyectado",
                              yaxis_title="% acumulado", xaxis_title="Mes")
            st.plotly_chart(fig, use_container_width=True)

            k1,k2,k3 = st.columns(3)
            k1.metric("Meta total (cuentas)", f"{total_meta:,}")
            k2.metric("Reales acumuladas", f"{int(comp['Cuentas reales'].sum()):,}")
            k3.metric("Avance total vs meta", f"{(comp['Cuentas reales'].sum()/total_meta*100 if total_meta else 0):.1f}%")

# ====== Boot ======
if "autenticado" not in st.session_state:
    login()
elif st.session_state.get("autenticado"):
    main_app()
