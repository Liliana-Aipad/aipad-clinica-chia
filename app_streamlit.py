# app_streamlit.py
# -*- coding: utf-8 -*-
APP_VERSION = "2025-08-12 • Supabase + Excel • Valor Factura / Valor Radicado"

import os, io, re
from datetime import datetime, date
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import streamlit.components.v1 as components

st.set_page_config(layout="wide", page_title="AIPAD • Control de Radicación")

# ====== Bloqueo de archivo (parche si falta filelock) ======
try:
    from filelock import FileLock, Timeout
except Exception:
    class FileLock:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *exc): return False
    class Timeout(Exception): pass

# ====== Constantes de archivos ======
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INVENTARIO_LOCAL = os.path.join(BASE_DIR, "inventario_cuentas.xlsx")
INVENTARIO_LOCK  = INVENTARIO_LOCAL + ".lock"
USUARIOS_FILE    = os.path.join(BASE_DIR, "usuarios.xlsx")  # opcional (login)

# ====== Catálogos / colores ======
ESTADOS = ["Pendiente","Auditada","Subsanada","Radicada"]
ESTADO_COLORES = {"Radicada":"green","Pendiente":"red","Auditada":"orange","Subsanada":"blue"}
MES_NOMBRE = {1:"Enero",2:"Febrero",3:"Marzo",4:"Abril",5:"Mayo",6:"Junio",
              7:"Julio",8:"Agosto",9:"Septiembre",10:"Octubre",11:"Noviembre",12:"Diciembre"}

# ====== Mapeos App (encabezados bonitos) ↔ DB (snake_case) ======
APP2DB = {
    "ID": "id",
    "NumeroFactura": "numero_factura",        # PK en DB
    "Valor Factura": "valor_factura",
    "Valor Radicado": "valor_radicado",
    "Fecha factura": "fecha_factura",
    "EPS": "eps",
    "Documento": "documento",
    "Paciente": "paciente",
    "Vigencia": "vigencia",
    "Estado": "estado",
    "FechaMovimiento": "fecha_movimiento",
    "FechaRadicacion": "fecha_radicacion",
    "No Radicado": "no_radicado",
    "Mes": "mes",
    "Observaciones": "observaciones",
}
DB2APP = {v: k for k, v in APP2DB.items()}
DB_TABLE = "inventario"
DB_PK = "numero_factura"  # clave primaria en DB

# ====== Helpers UI ======
def flash_success(msg: str): st.session_state["_flash_ok"] = msg
def show_flash():
    msg = st.session_state.pop("_flash_ok", None)
    if msg: st.success(msg)

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

# ====== Utilidades ======
def _parse_currency(s):
    if pd.isna(s) or s == "": return pd.NA
    t = str(s).replace("$","").replace("\xa0","").replace(" ","")
    t = t.replace(".","").replace(",",".")
    try: return float(t)
    except: 
        try: return float(str(s).strip())
        except: return pd.NA

def normalize_dataframe(df_in: pd.DataFrame) -> pd.DataFrame:
    """
    Normaliza tipos sin crear columna 'Valor'. 
    Usamos explícitamente 'Valor Factura' y 'Valor Radicado' en cálculos/gráficos.
    """
    df = df_in.copy()

    # Asegurar columnas esperadas (aunque sea vacías)
    for c in APP2DB.keys():
        if c not in df.columns:
            df[c] = pd.NA

    # Fechas
    for c in ["Fecha factura","FechaRadicacion","FechaMovimiento"]:
        df[c] = pd.to_datetime(df[c], errors="coerce")

    # Números
    # Valor Factura y Valor Radicado pueden venir con formato de texto
    df["Valor Factura"] = df["Valor Factura"].apply(_parse_currency)
    df["Valor Radicado"] = df["Valor Radicado"].apply(_parse_currency)
    df["Vigencia"] = pd.to_numeric(df["Vigencia"], errors="coerce")

    # Estado canon (para filtros)
    canon_map = {
        "radicada":"Radicada","radicadas":"Radicada",
        "pendiente":"Pendiente",
        "auditada":"Auditada","auditadas":"Auditada",
        "subsanada":"Subsanada","subsanadas":"Subsanada"
    }
    df["EstadoCanon"] = df["Estado"].astype(str).str.strip().str.lower().map(canon_map).fillna(df["Estado"])

    # Mes desde FechaRadicacion si falta
    vacios = df["Mes"].isna() | (df["Mes"].astype(str).str.strip()=="")
    has_frad = df["FechaRadicacion"].notna()
    need = vacios & has_frad
    if need.any():
        df.loc[need, "Mes"] = df.loc[need, "FechaRadicacion"].dt.month.map(MES_NOMBRE)

    df = df.dropna(how="all")
    return df

# ====== Excel local (fallback / o fuente principal) ======
def _read_excel_local(path: str) -> pd.DataFrame:
    if not os.path.exists(path): return pd.DataFrame()
    try:
        df = pd.read_excel(path)
        return df
    except Exception as e:
        st.error(f"Error leyendo Excel local: {e}")
        return pd.DataFrame()

def _write_excel_local(df: pd.DataFrame, path: str) -> tuple[bool, str]:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with FileLock(INVENTARIO_LOCK, timeout=10):
            tmp = path + ".tmp.xlsx"
            with pd.ExcelWriter(tmp, engine="openpyxl") as w:
                df.to_excel(w, index=False, sheet_name="inventario_cuentas")
            if os.path.exists(path): os.remove(path)
            os.rename(tmp, path)
        return True, "OK_LOCAL"
    except Timeout:
        return False, "Otro usuario está guardando en este momento. Intenta de nuevo."
    except Exception as e:
        return False, f"Error guardando Excel local: {e}"

