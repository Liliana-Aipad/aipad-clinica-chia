# app_streamlit.py
# -*- coding: utf-8 -*-
APP_VERSION = "2025-08-09 09:15"

import streamlit as st
st.set_page_config(layout="wide", page_title="AIPAD • Control de Radicación")

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, date
import io, os, re, base64, json, requests, time, tempfile
import streamlit.components.v1 as components

# ===== Rutas absolutas =====
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INVENTARIO_FILE = os.path.join(BASE_DIR, "inventario_cuentas.xlsx")
USUARIOS_FILE  = os.path.join(BASE_DIR, "usuarios.xlsx")
LOCK_FILE      = os.path.join(BASE_DIR, ".inventario.lock")

# ===== Visual =====
ESTADO_COLORES = {"Radicada":"green","Pendiente":"red","Auditada":"orange","Subsanada":"blue"}
ESTADOS = ["Pendiente","Auditada","Subsanada","Radicada"]
MES_NOMBRE = {1:"Enero",2:"Febrero",3:"Marzo",4:"Abril",5:"Mayo",6:"Junio",
              7:"Julio",8:"Agosto",9:"Septiembre",10:"Octubre",11:"Noviembre",12:"Diciembre"}

# ===== UI helpers =====
def flash_success(msg: str):
    st.session_state["_flash_ok"] = msg

def show_flash():
    msg = st.session_state.pop("_flash_ok", None)
    if msg:
        st.success(msg)

# ===== GitHub (opcional) =====
def github_enabled() -> bool:
    try:
        s = st.secrets.get("github", None)
        return isinstance(s, dict) and all(k in s for k in ("token","owner","repo"))
    except Exception:
        return False

def _gh_headers():
    tok = st.secrets["github"]["token"]
    return {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"}

def _gh_repo_info():
    s = st.secrets["github"]
    return s["owner"], s["repo"], s.get("branch","main"), s.get("file_path","inventario_cuentas.xlsx")

def gh_get_file_sha():
    owner, repo, branch, path = _gh_repo_info()
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={branch}"
    r = requests.get(url, headers=_gh_headers(), timeout=20)
    if r.status_code == 200:
        return r.json()["sha"]
    elif r.status_code == 404:
        return None
    else:
        raise RuntimeError(f"GitHub GET error {r.status_code}: {r.text}")

def gh_put_file(content_bytes: bytes, message: str, sha: str|None):
    owner, repo, branch, path = _gh_repo_info()
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
    data = {
        "message": message,
        "content": base64.b64encode(content_bytes).decode("utf-8"),
        "branch": branch,
    }
    if sha:
        data["sha"] = sha
    r = requests.put(url, headers=_gh_headers(), data=json.dumps(data), timeout=45)
    if r.status_code not in (200,201):
        raise RuntimeError(f"GitHub PUT error {r.status_code}: {r.text}")
    return r.json()

# ===== Data =====
@st.cache_data
def load_data():
    if not os.path.exists(INVENTARIO_FILE):
        cols = ["ID","NumeroFactura","Valor","EPS","Vigencia","Estado",
                "Mes","FechaRadicacion","FechaMovimiento","Observaciones"]
        return pd.DataFrame(columns=cols)
    df = pd.read_excel(INVENTARIO_FILE)
    for c in ["FechaRadicacion","FechaMovimiento"]:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce")
    if "Valor" in df.columns:
        df["Valor"] = pd.to_numeric(df["Valor"], errors="coerce")
    if "Vigencia" in df.columns:
        df["Vigencia"] = pd.to_numeric(df["Vigencia"], errors="coerce")
    return df

def guardar_inventario(df: pd.DataFrame, factura_verificar: str | None = None) -> tuple[bool, str]:
    """Guarda local (lock + atómico), verifica y sincroniza a GitHub si está configurado."""
    # ---- Lock simple ----
    t0 = time.time()
    while True:
        try:
            fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd); break
        except FileExistsError:
            if time.time() - t0 > 10:
                return False, "Inventario en uso por otro usuario (timeout)"
            time.sleep(0.3)
    try:
        # ---- Escritura atómica local ----
        dir_dest = os.path.dirname(INVENTARIO_FILE) or "."
        with tempfile.NamedTemporaryFile(suffix=".xlsx", dir=dir_dest, delete=False) as tf:
            tmp_path = tf.name
        try:
            with pd.ExcelWriter(tmp_path, engine="openpyxl") as w:
                df.to_excel(w, index=False)
            os.replace(tmp_path, INVENTARIO_FILE)
        finally:
            try: os.remove(tmp_path)
            except: pass

        st.cache_data.clear()

        # ---- Verificar lectura ----
        try:
            df_disk = pd.read_excel(INVENTARIO_FILE)
        except Exception as e:
            return False, f"Guardó local pero no pude verificar: {e}"
        if factura_verificar:
            ok_row = df_disk["NumeroFactura"].astype(str).str.strip().eq(str(factura_verificar).strip()).any()
            if not ok_row:
                return False, f"Guardó local, pero la factura {factura_verificar} no aparece al releer"

        # ---- GitHub opcional ----
        if github_enabled():
            try:
                with open(INVENTARIO_FILE, "rb") as f:
                    content_bytes = f.read()
                tries = 0
                while tries < 3:
                    tries += 1
                    try:
                        sha = gh_get_file_sha()
                        gh_put_file(content_bytes, message=f"Update inventario (Factura {factura_verificar or ''})", sha=sha)
                        return True, "OK_GITHUB"
                    except RuntimeError as e:
                        if "sha" in str(e).lower() or "409" in str(e):
                            time.sleep(0.8); continue
                        return True, f"OK_LOCAL_GH_FAIL: {e}"
            except Exception as e:
                return True, f"OK_LOCAL_GH_FAIL: {e}"
        # si no hay secrets:
        return True, "OK_LOCAL"
    finally:
        try: os.remove(LOCK_FILE)
        except FileNotFoundError: pass

# ===== Auth (login con form y keys únicas) =====
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
            st.sidebar.error(f"Error cargando usuarios: {e}")

# ===== App =====
def main_app():
    st.caption(f"🆔 Versión: {APP_VERSION}")
    st.title("📊 AIPAD • Control de Radicación")
    if "usuario" in st.session_state and "rol" in st.session_state:
        st.markdown(f"👤 Usuario: `{st.session_state['usuario']}`  |  🔐 Rol: `{st.session_state['rol']}`")

    df = load_data()
    # Normalización de estados (solo para vista)
    df_view = df.copy()
    if "Estado" in df_view.columns:
        norm = df_view["Estado"].astype(str).str.strip().str.lower()
        mapa = {"radicada":"Radicada","radicadas":"Radicada","pendiente":"Pendiente",
                "auditada":"Auditada","auditadas":"Auditada","subsanada":"Subsanada","subsanadas":"Subsanada"}
        df_view["EstadoCanon"] = norm.map(mapa).fillna(df_view["Estado"])
    else:
        df_view["EstadoCanon"] = ""

    tab_dash, tab_bandejas, tab_gestion, tab_reportes, tab_avance = st.tabs(
        ["📋 Dashboard","🗂️ Bandejas","📝 Gestión","📑 Reportes","📈 Avance"]
    )

    # ===== Dashboard =====
    with tab_dash:
        show_flash()
        if df.empty:
            st.info("No hay datos en el inventario.")
        else:
            total = len(df)
            radicadas = int((df_view["EstadoCanon"]=="Radicada").sum())
            total_valor = float(df.get("Valor", pd.Series(dtype=float)).fillna(0).sum())
            avance = round((radicadas/total*100),2) if total else 0.0

            c1,c2,c3 = st.columns(3)
            c1.metric("📦 Total facturas", total)
            c2.metric("💰 Valor total", f"${total_valor:,.0f}")
            c3.metric("📊 Avance (radicadas)", f"{avance}%")

            # ---- Torta por Estado (como en tu captura) ----
            if {"Estado","NumeroFactura"}.issubset(df.columns):
                g_estado = df.groupby("Estado", dropna=False)["NumeroFactura"] \
                             .count().reset_index(name="Cantidad")
                fig_estado = px.pie(
                    g_estado, names="Estado", values="Cantidad",
                    hole=0.5, title="Distribución por Estado",
                    color="Estado", color_discrete_map=ESTADO_COLORES
                )
                fig_estado.update_traces(textposition="inside", textinfo="percent+value")
                st.plotly_chart(fig_estado, use_container_width=True)

            # ---- EPS (dos gráficos en una fila) ----
            st.markdown("## 🏥 Por EPS")
            e1,e2 = st.columns(2)
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

            # ---- Vigencia (dos gráficos en una fila) ----
            st.markdown("## 📆 Por Vigencia")
            v1,v2 = st.columns(2)
            if {"Vigencia","Estado","Valor","NumeroFactura"}.issubset(df.columns):
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

            st.divider()
            # Descarga Excel del dashboard
            def exportar_dashboard_excel(df, df_view):
                out = io.BytesIO()
                total = len(df)
                rad = int((df_view["EstadoCanon"]=="Radicada").sum())
                total_val = float(df.get("Valor", pd.Series(dtype=float)).fillna(0).sum())
                avance = round((rad/total*100),2) if total else 0.0
                with pd.ExcelWriter(out, engine="openpyxl") as w:
                    pd.DataFrame({"Métrica":["Total facturas","Valor total","% Avance (radicadas)"],
                                  "Valor":[total,total_val,avance]}).to_excel(w, index=False, sheet_name="Resumen")
                    if "EPS" in df.columns:
                        df.groupby("EPS", dropna=False).agg(
                            N_Facturas=("NumeroFactura","count"),
                            Valor_Total=("Valor","sum")
                        ).reset_index().to_excel(w, index=False, sheet_name="Por_EPS")
                    if "Vigencia" in df.columns:
                        df.groupby("Vigencia", dropna=False).agg(
                            N_Facturas=("NumeroFactura","count"),
                            Valor_Total=("Valor","sum")
                        ).reset_index().to_excel(w, index=False, sheet_name="Por_Vigencia")
                return out.getvalue()
            st.download_button("⬇️ Descargar Dashboard a Excel",
                               data=exportar_dashboard_excel(df, df_view),
                               file_name="dashboard_radicacion.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               use_container_width=True)

            with st.expander("🧪 Diagnóstico de inventario"):
                st.code(f"Inventario en: {INVENTARIO_FILE}", language="bash")
                st.caption(f"🛠️ GitHub configurado: {'Sí' if github_enabled() else 'No'}")
                c1, c2 = st.columns(2)
                if c1.button("🔄 Forzar recarga desde disco"):
                    st.cache_data.clear(); st.rerun()
                if github_enabled() and c2.button("Probar conexión a GitHub"):
                    try:
                        sha = gh_get_file_sha()
                        st.success(f"Conexión OK. SHA actual: {sha or 'nuevo archivo'}")
                    except Exception as e:
                        st.error(f"Fallo conexión GitHub: {e}")
                qn = st.text_input("🔍 Ver factura por número:")
                if qn:
                    try:
                        ddf = pd.read_excel(INVENTARIO_FILE)
                        st.dataframe(ddf[ddf["NumeroFactura"].astype(str).str.strip()==qn.strip()].tail(1),
                                     use_container_width=True)
                    except Exception as e:
                        st.error(f"No pude leer el archivo: {e}")

    # ===== Bandejas =====
    with tab_bandejas:
        show_flash()
        st.subheader("🗂️ Bandejas por estado")
        if df.empty:
            st.info("No hay datos para mostrar.")
        else:
            c1,c2,c3,c4 = st.columns([1.4,1,1,1])
            q = c1.text_input("🔎 Buscar factura (contiene)")
            eps_opts = ["Todos"] + sorted([e for e in df.get("EPS", pd.Series(dtype=str)).dropna().astype(str).unique().tolist() if e])
            eps_sel = c2.selectbox("EPS", eps_opts, index=0)
            vig_opts = ["Todos"] + sorted([str(int(v)) for v in pd.to_numeric(df.get("Vigencia", pd.Series(dtype=float)), errors="coerce").dropna().unique().tolist()])
            vig_sel = c3.selectbox("Vigencia", vig_opts, index=0)
            per_page = c4.selectbox("Filas por página", [50,100,200], index=1)

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
                    prevb = cpa.button("⬅️ Anterior", disabled=(current_page<=1), key=f"prev_{estado}")
                    cpb.markdown(f"**Página {current_page} / {total_pages}** &nbsp; (**{len(sub)}** registros)")
                    nextb = cpc.button("Siguiente ➡️", disabled=(current_page>=total_pages), key=f"next_{estado}")
                    if prevb: st.session_state[key_page]=max(1,current_page-1); st.rerun()
                    if nextb: st.session_state[key_page]=min(total_pages,current_page+1); st.rerun()

                    st.divider()
                    sel_all = st.checkbox("Seleccionar todo (esta página)", key=f"selall_{estado}_{current_page}", value=False)
                    cols = ["ID","NumeroFactura","EPS","Vigencia","Valor","FechaRadicacion","FechaMovimiento","Observaciones"]
                    view = page_df[cols].copy()
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
                    c1,c2 = st.columns([2,1])
                    nuevo_estado = c1.selectbox("Mover seleccionadas a:", [e for e in ESTADOS if e != estado])
                    mover = c2.button("Aplicar movimiento", type="primary", disabled=(len(seleccionados)==0), key=f"mover_{estado}")
                    if mover:
                        ahora = pd.Timestamp(datetime.now())
                        for idx in seleccionados:
                            df.at[idx, "Estado"] = nuevo_estado
                            df.at[idx, "FechaMovimiento"] = ahora
                        ok, msg = guardar_inventario(df)
                        if ok:
                            tag = "(sincronizado con GitHub)" if msg=="OK_GITHUB" else "(guardado local)"
                            if str(msg).startswith("OK_LOCAL_GH_FAIL"): tag = "(guardado local; GitHub no disponible)"
                            flash_success(f"✅ Cambios guardados — {len(seleccionados)} facturas movidas a {nuevo_estado} {tag}")
                            st.rerun()
                        else:
                            st.error(f"❌ Error guardando: {msg}")

    # ===== Gestión =====
    with tab_gestion:
        show_flash()
        st.subheader("📝 Gestión")
        if df.empty:
            st.info("Ingresa o busca una factura para editar/crear.")
        else:
            c1,c2 = st.columns([2,1])
            q_factura = c1.text_input("🔎 Buscar por Número de factura", key="buscar_factura_input")
            buscar = c2.button("Buscar / Cargar", type="primary")
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
                    "Valor": float(getv(fila,"Valor",0) or 0.0),
                    "EPS": str(getv(fila,"EPS","") or ""),
                    "Vigencia": getv(fila,"Vigencia", ""),
                    "Estado": str(getv(fila,"Estado","Pendiente") or "Pendiente"),
                    "FechaRadicacion": getv(fila,"FechaRadicacion", pd.NaT),
                    "FechaMovimiento": getv(fila,"FechaMovimiento", pd.NaT),
                    "Observaciones": str(getv(fila,"Observaciones","") or ""),
                    "Mes": str(getv(fila,"Mes","") or ""),
                }

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
                    num_val = f1.text_input("Número de factura", value=def_val["NumeroFactura"], key="gestion_num_factura")
                    valor_val = f1.number_input("Valor", min_value=0.0, step=1000.0, value=float(def_val["Valor"]), key="gestion_valor")
                    eps_val = f1.text_input("EPS", value=def_val["EPS"], key="gestion_eps")

                    vig_val = f2.text_input("Vigencia", value=str(def_val["Vigencia"]), key="gestion_vigencia")
                    obs_val = f2.text_area("Observaciones", value=def_val["Observaciones"], height=100, key="gestion_obs")

                    submit = st.form_submit_button("💾 Guardar cambios", type="primary", use_container_width=True)

                if submit:
                    ahora = pd.Timestamp(datetime.now())
                    mask2 = df.get("NumeroFactura", pd.Series(dtype=str)).astype(str).str.strip() == str(num_val).strip()
                    existe2 = bool(mask2.any()); idx2 = df[mask2].index[0] if existe2 else None

                    estado_anterior = (str(df.loc[idx2,"Estado"]) if existe2 and "Estado" in df.columns else "").strip()
                    estado_actual = st.session_state.get("estado_val", estado_anterior or "Pendiente")

                    frad_widget = st.session_state.get("frad_val", def_val["FechaRadicacion"] if pd.notna(def_val["FechaRadicacion"]) else date.today())
                    frad_ts = pd.to_datetime(frad_widget) if estado_actual == "Radicada" else (pd.to_datetime(df.loc[idx2,"FechaRadicacion"]) if existe2 and "FechaRadicacion" in df.columns else pd.NaT)

                    mes_nuevo = (df.loc[idx2,"Mes"] if existe2 and "Mes" in df.columns else "")
                    if pd.notna(frad_ts):
                        mes_nuevo = MES_NOMBRE[int(frad_ts.month)]

                    estado_cambio = (estado_actual != estado_anterior) or (not existe2)
                    fecha_mov = (ahora if estado_cambio else (pd.to_datetime(df.loc[idx2,"FechaMovimiento"]) if existe2 and "FechaMovimiento" in df.columns else pd.NaT))

                    if existe2 and "ID" in df.columns and pd.notna(df.loc[idx2,"ID"]) and str(df.loc[idx2,"ID"]).strip():
                        new_id = str(df.loc[idx2,"ID"]).strip()
                    else:
                        try:
                            nums = pd.to_numeric(df.get("ID", pd.Series(dtype=str)).astype(str).str.extract(r"(\d+)$")[0], errors="coerce")
                            nextn = int(nums.max()) + 1 if nums.notna().any() else 1
                        except Exception:
                            nextn = 1
                        new_id = f"CHIA-{nextn:04d}"

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

                    if existe2:
                        for k,v in registro.items():
                            df.at[idx2, k] = v
                    else:
                        df = pd.concat([df, pd.DataFrame([registro])], ignore_index=True)

                    ok, msg = guardar_inventario(df, factura_verificar=registro["NumeroFactura"])
                    if ok:
                        tag = "(sincronizado con GitHub)" if msg=="OK_GITHUB" else "(guardado local)"
                        if str(msg).startswith("OK_LOCAL_GH_FAIL"): tag = "(guardado local; GitHub no disponible)"
                        flash_success(f"✅ Cambios guardados — Factura {registro['NumeroFactura']} {tag}")
                        st.session_state["factura_activa"] = ""
                        st.rerun()
                    else:
                        st.error(f"❌ No pude confirmar el guardado: {msg}")

    # ===== Reportes =====

  # ===== Reportes =====