# ====== Supabase (cliente + mapeo snake_case) ======
try:
    from supabase import create_client, Client
except Exception:
    create_client = None
    Client = None

def _get_supabase() -> "Client|None":
    try:
        cfg = st.secrets.get("supabase", {})
        url = (cfg.get("url") or "").strip()
        key = (cfg.get("anon_key") or "").strip()
        if not url or not key:
            return None
        if not url.startswith("https://") or ".supabase.co" not in url:
            st.info("Supabase: URL no válida en secrets. Usando Excel local.")
            return None
        if not create_client:
            st.info("Supabase: librería no disponible. Usando Excel local.")
            return None
        return create_client(url, key)
    except Exception:
        return None

def _df_app_to_db(df_app: pd.DataFrame) -> pd.DataFrame:
    if df_app is None or df_app.empty:
        return pd.DataFrame()
    df = df_app.copy()

    # Garantizar columnas esperadas
    for app_col in APP2DB.keys():
        if app_col not in df.columns:
            df[app_col] = pd.NA

    # Renombrar
    df = df.rename(columns=APP2DB)

    # Fechas → timestamp
    for c in ["fecha_factura","fecha_radicacion","fecha_movimiento"]:
        df[c] = pd.to_datetime(df[c], errors="coerce")

    # Numéricos
    for c in ["valor_factura","valor_radicado","vigencia"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    # NaN/NaT → None
    df = df.where(pd.notna(df), None)
    return df

def _df_db_to_app(df_db: pd.DataFrame) -> pd.DataFrame:
    if df_db is None or df_db.empty:
        cols_min = list(APP2DB.keys())
        return pd.DataFrame(columns=cols_min)
    df = df_db.copy().rename(columns=DB2APP)

    # Normaliza a tipos
    for c in ["Fecha factura","FechaRadicacion","FechaMovimiento"]:
        df[c] = pd.to_datetime(df[c], errors="coerce")
    for c in ["Valor Factura","Valor Radicado"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["Vigencia"] = pd.to_numeric(df["Vigencia"], errors="coerce")
    return df

def supabase_fetch_all() -> pd.DataFrame:
    sb = _get_supabase()
    if not sb:
        raise RuntimeError("Supabase no configurado")
    res = sb.table(DB_TABLE).select("*").execute()
    rows = res.data or []
    df_db = pd.DataFrame(rows)
    df_app = _df_db_to_app(df_db)
    # asegurar todas las columnas
    for k in APP2DB.keys():
        if k not in df_app.columns:
            df_app[k] = pd.NA
    return df_app

def supabase_upsert(df_app: pd.DataFrame, pk: str = DB_PK) -> tuple[bool, str]:
    sb = _get_supabase()
    if not sb:
        return False, "Supabase no configurado"

    if df_app is None or df_app.empty:
        return True, "OK_SUPABASE_NOOP"

    df_db = _df_app_to_db(df_app)
    if df_db.empty or len(df_db.columns) == 0:
        return True, "OK_SUPABASE_NOOP"

    if pk not in df_db.columns:
        return False, f"Falta la columna PK '{pk}'"
    if df_db[pk].isna().any() or (df_db[pk].astype(str).str.strip()=="").any():
        return False, f"Hay registros sin '{pk}'"

    try:
        records = df_db.to_dict(orient="records")
        sb.table(DB_TABLE).upsert(records, on_conflict=pk).execute()
        return True, "OK_SUPABASE"
    except Exception as e:
        return False, f"Error Supabase upsert: {e}"

# ====== Carga/guardado central ======
@st.cache_data
def load_data():
    # 1) Intentar Supabase
    try:
        sb = _get_supabase()
        if sb:
            df_app = supabase_fetch_all()
            if df_app is not None and len(df_app) > 0:
                return normalize_dataframe(df_app)
            else:
                st.info("Supabase sin datos; usando Excel local.")
    except Exception as e:
        st.warning(f"No pude leer Supabase, uso Excel local: {e}")

    # 2) Excel local
    df_raw = _read_excel_local(INVENTARIO_LOCAL)
    if df_raw.empty:
        cols_min = list(APP2DB.keys())
        return normalize_dataframe(pd.DataFrame(columns=cols_min))
    return normalize_dataframe(df_raw)

def guardar_inventario(df: pd.DataFrame, factura_verificar: str | None = None) -> tuple[bool, str]:
    """Guarda en Supabase si está configurado; si no, en Excel. Luego verifica."""
    df_to_save = df.copy()

    # Tipos antes de guardar
    for c in ["Fecha factura","FechaRadicacion","FechaMovimiento"]:
        df_to_save[c] = pd.to_datetime(df_to_save[c], errors="coerce")
    for c in ["Valor Factura","Valor Radicado"]:
        df_to_save[c] = pd.to_numeric(df_to_save[c], errors="coerce")

    # Supabase
    try:
        sb = _get_supabase()
        if sb:
            ok, msg = supabase_upsert(df_to_save, pk=DB_PK)
            if not ok: return False, msg
            st.cache_data.clear()
            if factura_verificar:
                df_new = load_data()
                ok_row = df_new["NumeroFactura"].astype(str).str.strip().eq(str(factura_verificar).strip()).any()
                if not ok_row:
                    return False, f"Guardó en Supabase, pero la factura {factura_verificar} no aparece al releer."
            return True, "OK_SUPABASE"
    except Exception as e:
        st.warning(f"No pude guardar en Supabase, intento Excel local: {e}")

    # Excel
    ok, msg = _write_excel_local(df_to_save, INVENTARIO_LOCAL)
    if not ok: return False, msg
    st.cache_data.clear()
    if factura_verificar:
        df_new = load_data()
        ok_row = df_new["NumeroFactura"].astype(str).str.strip().eq(str(factura_verificar).strip()).any()
        if not ok_row:
            return False, f"Guardó en Excel, pero la factura {factura_verificar} no aparece al releer."
    return True, "OK_LOCAL"

# ====== Login opcional ======
def login():
    st.sidebar.title("🔐 Ingreso")
    with st.sidebar.form("login_form", clear_on_submit=False):
        cedula = st.text_input("Cédula", key="login_cedula")
        contrasena = st.text_input("Contraseña", type="password", key="login_pwd")
        submitted = st.form_submit_button("Ingresar", use_container_width=True)
    if submitted:
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
            st.sidebar.error(f"Error cargando usuarios: {e}\n\nSi no usas login, comenta esta sección y deja `autenticado=True`.")

# ====== App principal ======
def main_app():
    st.caption(f"🆔 Versión: {APP_VERSION}")
    st.title("📊 AIPAD • Control de Radicación")
    if "usuario" in st.session_state and "rol" in st.session_state:
        st.markdown(f"👤 Usuario: `{st.session_state['usuario']}`  |  🔐 Rol: `{st.session_state['rol']}`")

    # Tabs
    tab_tabla, tab_dash, tab_bandejas, tab_gestion, tab_reportes, tab_avance = st.tabs(
        ["📄 Tabla","📋 Dashboard","🗂️ Bandejas","📝 Gestión","📑 Reportes","📈 Avance"]
    )

    # ===== 📄 TABLA =====
    with tab_tabla:
        show_flash()
        st.subheader("📄 Tabla (inventario base)")

        up = st.file_uploader("Sube un Excel (.xlsx) con el inventario", type=["xlsx"], accept_multiple_files=False, key="uploader_tabla")
        c1, c2, c3 = st.columns([1,1,1])
        if c1.button("📥 Cargar Excel (reemplazar)", use_container_width=True, type="secondary", disabled=(up is None), key="btn_cargar_excel"):
            try:
                df_up = pd.read_excel(up)
                ok, msg = _write_excel_local(df_up, INVENTARIO_LOCAL)
                if ok:
                    st.cache_data.clear()
                    st.success(f"✅ Inventario reemplazado desde archivo '{up.name}'.")
                    st.rerun()
                else:
                    st.error(f"❌ No se pudo guardar: {msg}")
            except Exception as e:
                st.error(f"❌ Error leyendo el archivo subido: {e}")

        df_live = load_data().copy()
        st.caption(f"Registros actuales: **{len(df_live)}**")
        st.info("Puedes editar directamente en la tabla. Luego pulsa **Guardar cambios en Excel/DB**.")
        edited = st.data_editor(
            df_live,
            use_container_width=True,
            hide_index=True,
            num_rows="dynamic",
            key="tabla_editor_main",
        )

        c4, c5, c6 = st.columns([1,1,1])
        if c4.button("💾 Guardar cambios en Excel/DB", type="primary", use_container_width=True, key="btn_guardar_tabla"):
            ok, msg = guardar_inventario(edited)
            if ok:
                tag = "(Supabase)" if msg=="OK_SUPABASE" else "(Excel local)"
                st.success(f"✅ Cambios guardados {tag}.")
                st.rerun()
            else:
                st.error(f"❌ Error guardando: {msg}")

        if c5.button("🔄 Recargar desde origen", use_container_width=True, key="btn_recargar_tabla"):
            st.cache_data.clear()
            st.rerun()

        def _export_bytes(df_export: pd.DataFrame) -> bytes:
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as w:
                df_export.to_excel(w, index=False, sheet_name="inventario_cuentas")
            return buf.getvalue()

        st.download_button(
            "⬇️ Descargar inventario actual (.xlsx)",
            data=_export_bytes(load_data()),
            file_name="inventario_cuentas.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="dl_inventario_actual"
        )

    # ===== Cargar para otras pestañas =====
    df = load_data()
    df_view = df.copy()

    # ===== 📋 DASHBOARD =====
    with tab_dash:
        show_flash()
        if df.empty:
            st.info("No hay datos en el inventario.")
        else:
            total = len(df)
            radicadas = int((df.get("EstadoCanon", pd.Series(dtype=str))=="Radicada").sum())
            total_valor_fact = float(df.get("Valor Factura", pd.Series(dtype=float)).fillna(0).sum())
            total_valor_radic = float(df.get("Valor Radicado", pd.Series(dtype=float)).fillna(0).sum())
            avance = round((radicadas/total*100),2) if total else 0.0

            c1,c2,c3,c4 = st.columns(4)
            c1.metric("📦 Total facturas", total)
            c2.metric("💰 Total facturado", f"${total_valor_fact:,.0f}")
            c3.metric("🏦 Total radicado", f"${total_valor_radic:,.0f}")
            c4.metric("📊 Avance (radicadas)", f"{avance}%")

            # Torta por Estado
            if {"Estado","NumeroFactura"}.issubset(df.columns):
                g_estado = df.groupby("Estado", dropna=False)["NumeroFactura"].count().reset_index(name="Cantidad")
                fig_estado = px.pie(g_estado, names="Estado", values="Cantidad",
                                    hole=0.5, title="Distribución por Estado",
                                    color="Estado", color_discrete_map=ESTADO_COLORES)
                fig_estado.update_traces(textposition="inside", textinfo="percent+value")
                st.plotly_chart(fig_estado, use_container_width=True, key="dash_estado_donut")

            # EPS
            st.markdown("## 🏥 Por EPS")
            e1,e2 = st.columns(2)
            if {"EPS","NumeroFactura"}.issubset(df.columns):
                g_cnt = df.groupby("EPS", dropna=False)["NumeroFactura"].count().reset_index(name="Cantidad")
                g_cnt = g_cnt.sort_values("Cantidad", ascending=False)
                total_cnt = g_cnt["Cantidad"].sum() if not g_cnt.empty else 0
                g_cnt["%"] = (g_cnt["Cantidad"]/total_cnt*100).round(1) if total_cnt else 0
                with e1:
                    fig_funnel = px.funnel(g_cnt, x="Cantidad", y="EPS", title="Cantidad y % por EPS")
                    fig_funnel.update_traces(
                        text=g_cnt.apply(lambda r: f"{int(r['Cantidad'])} ({r['%']}%)", axis=1),
                        textposition="inside"
                    )
                    st.plotly_chart(fig_funnel, use_container_width=True, key="dash_eps_funnel")
                with e2:
                    df_rad = df[df.get("EstadoCanon","")=="Radicada"].copy()
                    g_val = df_rad.groupby("EPS", dropna=False)["Valor Radicado"].sum().reset_index(name="ValorRadicado")
                    g_val = g_val.sort_values("ValorRadicado", ascending=False)
                    fig_eps_val = px.bar(g_val, x="EPS", y="ValorRadicado",
                                         title="Valor radicado por EPS (solo Radicadas)",
                                         text_auto=".2s")
                    fig_eps_val.update_layout(xaxis={'categoryorder':'total descending'})
                    st.plotly_chart(fig_eps_val, use_container_width=True, key="dash_eps_val")

            # Vigencia
            st.markdown("## 📆 Por Vigencia")
            v1,v2 = st.columns(2)
            if {"Vigencia","Estado","NumeroFactura"}.issubset(df.columns):
                with v1:
                    fig_vig_val = px.bar(
                        df, x="Vigencia", y="Valor Factura", color="Estado",
                        title="Valor Factura por Vigencia (por Estado)",
                        barmode="group", color_discrete_map=ESTADO_COLORES, text_auto=".2s"
                    )
                    st.plotly_chart(fig_vig_val, use_container_width=True, key="dash_vig_valfact")
                with v2:
                    g_vig_cnt = df.groupby("Vigencia", dropna=False)["NumeroFactura"].count().reset_index(name="Cantidad")
                    fig_vig_donut = px.pie(g_vig_cnt, names="Vigencia", values="Cantidad",
                                           hole=0.4, title="Distribución de Facturas por Vigencia")
                    fig_vig_donut.update_traces(textposition="inside", textinfo="percent+value")
                    st.plotly_chart(fig_vig_donut, use_container_width=True, key="dash_vig_donut")

            st.divider()
            # Descargar dashboard a Excel
            def exportar_dashboard_excel(df):
                out = io.BytesIO()
                total = len(df)
                rad = int((df.get("EstadoCanon", pd.Series(dtype=str))=="Radicada").sum())
                total_fact = float(df["Valor Factura"].fillna(0).sum())
                total_radic = float(df["Valor Radicado"].fillna(0).sum())
                avance = round((rad/total*100),2) if total else 0.0
                with pd.ExcelWriter(out, engine="openpyxl") as w:
                    pd.DataFrame({
                        "Métrica":["Total facturas","Total facturado","Total radicado","% Avance (radicadas)"],
                        "Valor":[total,total_fact,total_radic,avance]
                    }).to_excel(w, index=False, sheet_name="Resumen")
                    if "EPS" in df.columns:
                        df.groupby("EPS", dropna=False).agg(
                            N_Facturas=("NumeroFactura","count"),
                            Valor_Facturado=("Valor Factura","sum"),
                            Valor_Radicado=("Valor Radicado","sum")
                        ).reset_index().to_excel(w, index=False, sheet_name="Por_EPS")
                    if "Vigencia" in df.columns:
                        df.groupby("Vigencia", dropna=False).agg(
                            N_Facturas=("NumeroFactura","count"),
                            Valor_Facturado=("Valor Factura","sum"),
                            Valor_Radicado=("Valor Radicado","sum")
                        ).reset_index().to_excel(w, index=False, sheet_name="Por_Vigencia")
                return out.getvalue()
            st.download_button("⬇️ Descargar Dashboard a Excel",
                               data=exportar_dashboard_excel(df),
                               file_name="dashboard_radicacion.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               use_container_width=True,
                               key="dl_dashboard")

    # ===== 🗂️ BANDEJAS =====
    with tab_bandejas:
        show_flash()
        st.subheader("🗂️ Bandejas por estado")
        if df.empty:
            st.info("No hay datos para mostrar.")
        else:
            c1,c2,c3,c4 = st.columns([1.4,1,1,1])
            q = c1.text_input("🔎 Buscar factura (contiene)", key="ban_q")
            eps_opts = ["Todos"] + sorted([e for e in df.get("EPS", pd.Series(dtype=str)).dropna().astype(str).unique().tolist() if e])
            eps_sel = c2.selectbox("EPS", eps_opts, index=0, key="ban_eps")
            vig_opts = ["Todos"] + sorted([str(int(v)) for v in pd.to_numeric(df.get("Vigencia", pd.Series(dtype=float)), errors="coerce").dropna().unique().tolist()])
            vig_sel = c3.selectbox("Vigencia", vig_opts, index=0, key="ban_vig")
            per_page = c4.selectbox("Filas por página", [50,100,200], index=1, key="ban_pp")

            def _filtrar(df_, estado, eps, vig, qtext):
                sub = df_[df_["Estado"]==estado].copy()
                if eps and eps!="Todos": sub = sub[sub["EPS"].astype(str)==eps]
                if vig and vig!="Todos": sub = sub[sub["Vigencia"].astype(str)==str(vig)]
                if qtext:
                    qn = str(qtext).strip().lower()
                    sub = sub[sub["NumeroFactura"].astype(str).str.lower().str.contains(qn)]
                return sub

            def _paginar(df_, page, per_page_):
                total = len(df_); total_pages = max((total-1)//per_page_+1,1)
                page = max(1, min(page, total_pages)); a=(page-1)*per_page_; b=a+per_page_
                return df_.iloc[a:b], total_pages, page

            estado_tabs = st.tabs(ESTADOS)
            for estado, tab in zip(ESTADOS, estado_tabs):
                with tab:
                    sub = _filtrar(df, estado, eps_sel, vig_sel, q)
                    sub = sub.sort_values(by=["FechaMovimiento","NumeroFactura"], ascending=[False, True])
                    key_page = f"page_{estado}"
                    if key_page not in st.session_state: st.session_state[key_page]=1
                    page_df, total_pages, current_page = _paginar(sub, st.session_state[key_page], per_page)
                    st.session_state[key_page]=current_page

                    cpa, cpb, cpc = st.columns([1,2,1])
                    prevb = cpa.button("⬅️ Anterior", disabled=(current_page<=1), key=f"prev_{estado}_{current_page}")
                    cpb.markdown(f"**Página {current_page} / {total_pages}** &nbsp; (**{len(sub)}** registros)")
                    nextb = cpc.button("Siguiente ➡️", disabled=(current_page>=total_pages), key=f"next_{estado}_{current_page}")
                    if prevb: st.session_state[key_page]=max(1,current_page-1); st.rerun()
                    if nextb: st.session_state[key_page]=min(total_pages,current_page+1); st.rerun()

                    st.divider()
                    sel_all = st.checkbox("Seleccionar todo (esta página)", key=f"selall_{estado}_{current_page}", value=False)
                    cols = ["ID","NumeroFactura","EPS","Vigencia","Valor Factura","Valor Radicado","FechaRadicacion","FechaMovimiento","Observaciones"]
                    view = page_df.reindex(columns=[c for c in cols if c in page_df.columns]).copy()
                    view.insert(0,"Seleccionar", sel_all)
                    edited = st.data_editor(view, hide_index=True, use_container_width=True, num_rows="fixed",
                                            column_config={"Seleccionar": st.column_config.CheckboxColumn("Seleccionar", default=False)},
                                            key=f"editor_{estado}_{current_page}")
                    try:
                        mask = edited["Seleccionar"].fillna(False).tolist()
                    except Exception:
                        mask = [False]*len(page_df)
                    seleccionados = [idx for pos, idx in enumerate(page_df.index.tolist()) if pos < len(mask) and mask[pos]]

                    st.divider()
                    c7,c8 = st.columns([2,1])
                    nuevo_estado = c7.selectbox("Mover seleccionadas a:", [e for e in ESTADOS if e != estado], key=f"move_{estado}_{current_page}")
                    mover = c8.button("Aplicar movimiento", type="primary", disabled=(len(seleccionados)==0), key=f"mover_{estado}_{current_page}")
                    if mover:
                        ahora = pd.Timestamp(datetime.now())
                        for idx in seleccionados:
                            df.at[idx, "Estado"] = nuevo_estado
                            df.at[idx, "FechaMovimiento"] = ahora
                        ok, msg = guardar_inventario(df)
                        if ok:
                            tag = "(Supabase)" if msg=="OK_SUPABASE" else "(Excel local)"
                            flash_success(f"✅ Cambios guardados — {len(seleccionados)} facturas movidas a {nuevo_estado} {tag}")
                            st.rerun()
                        else:
                            st.error(f"❌ Error guardando: {msg}")

    # ===== 📝 GESTIÓN =====
    with tab_gestion:
        show_flash()
        st.subheader("📝 Gestión")
        if df.empty:
            st.info("Ingresa o busca una factura para editar/crear.")
        else:
            c1,c2 = st.columns([2,1])
            q_factura = c1.text_input("🔎 Buscar por Número de factura", key="buscar_factura_input")
            buscar = c2.button("Buscar / Cargar", type="primary", key="btn_buscar_gestion")
            if buscar and q_factura.strip():
                st.session_state["factura_activa"] = q_factura.strip()
            numero_activo = st.session_state.get("factura_activa","")

            if not numero_activo:
                st.info("Ingresa un número de factura y presiona **Buscar / Cargar** para editar o crear.")
            else:
                mask = df.get("NumeroFactura", pd.Series(dtype=str)).astype(str).str.strip() == str(numero_activo).strip()
                existe = bool(mask.any())
                idx = df[mask].index[0] if existe else None
                fila = df.loc[idx] if existe else pd.Series(dtype=object)

                def getv(s, k, default=None):
                    v = s.get(k, default) if isinstance(s, pd.Series) else default
                    return v if not (pd.isna(v) if hasattr(pd, "isna") else v is None) else default

                def_val = {
                    "ID": getv(fila,"ID",""),
                    "NumeroFactura": str(getv(fila,"NumeroFactura", numero_activo) or numero_activo),
                    "EPS": str(getv(fila,"EPS","") or ""),
                    "Vigencia": getv(fila,"Vigencia",""),
                    "Estado": str(getv(fila,"Estado","Pendiente") or "Pendiente"),
                    "FechaRadicacion": getv(fila,"FechaRadicacion", pd.NaT),
                    "FechaMovimiento": getv(fila,"FechaMovimiento", pd.NaT),
                    "Observaciones": str(getv(fila,"Observaciones","") or ""),
                    "Mes": str(getv(fila,"Mes","") or ""),
                    # Extras
                    "Fecha factura": getv(fila,"Fecha factura", pd.NaT),
                    "Documento": str(getv(fila,"Documento","") or ""),
                    "Paciente": str(getv(fila,"Paciente","") or ""),
                    "No Radicado": str(getv(fila,"No Radicado","") or ""),
                    "Valor Factura": getv(fila,"Valor Factura", pd.NA),
                    "Valor Radicado": getv(fila,"Valor Radicado", pd.NA),
                }

                # Top controls
                ctop1, ctop2, ctop3 = st.columns(3)
                ctop1.text_input("ID (automático)", value=def_val["ID"], disabled=True, key="gestion_id_display")
                est_val = ctop2.selectbox("Estado", options=ESTADOS,
                                          index=ESTADOS.index(def_val["Estado"]) if def_val["Estado"] in ESTADOS else 0,
                                          key="estado_val")
                frad_disabled = (est_val != "Radicada")
                frad_val = ctop3.date_input("Fecha de Radicación",
                                            value=(def_val["FechaRadicacion"].date() if pd.notna(def_val["FechaRadicacion"]) else date.today()),
                                            disabled=frad_disabled, key="frad_val")

                with st.form("form_factura", clear_on_submit=False):
                    f1, f2 = st.columns(2)
                    # Básicos
                    num_val = f1.text_input("Número de factura", value=def_val["NumeroFactura"], key="gestion_num_factura")
                    eps_val = f1.text_input("EPS", value=def_val["EPS"], key="gestion_eps")

                    # Valores y extras izquierda
                    valor_fact = f1.text_input("Valor Factura", value=(str(def_val["Valor Factura"]) if pd.notna(def_val["Valor Factura"]) else ""), key="gestion_valor_factura")
                    valor_radic = f1.text_input("Valor Radicado", value=(str(def_val["Valor Radicado"]) if pd.notna(def_val["Valor Radicado"]) else ""), key="gestion_valor_radicado")

                    fecha_fact = f1.date_input("Fecha factura",
                                               value=(def_val["Fecha factura"].date() if isinstance(def_val["Fecha factura"], pd.Timestamp) and pd.notna(def_val["Fecha factura"]) else date.today()),
                                               key="gestion_fecha_factura")

                    # Derecha
                    vig_val = f2.text_input("Vigencia", value=str(def_val["Vigencia"]), key="gestion_vigencia")
                    obs_val = f2.text_area("Observaciones", value=def_val["Observaciones"], height=100, key="gestion_obs")
                    doc_val = f2.text_input("Documento", value=str(def_val["Documento"]), key="gestion_documento")
                    pac_val = f2.text_input("Paciente", value=str(def_val["Paciente"]), key="gestion_paciente")
                    no_radicado = f2.text_input("No Radicado", value=str(def_val["No Radicado"]), key="gestion_no_radicado")

                    submit = st.form_submit_button("💾 Guardar cambios", type="primary", use_container_width=True, key="btn_form_guardar")

                if submit:
                    ahora = pd.Timestamp(datetime.now())
                    mask2 = df.get("NumeroFactura", pd.Series(dtype=str)).astype(str).str.strip() == str(num_val).strip()
                    existe2 = bool(mask2.any()); idx2 = df[mask2].index[0] if existe2 else None

                    estado_anterior = (str(df.loc[idx2,"Estado"]) if existe2 and "Estado" in df.columns else "").strip()
                    estado_actual = st.session_state.get("estado_val", estado_anterior or "Pendiente")

                    frad_widget = st.session_state.get("frad_val", def_val["FechaRadicacion"] if pd.notna(def_val["FechaRadicacion"]) else date.today())
                    frad_ts = pd.to_datetime(frad_widget) if estado_actual == "Radicada" else (pd.to_datetime(df.loc[idx2,"FechaRadicacion"]) if existe2 and "FechaRadicacion" in df.columns else pd.NaT)

                    mes_nuevo = (df.loc[idx2,"Mes"] if existe2 and "Mes" in df.columns else "")
                    if pd.notna(frad_ts): mes_nuevo = MES_NOMBRE[int(frad_ts.month)]

                    estado_cambio = (estado_actual != estado_anterior) or (not existe2)
                    fecha_mov = (ahora if estado_cambio else (pd.to_datetime(df.loc[idx2,"FechaMovimiento"]) if existe2 and "FechaMovimiento" in df.columns else pd.NaT))

                    # ID
                    if existe2 and "ID" in df.columns and pd.notna(df.loc[idx2,"ID"]) and str(df.loc[idx2,"ID"]).strip():
                        new_id = str(df.loc[idx2,"ID"]).strip()
                    else:
                        try:
                            nums = pd.to_numeric(df.get("ID", pd.Series(dtype=str)).astype(str).str.extract(r"(\d+)$")[0], errors="coerce")
                            nextn = int(nums.max()) + 1 if nums.notna().any() else 1
                        except Exception:
                            nextn = 1
                        new_id = f"CHIA-{nextn:04d}"

                    # Normalizar valores monetarios
                    v_fact = _parse_currency(valor_fact)
                    v_radic = _parse_currency(valor_radic)

                    registro = {
                        "ID": new_id,
                        "NumeroFactura": str(num_val).strip(),
                        "EPS": str(eps_val).strip(),
                        "Vigencia": int(vig_val) if str(vig_val).isdigit() else vig_val,
                        "Estado": estado_actual,
                        "FechaRadicacion": frad_ts,
                        "FechaMovimiento": fecha_mov,
                        "Observaciones": str(obs_val).strip(),
                        "Mes": mes_nuevo,
                        "Fecha factura": pd.to_datetime(fecha_fact) if fecha_fact else pd.NaT,
                        "Documento": str(doc_val).strip() if doc_val is not None else "",
                        "Paciente": str(pac_val).strip() if pac_val is not None else "",
                        "No Radicado": str(no_radicado).strip() if no_radicado is not None else "",
                        "Valor Factura": v_fact,
                        "Valor Radicado": v_radic,
                    }

                    if existe2:
                        for k,v in registro.items(): df.at[idx2, k] = v
                    else:
                        df = pd.concat([df, pd.DataFrame([registro])], ignore_index=True)

                    ok, msg = guardar_inventario(df, factura_verificar=registro["NumeroFactura"])
                    if ok:
                        tag = "(Supabase)" if msg=="OK_SUPABASE" else "(Excel local)"
                        flash_success(f"✅ Cambios guardados — Factura {registro['NumeroFactura']} {tag}")
                        st.session_state["factura_activa"] = ""
                        st.rerun()
                    else:
                        st.error(f"❌ No pude confirmar el guardado: {msg}")

    # ===== 📑 REPORTES =====
    with tab_reportes:
        show_flash()
        st.subheader("📑 Reportes")
        if df.empty:
            st.info("No hay datos para reportar.")
        else:
            tipo = st.selectbox("Elige el reporte", ["Por EPS", "Por Vigencia", "Por Estado"], index=0, key="rep_tipo")

            def agg_eps(data: pd.DataFrame) -> pd.DataFrame:
                g = data.groupby("EPS", dropna=False).agg(
                    Cuentas=("NumeroFactura","count"),
                    Valor_Facturado=("Valor Factura","sum"),
                    Valor_Radicado=("Valor Radicado","sum"),
                    Radicadas=("Estado", lambda x: (x=="Radicada").sum())
                ).reset_index().fillna(0)
                g["% Avance"] = (g["Radicadas"] / g["Cuentas"].where(g["Cuentas"]!=0, pd.NA) * 100).fillna(0).round(2)
                return g.sort_values("Cuentas", ascending=False)

            def agg_vig(data: pd.DataFrame) -> pd.DataFrame:
                g = data.groupby("Vigencia", dropna=False).agg(
                    Cuentas=("NumeroFactura","count"),
                    Valor_Facturado=("Valor Factura","sum"),
                    Valor_Radicado=("Valor Radicado","sum"),
                    Radicadas=("Estado", lambda x: (x=="Radicada").sum())
                ).reset_index().fillna(0)
                g["% Avance"] = (g["Radicadas"] / g["Cuentas"].where(g["Cuentas"]!=0, pd.NA) * 100).fillna(0).round(2)
                return g.sort_values("Cuentas", ascending=False)

            def agg_estado(data: pd.DataFrame) -> pd.DataFrame:
                g = data.groupby("Estado", dropna=False).agg(
                    Cuentas=("NumeroFactura","count"),
                    Valor_Facturado=("Valor Factura","sum"),
                    Valor_Radicado=("Valor Radicado","sum")
                ).reset_index().fillna(0)
                return g.sort_values("Cuentas", ascending=False)

            def exportar_excel(df_tab: pd.DataFrame, sheet_name: str) -> bytes:
                out = io.BytesIO()
                with pd.ExcelWriter(out, engine="openpyxl") as w:
                    df_tab.to_excel(w, index=False, sheet_name=sheet_name)
                return out.getvalue()

            if tipo == "Por EPS":
                tabla = agg_eps(df)
                st.markdown("### 🏥 Tabla por EPS")
                st.dataframe(tabla, use_container_width=True, key="tabla_por_eps")

                c1, c2 = st.columns(2)
                total_cnt = int(tabla["Cuentas"].sum()) if not tabla.empty else 0
                tabla_plot = tabla.copy()
                tabla_plot["%"] = (tabla_plot["Cuentas"]/total_cnt*100).round(1) if total_cnt else 0
                with c1:
                    fig_funnel = px.funnel(tabla_plot, x="Cuentas", y="EPS", title="Cantidad y % por EPS")
                    fig_funnel.update_traces(
                        text=tabla_plot.apply(lambda r: f"{int(r['Cuentas'])} ({r['%']}%)", axis=1),
                        textposition="inside"
                    )
                    st.plotly_chart(fig_funnel, use_container_width=True, key="rep_eps_funnel")
                with c2:
                    df_rad = df[df.get("EstadoCanon","")=="Radicada"].copy()
                    g_val = df_rad.groupby("EPS", dropna=False)["Valor Radicado"].sum().reset_index(name="Valor Radicado")
                    g_val = g_val.sort_values("Valor Radicado", ascending=False)
                    fig_val = px.bar(g_val, x="EPS", y="Valor Radicado", title="Valor radicado por EPS", text_auto=".2s")
                    fig_val.update_layout(xaxis={'categoryorder':'total descending'})
                    st.plotly_chart(fig_val, use_container_width=True, key="rep_eps_val")

                st.download_button("⬇️ Descargar reporte EPS (Excel)",
                                   data=exportar_excel(tabla, "Por_EPS"),
                                   file_name="reporte_por_eps.xlsx",
                                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                   use_container_width=True, key="dl_rep_eps")

            elif tipo == "Por Vigencia":
                tabla = agg_vig(df)
                st.markdown("### 📆 Tabla por Vigencia")
                st.dataframe(tabla, use_container_width=True, key="tabla_por_vigencia")

                c1, c2 = st.columns(2)
                with c1:
                    fig_vig_val = px.bar(df, x="Vigencia", y="Valor Factura", color="Estado",
                                         title="Valor Factura por Vigencia (por Estado)",
                                         barmode="group", color_discrete_map=ESTADO_COLORES, text_auto=".2s")
                    st.plotly_chart(fig_vig_val, use_container_width=True, key="rep_vig_valfact")
                with c2:
                    g_cnt = df.groupby("Vigencia", dropna=False)["NumeroFactura"].count().reset_index(name="Cuentas")
                    fig_vig_donut = px.pie(g_cnt, names="Vigencia", values="Cuentas",
                                           hole=0.45, title="Distribución de Cuentas por Vigencia")
                    fig_vig_donut.update_traces(textposition="inside", textinfo="percent+value")
                    st.plotly_chart(fig_vig_donut, use_container_width=True, key="rep_vig_donut")

                st.download_button("⬇️ Descargar reporte Vigencia (Excel)",
                                   data=exportar_excel(tabla, "Por_Vigencia"),
                                   file_name="reporte_por_vigencia.xlsx",
                                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                   use_container_width=True, key="dl_rep_vig")

            else:
                tabla = agg_estado(df)
                st.markdown("### 🧩 Tabla por Estado")
                st.dataframe(tabla, use_container_width=True, key="tabla_por_estado")

                c1, c2 = st.columns(2)
                with c1:
                    fig_estado = px.pie(tabla, names="Estado", values="Cuentas",
                                        hole=0.5, title="Distribución por Estado",
                                        color="Estado", color_discrete_map=ESTADO_COLORES)
                    fig_estado.update_traces(textposition="inside", textinfo="percent+value")
                    st.plotly_chart(fig_estado, use_container_width=True, key="rep_estado_pie")
                with c2:
                    fig_bar = px.bar(tabla, x="Estado", y="Cuentas",
                                     title="Cuentas por Estado", text_auto=True,
                                     color="Estado", color_discrete_map=ESTADO_COLORES)
                    st.plotly_chart(fig_bar, use_container_width=True, key="rep_estado_bar")

                st.download_button("⬇️ Descargar reporte Estado (Excel)",
                                   data=exportar_excel(tabla, "Por_Estado"),
                                   file_name="reporte_por_estado.xlsx",
                                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                   use_container_width=True, key="dl_rep_estado")

    # ===== 📈 AVANCE =====
    with tab_avance:
        show_flash()
        st.subheader("📈 Avance (Real vs Proyectado — Acumulado)")
        base = pd.DataFrame({
            "Mes": ["Agosto 2025","Septiembre 2025","Octubre 2025","Noviembre 2025"],
            "Cuentas estimadas": [515, 1489, 1797, 1738],
        })
        base["Cuentas estimadas acumuladas"] = base["Cuentas estimadas"].cumsum()
        total_meta = int(base["Cuentas estimadas"].sum())
        base["% proyectado acumulado"] = (base["Cuentas estimadas acumuladas"]/total_meta*100).round(2) if total_meta else 0.0

        def _etq_mes(row):
            fr = row.get("FechaRadicacion")
            if pd.notna(fr):
                fr = pd.to_datetime(fr, errors="coerce")
                if pd.notna(fr): return f"{MES_NOMBRE[int(fr.month)]} {int(fr.year)}"
            m = str(row.get("Mes","")).strip()
            if re.search(r"\b20\d{2}\b", m): return m
            vig = str(row.get("Vigencia","")).strip()
            if m and vig.isdigit(): return f"{m} {vig}"
            return m or "Sin Mes"

        df_v = df.copy()
        if "EstadoCanon" not in df_v.columns and "Estado" in df_v.columns:
            df_v["EstadoCanon"] = df_v["Estado"].astype(str).str.strip().str.lower().map({
                "radicada":"Radicada","radicadas":"Radicada",
                "pendiente":"Pendiente","auditada":"Auditada","subsanada":"Subsanada"
            }).fillna(df_v["Estado"])

        df_rad = df_v[df_v["EstadoCanon"]=="Radicada"].copy()
        if df_rad.empty:
            st.info("Aún no hay cuentas radicadas para comparar.")
        else:
            df_rad["MesClave"] = df_rad.apply(_etq_mes, axis=1)
            reales = df_rad.groupby("MesClave")["NumeroFactura"].nunique().reset_index(name="Cuentas reales")
            comp = base.merge(reales, left_on="Mes", right_on="MesClave", how="left").drop(columns=["MesClave"]).fillna(0)
            comp["Cuentas reales"] = comp["Cuentas reales"].astype(int)
            comp["Cuentas reales acumuladas"] = comp["Cuentas reales"].cumsum()
            comp["% real acumulado"] = (comp["Cuentas reales acumuladas"]/total_meta*100).round(2) if total_meta else 0.0
            comp["Diferencia % (Real - Proy)"] = (comp["% real acumulado"] - base["% proyectado acumulado"]).round(2)

            st.dataframe(comp, use_container_width=True, key="avance_tabla")

            fig = go.Figure()
            fig.add_trace(go.Scatter(x=base["Mes"], y=base["% proyectado acumulado"], mode='lines+markers', name='Proyectado'))
            fig.add_trace(go.Scatter(x=comp["Mes"], y=comp["% real acumulado"], mode='lines+markers', name='Real'))
            fig.update_layout(title="Avance acumulado (%) — Real vs Proyectado", yaxis_title="% acumulado", xaxis_title="Mes")
            st.plotly_chart(fig, use_container_width=True, key="avance_lineas")

            k1,k2,k3 = st.columns(3)
            k1.metric("Meta total (cuentas)", f"{total_meta:,}")
            k2.metric("Reales acumuladas", f"{int(comp['Cuentas reales'].sum()):,}")
            k3.metric("Avance total vs meta", f"{(comp['Cuentas reales'].sum()/total_meta*100 if total_meta else 0):.1f}%")

# ====== Arranque ======
if st.session_state.get("autenticado", False):
    main_app()
else:
    # Si no quieres login, descomenta la línea siguiente para omitirlo:
    # st.session_state["autenticado"] = True; main_app()
    login()