with tab_reportes:
    show_flash()
    st.subheader("📑 Reportes")
    if df.empty:
        st.info("No hay datos para reportar.")
    else:
        # Selector de reporte
        tipo = st.selectbox(
            "Elige el reporte",
            ["Por EPS", "Por Vigencia", "Por Estado"],
            index=0
        )

        # Helpers de agregación
        def agg_eps(data: pd.DataFrame) -> pd.DataFrame:
            g = data.groupby("EPS", dropna=False).agg(
                Cuentas=("NumeroFactura","count"),
                Valor=("Valor","sum"),
                Radicadas=("Estado", lambda x: (x=="Radicada").sum())
            ).reset_index().fillna(0)
            g["% Avance"] = (g["Radicadas"] / g["Cuentas"].where(g["Cuentas"]!=0, pd.NA) * 100).fillna(0).round(2)
            return g.sort_values("Cuentas", ascending=False)

        def agg_vig(data: pd.DataFrame) -> pd.DataFrame:
            g = data.groupby("Vigencia", dropna=False).agg(
                Cuentas=("NumeroFactura","count"),
                Valor=("Valor","sum"),
                Radicadas=("Estado", lambda x: (x=="Radicada").sum())
            ).reset_index().fillna(0)
            g["% Avance"] = (g["Radicadas"] / g["Cuentas"].where(g["Cuentas"]!=0, pd.NA) * 100).fillna(0).round(2)
            return g.sort_values("Cuentas", ascending=False)

        def agg_estado(data: pd.DataFrame) -> pd.DataFrame:
            g = data.groupby("Estado", dropna=False).agg(
                Cuentas=("NumeroFactura","count"),
                Valor=("Valor","sum")
            ).reset_index().fillna(0)
            return g.sort_values("Cuentas", ascending=False)

        # Exportador Excel según selección
        def exportar_excel(df_tab: pd.DataFrame, sheet_name: str, extra_sheets: dict | None = None) -> bytes:
            out = io.BytesIO()
            with pd.ExcelWriter(out, engine="openpyxl") as w:
                df_tab.to_excel(w, index=False, sheet_name=sheet_name)
                if extra_sheets:
                    for name, dfx in extra_sheets.items():
                        dfx.to_excel(w, index=False, sheet_name=name)
            return out.getvalue()

        # ====== POR EPS ======
        if tipo == "Por EPS":
            tabla = agg_eps(df)

            st.markdown("### 🏥 Tabla por EPS")
            st.dataframe(tabla, use_container_width=True)

            c1, c2 = st.columns(2)
            # Embudo: cantidad y %
            total_cnt = int(tabla["Cuentas"].sum())
            tabla_plot = tabla.copy()
            tabla_plot["%"] = (tabla_plot["Cuentas"]/total_cnt*100).round(1) if total_cnt else 0
            with c1:
                fig_funnel = px.funnel(
                    tabla_plot.head(25),
                    x="Cuentas", y="EPS",
                    title="Cantidad y % por EPS"
                )
                fig_funnel.update_traces(
                    text=tabla_plot.head(25).apply(lambda r: f"{int(r['Cuentas'])} ({r['%']}%)", axis=1),
                    textposition="inside"
                )
                st.plotly_chart(fig_funnel, use_container_width=True)
            # Barras: valor radicado (solo Radicadas)
            with c2:
                df_rad = df[df["Estado"]=="Radicada"].copy()
                g_val = df_rad.groupby("EPS", dropna=False)["Valor"].sum().reset_index(name="Valor Radicado")
                g_val = g_val.sort_values("Valor Radicado", ascending=False)
                fig_val = px.bar(
                    g_val, x="EPS", y="Valor Radicado",
                    title="Valor radicado por EPS",
                    text_auto=".2s"
                )
                fig_val.update_layout(xaxis={'categoryorder':'total descending'})
                st.plotly_chart(fig_val, use_container_width=True)

            st.download_button(
                "⬇️ Descargar reporte EPS (Excel)",
                data=exportar_excel(tabla, "Por_EPS"),
                file_name="reporte_por_eps.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )

        # ====== POR VIGENCIA ======
        elif tipo == "Por Vigencia":
            tabla = agg_vig(df)

            st.markdown("### 📆 Tabla por Vigencia")
            st.dataframe(tabla, use_container_width=True)

            c1, c2 = st.columns(2)
            with c1:
                fig_vig_val = px.bar(
                    df, x="Vigencia", y="Valor", color="Estado",
                    title="Valor por Vigencia (por Estado)",
                    barmode="group", color_discrete_map=ESTADO_COLORES, text_auto=".2s"
                )
                st.plotly_chart(fig_vig_val, use_container_width=True)
            with c2:
                g_cnt = df.groupby("Vigencia", dropna=False)["NumeroFactura"].count().reset_index(name="Cuentas")
                fig_vig_donut = px.pie(
                    g_cnt, names="Vigencia", values="Cuentas",
                    hole=0.45, title="Distribución de Cuentas por Vigencia"
                )
                fig_vig_donut.update_traces(textposition="inside", textinfo="percent+value")
                st.plotly_chart(fig_vig_donut, use_container_width=True)

            st.download_button(
                "⬇️ Descargar reporte Vigencia (Excel)",
                data=exportar_excel(tabla, "Por_Vigencia"),
                file_name="reporte_por_vigencia.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )

        # ====== POR ESTADO ======
        else:  # "Por Estado"
            tabla = agg_estado(df)

            st.markdown("### 🧩 Tabla por Estado")
            st.dataframe(tabla, use_container_width=True)

            c1, c2 = st.columns(2)
            with c1:
                fig_estado = px.pie(
                    tabla, names="Estado", values="Cuentas",
                    hole=0.5, title="Distribución por Estado",
                    color="Estado", color_discrete_map=ESTADO_COLORES
                )
                fig_estado.update_traces(textposition="inside", textinfo="percent+value")
                st.plotly_chart(fig_estado, use_container_width=True)
            with c2:
                fig_bar = px.bar(
                    tabla, x="Estado", y="Cuentas",
                    title="Cuentas por Estado", text_auto=True,
                    color="Estado", color_discrete_map=ESTADO_COLORES
                )
                st.plotly_chart(fig_bar, use_container_width=True)

            st.download_button(
                "⬇️ Descargar reporte Estado (Excel)",
                data=exportar_excel(tabla, "Por_Estado"),
                file_name="reporte_por_estado.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
    
    # ===== Avance =====
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
                if pd.notna(fr):
                    return f"{MES_NOMBRE[int(fr.month)]} {int(fr.year)}"
            m = str(row.get("Mes","")).strip()
            if re.search(r"\b20\d{2}\b", m): return m
            vig = str(row.get("Vigencia","")).strip()
            if m and vig.isdigit(): return f"{m} {vig}"
            return m or "Sin Mes"

        df_v = df.copy()
        if "Estado" in df_v.columns:
            df_v["EstadoCanon"] = df_v["Estado"].astype(str).str.strip().str.lower().map({
                "radicada":"Radicada","radicadas":"Radicada",
                "pendiente":"Pendiente","auditada":"Auditada","subsanada":"Subsanada"
            }).fillna(df_v["Estado"])
        else:
            df_v["EstadoCanon"] = ""

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

            st.dataframe(comp, use_container_width=True)

            fig = go.Figure()
            fig.add_trace(go.Scatter(x=base["Mes"], y=base["% proyectado acumulado"], mode='lines+markers', name='Proyectado'))
            fig.add_trace(go.Scatter(x=comp["Mes"], y=comp["% real acumulado"], mode='lines+markers', name='Real'))
            fig.update_layout(title="Avance acumulado (%) — Real vs Proyectado", yaxis_title="% acumulado", xaxis_title="Mes")
            st.plotly_chart(fig, use_container_width=True)

            k1,k2,k3 = st.columns(3)
            k1.metric("Meta total (cuentas)", f"{total_meta:,}")
            k2.metric("Reales acumuladas", f"{int(comp['Cuentas reales'].sum()):,}")
            k3.metric("Avance total vs meta", f"{(comp['Cuentas reales'].sum()/total_meta*100 if total_meta else 0):.1f}%")

# ===== Boot =====
if st.session_state.get("autenticado", False):
    main_app()
else:
    login()

