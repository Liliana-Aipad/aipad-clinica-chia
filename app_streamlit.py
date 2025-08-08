# app_streamlit.py
# -*- coding: utf-8 -*-
import os
from datetime import datetime, date
import pandas as pd
import numpy as np
import streamlit as st
import altair as alt
from io import BytesIO
import shutil

###############################################################################
# CONFIGURACIÓN GENERAL
###############################################################################
st.set_page_config(page_title="Radicación - Gestión y Tablero", layout="wide")

# Rutas de archivos (puedes ajustar estas rutas para tu servidor)
DATA_FILE = os.environ.get("RADICACION_DATA_FILE", "inventario_ejemplo.xlsx")
BACKUP_DIR = os.environ.get("RADICACION_BACKUP_DIR", "backups")

ESTADOS = ["Pendiente", "Auditada", "Radicada"]
COLOR_ESTADO = {
    "Radicada": "#22c55e",  # Verde
    "Pendiente": "#ef4444", # Rojo
    "Auditada": "#f97316",  # Naranja
}

# EPS de ejemplo (Puedes reemplazar por las tuyas; se soportan ~25 sin problema)
EPS_LIST = [
    "Salud Total","Sanitas","Compensar","Nueva EPS","SURA","Famisanar","Coosalud",
    "SOS","Medimás","Mutual Ser","Cafesalud","Colmena","Comfenalco","Aliansalud",
    "Capresoca","Emssanar","Capital Salud","Ecoopsos","Comfandi","Comfaoriente",
    "ComfaTolima","ComfaHuila","EPM Salud","RedVital","Otro"
]

###############################################################################
# FUNCIONES DE I/O
###############################################################################
@st.cache_data(ttl=5)
def load_data(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        # Si no existe, crear un archivo vacío con columnas base
        base = pd.DataFrame(columns=[
            "ID","Factura","EPS","Vigencia","Estado",
            "FechaRadicacion","FechaMovimiento","Mes","Valor"
        ])
        base.to_excel(path, index=False)
    df = pd.read_excel(path, dtype={"ID": int, "Vigencia": int, "Valor": float})
    # Normalizar tipos
    df["Estado"] = df["Estado"].fillna("Pendiente")
    # Convertir fechas si vienen como string
    def to_date_safe(x):
        if pd.isna(x) or x == "":
            return None
        try:
            return pd.to_datetime(x).date()
        except Exception:
            return None
    def to_dt_safe(x):
        if pd.isna(x) or x == "":
            return None
        try:
            return pd.to_datetime(x)
        except Exception:
            return None
    df["FechaRadicacion"] = df["FechaRadicacion"].apply(to_date_safe)
    df["FechaMovimiento"] = df["FechaMovimiento"].apply(to_dt_safe)
    # Recalcular Mes a partir de FechaRadicacion si existe
    df["Mes"] = df["FechaRadicacion"].apply(lambda d: f"{d.year:04d}-{d.month:02d}" if pd.notna(d) and d else "")
    # Asegurar ID único incremental
    if not df.empty:
        df = df.sort_values("ID").reset_index(drop=True)
    return df

def save_data(df: pd.DataFrame, path: str):
    df.to_excel(path, index=False)

def backup_data(src: str, backup_dir: str):
    os.makedirs(backup_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(backup_dir, f"inventario_{ts}.xlsx")
    shutil.copy2(src, dst)
    return dst

###############################################################################
# UTILIDADES
###############################################################################
def next_id(df: pd.DataFrame) -> int:
    if df.empty: 
        return 1
    return int(df["ID"].max()) + 1

def clear_form_state():
    for k in ["form_id","form_factura","form_eps","form_vigencia","form_estado",
              "form_fecha_radicacion","form_valor","form_modo_edicion"]:
        if k in st.session_state:
            del st.session_state[k]

def set_active_page(page_key: str):
    st.session_state["active_page"] = page_key

def now_local():
    return datetime.now()

###############################################################################
# CARGA INICIAL
###############################################################################
df = load_data(DATA_FILE)
if "active_page" not in st.session_state:
    st.session_state["active_page"] = "gestion"  # mantener pestaña tras guardar

###############################################################################
# NAVEGACIÓN (sin cambiar de página tras guardar)
###############################################################################
nav = st.radio(
    "Navegación",
    options=[("Gestión","gestion"), ("Kanban","kanban"), ("Dashboard","dashboard"), ("Backups","backups")],
    format_func=lambda x: x[0],
    horizontal=True,
    index=["gestion","kanban","dashboard","backups"].index(st.session_state["active_page"])
)
set_active_page(nav[1])

st.markdown("### Proyecto: Radicación - Gestión de Facturas")

###############################################################################
# PESTAÑA: GESTIÓN (Formulario de captura y edición + tabla)
###############################################################################
if st.session_state["active_page"] == "gestion":
    st.subheader("Gestión")
    col_form, col_table = st.columns([1,2], vertical_alignment="top")

    with col_form:
        st.markdown("**Formulario**")
        # Detectar si venimos a editar
        modo_edicion = st.session_state.get("form_modo_edicion", False)

        # Campos base
        if modo_edicion:
            id_val = st.number_input("ID (bloqueado)", min_value=1, value=int(st.session_state.get("form_id", 0)), disabled=True)
        else:
            id_val = st.number_input("ID (asignado automáticamente)", min_value=1, value=next_id(df), disabled=True)

        factura = st.text_input("Factura", value=st.session_state.get("form_factura",""))
        eps = st.selectbox("EPS", EPS_LIST, index=EPS_LIST.index(st.session_state.get("form_eps", EPS_LIST[0])) if st.session_state.get("form_eps") in EPS_LIST else 0)
        vigencia = st.number_input("Vigencia", min_value=2000, max_value=2100, value=int(st.session_state.get("form_vigencia", datetime.now().year)))

        # Estado con lista desplegable
        estado = st.selectbox("Estado", ESTADOS, index=ESTADOS.index(st.session_state.get("form_estado","Pendiente")))

        # Regla: FechaRadicacion solo editable cuando estado == 'Radicada'
        fecha_radicacion_disabled = estado != "Radicada"
        fecha_radicacion = st.date_input(
            "Fecha de radicación",
            value=st.session_state.get("form_fecha_radicacion", date.today() if estado=="Radicada" else date.today()),
            disabled=fecha_radicacion_disabled
        )

        valor = st.number_input("Valor", min_value=0.0, step=1000.0, value=float(st.session_state.get("form_valor", 0.0)))

        # Botones de acción
        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("Guardar cambios", type="primary"):
                # Cargar datos actuales
                data = load_data(DATA_FILE)
                mes = f"{fecha_radicacion.year:04d}-{fecha_radicacion.month:02d}" if estado=="Radicada" else ""

                if modo_edicion:
                    # Actualizar fila existente (ID bloqueado)
                    idx = data.index[data["ID"] == st.session_state["form_id"]]
                    if len(idx) == 1:
                        idx = idx[0]
                        # Si el estado cambió, actualizar FechaMovimiento a ahora
                        old_estado = str(data.at[idx, "Estado"])
                        if old_estado != estado:
                            data.at[idx, "FechaMovimiento"] = now_local()
                        # Asignaciones seguras
                        data.at[idx, "Factura"] = factura
                        data.at[idx, "EPS"] = eps
                        data.at[idx, "Vigencia"] = int(vigencia)
                        data.at[idx, "Estado"] = estado
                        # Reglas de FechaRadicacion
                        if estado == "Radicada":
                            data.at[idx, "FechaRadicacion"] = fecha_radicacion
                            data.at[idx, "Mes"] = mes
                        else:
                            data.at[idx, "FechaRadicacion"] = None
                            data.at[idx, "Mes"] = ""
                        data.at[idx, "Valor"] = float(valor)
                else:
                    # Crear nueva fila
                    new_id = next_id(data)
                    new_row = {
                        "ID": new_id,
                        "Factura": factura,
                        "EPS": eps,
                        "Vigencia": int(vigencia),
                        "Estado": estado,
                        "FechaRadicacion": fecha_radicacion if estado=="Radicada" else None,
                        "FechaMovimiento": now_local(),
                        "Mes": mes,
                        "Valor": float(valor),
                    }
                    data = pd.concat([data, pd.DataFrame([new_row])], ignore_index=True)

                # Guardar a disco sin cambiar de pestaña
                save_data(data, DATA_FILE)
                st.success("¡Cambios guardados correctamente! El formulario se ha limpiado y permaneces en 'Gestión'.")
                clear_form_state()
                st.rerun(scope="fragment")

        with c2:
            if st.button("Limpiar formulario"):
                clear_form_state()
                st.rerun(scope="fragment")

        with c3:
            # Backup manual
            if st.button("Hacer backup ahora"):
                try:
                    dst = backup_data(DATA_FILE, BACKUP_DIR)
                    st.toast(f"Backup creado: {dst}", icon="✅")
                except Exception as e:
                    st.error(f"No se pudo crear el backup: {e}")

    with col_table:
        st.markdown("**Inventario**")
        if df.empty:
            st.info("No hay registros aún.")
        else:
            # Mostrar tabla: FechaMovimiento visible pero NO editable, ID bloqueado
            show = df.copy()
            # Formateos para visualizar
            show["FechaRadicacion"] = show["FechaRadicacion"].apply(lambda d: d.strftime("%Y-%m-%d") if pd.notna(d) and d else "")
            show["FechaMovimiento"] = show["FechaMovimiento"].apply(lambda d: d.strftime("%Y-%m-%d %H:%M:%S") if pd.notna(d) and d else "")
            st.dataframe(show, use_container_width=True, hide_index=True)

            # Acciones por fila
            st.markdown("**Editar / Eliminar**")
            ids = df["ID"].tolist()
            colA, colB, colC = st.columns([2,1,1])
            with colA:
                sel_id = st.selectbox("Selecciona ID para editar/eliminar", ids)
            with colB:
                if st.button("Editar selección"):
                    row = df[df["ID"] == sel_id].iloc[0]
                    st.session_state["form_modo_edicion"] = True
                    st.session_state["form_id"] = int(row["ID"])
                    st.session_state["form_factura"] = str(row["Factura"])
                    st.session_state["form_eps"] = str(row["EPS"]) if row["EPS"] in EPS_LIST else EPS_LIST[0]
                    st.session_state["form_vigencia"] = int(row["Vigencia"])
                    st.session_state["form_estado"] = str(row["Estado"])
                    st.session_state["form_fecha_radicacion"] = row["FechaRadicacion"] if pd.notna(row["FechaRadicacion"]) else date.today()
                    st.session_state["form_valor"] = float(row["Valor"]) if pd.notna(row["Valor"]) else 0.0
                    st.rerun(scope="fragment")
            with colC:
                if st.button("Eliminar selección"):
                    data = load_data(DATA_FILE)
                    data = data[data["ID"] != sel_id]
                    save_data(data, DATA_FILE)
                    st.success(f"Registro {sel_id} eliminado.")
                    st.rerun(scope="fragment")

###############################################################################
# PESTAÑA: KANBAN (cambiar estado arrastrando con controles simples)
###############################################################################
elif st.session_state["active_page"] == "kanban":
    st.subheader("Kanban por Estado")
    if df.empty:
        st.info("No hay registros para mostrar.")
    else:
        # Tres columnas: Pendiente, Auditada, Radicada
        cols = st.columns(3)
        estados_col = ["Pendiente","Auditada","Radicada"]
        for i, est in enumerate(estados_col):
            with cols[i]:
                st.markdown(f"#### {est}")
                subset = df[df["Estado"] == est].sort_values("FechaMovimiento", ascending=False)
                if subset.empty:
                    st.caption("— vacío —")
                else:
                    for _, row in subset.iterrows():
                        with st.container(border=True):
                            st.markdown(f"**#{int(row['ID'])}** — {row['Factura']}")
                            st.caption(f"EPS: {row['EPS']} • Vigencia: {int(row['Vigencia'])} • Valor: {int(row['Valor']):,}".replace(",", "."))
                            # Controles para mover de estado
                            new_state = st.selectbox(
                                "Mover a:",
                                ESTADOS,
                                index=ESTADOS.index(est),
                                key=f"move_{int(row['ID'])}"
                            )
                            if st.button("Aplicar", key=f"apply_{int(row['ID'])}"):
                                data = load_data(DATA_FILE)
                                idx = data.index[data["ID"] == int(row["ID"])]
                                if len(idx)==1:
                                    idx = idx[0]
                                    old_est = str(data.at[idx,"Estado"])
                                    if new_state != old_est:
                                        data.at[idx,"Estado"] = new_state
                                        data.at[idx,"FechaMovimiento"] = now_local()
                                        # Reglas de radicación
                                        if new_state=="Radicada":
                                            data.at[idx,"FechaRadicacion"] = date.today()
                                            data.at[idx,"Mes"] = f"{date.today().year:04d}-{date.today().month:02d}"
                                        else:
                                            data.at[idx,"FechaRadicacion"] = None
                                            data.at[idx,"Mes"] = ""
                                        save_data(data, DATA_FILE)
                                        st.toast(f"#{int(row['ID'])} movida a {new_state}", icon="✅")
                                        st.rerun(scope="page")

###############################################################################
# PESTAÑA: DASHBOARD (gráficos gerenciales SIN filtros)
###############################################################################
elif st.session_state["active_page"] == "dashboard":
    st.subheader("Dashboard Gerencial")
    if df.empty:
        st.info("No hay registros para mostrar.")
    else:
        # KPIs
        total_facturas = len(df)
        valor_total = float(df["Valor"].fillna(0).sum())
        radicadas = int((df["Estado"] == "Radicada").sum())
        avance_pct = (radicadas / total_facturas * 100.0) if total_facturas else 0.0

        k1, k2, k3 = st.columns(3)
        k1.metric("Número de facturas", f"{total_facturas}")
        k2.metric("Valor total", f"${valor_total:,.0f}".replace(",", "."))
        k3.metric("Avance (Radicadas / Total)", f"{avance_pct:,.1f}%")

        # Preparar datos
        df_estado = df.groupby("Estado", as_index=False).agg(
            facturas=("ID","count"),
            valor=("Valor","sum")
        )
        # Gráfico por estado (barra + etiquetas)
        base_estado = alt.Chart(df_estado).mark_bar().encode(
            x=alt.X("Estado:N", sort=ESTADOS),
            y=alt.Y("facturas:Q"),
            color=alt.Color("Estado:N", scale=alt.Scale(domain=list(COLOR_ESTADO.keys()), range=list(COLOR_ESTADO.values()))),
        )
        text_estado = base_estado.mark_text(dy=-6).encode(text="facturas:Q")
        st.altair_chart(base_estado + text_estado, use_container_width=True)

        # Por EPS
        df_eps = df.groupby("EPS", as_index=False).agg(
            facturas=("ID","count"),
            valor=("Valor","sum"),
            radicadas=("Estado", lambda s: (s=="Radicada").sum())
        )
        df_eps["avance_pct"] = df_eps["radicadas"] / df_eps["facturas"] * 100
        # Usar barras apiladas por estado para ver composición + etiquetas totales
        df_comp = df.groupby(["EPS","Estado"], as_index=False).agg(facturas=("ID","count"))
        chart_eps = alt.Chart(df_comp).mark_bar().encode(
            x=alt.X("EPS:N", sort="-y"),
            y=alt.Y("facturas:Q"),
            color=alt.Color("Estado:N", scale=alt.Scale(domain=list(COLOR_ESTADO.keys()), range=list(COLOR_ESTADO.values()))),
            tooltip=["EPS","Estado","facturas"]
        )
        # Etiquetas con total por EPS
        text_eps = alt.Chart(df_eps).mark_text(dy=-6).encode(
            x=alt.X("EPS:N", sort="-y"),
            y="facturas:Q",
            text=alt.Text("facturas:Q", format=".0f")
        )
        st.markdown("**Desglose por EPS**")
        st.altair_chart(chart_eps + text_eps, use_container_width=True)

        # Por Vigencia (área)
        df_vig = df.groupby(["Vigencia","Estado"], as_index=False).agg(facturas=("ID","count"))
        chart_vig = alt.Chart(df_vig).mark_area(opacity=0.6).encode(
            x=alt.X("Vigencia:O"),
            y=alt.Y("facturas:Q"),
            color=alt.Color("Estado:N", scale=alt.Scale(domain=list(COLOR_ESTADO.keys()), range=list(COLOR_ESTADO.values())))
        )
        st.markdown("**Desglose por Vigencia**")
        st.altair_chart(chart_vig, use_container_width=True)

        # Por Mes (radicadas únicamente, gráfico de líneas)
        df_mes = df[df["Mes"]!=""].groupby("Mes", as_index=False).agg(facturas=("ID","count"), valor=("Valor","sum"))
        if not df_mes.empty:
            chart_mes = alt.Chart(df_mes).mark_line(point=True).encode(
                x=alt.X("Mes:T", title="Mes"),
                y=alt.Y("facturas:Q", title="Facturas Radicadas"),
                tooltip=["Mes","facturas","valor"]
            )
            st.markdown("**Radicaciones por Mes**")
            st.altair_chart(chart_mes, use_container_width=True)
        else:
            st.info("Aún no hay radicaciones con 'Mes' para graficar.")

        # Tabla de resumen (para descarga)
        st.markdown("**Resumen**")
        resumen = pd.DataFrame({
            "Total facturas":[total_facturas],
            "Valor total":[valor_total],
            "Avance %":[avance_pct]
        })
        st.dataframe(resumen, use_container_width=True, hide_index=True)

        # DESCARGA A EXCEL (resumen + tablas) — PDF deshabilitado
        out = BytesIO()
        with pd.ExcelWriter(out, engine="xlsxwriter") as writer:
            resumen.to_excel(writer, index=False, sheet_name="Resumen")
            df_estado.to_excel(writer, index=False, sheet_name="Por Estado")
            df_eps.to_excel(writer, index=False, sheet_name="Por EPS")
            df_vig.to_excel(writer, index=False, sheet_name="Por Vigencia")
            df_mes.to_excel(writer, index=False, sheet_name="Por Mes")
        st.download_button(
            "Descargar Excel del dashboard (Resumen y tablas)",
            data=out.getvalue(),
            file_name="dashboard_resumen.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

###############################################################################
# PESTAÑA: BACKUPS (respaldo centralizado manual)
###############################################################################
elif st.session_state["active_page"] == "backups":
    st.subheader("Backups centralizados (manual)")
    st.caption("Configura RADICACION_BACKUP_DIR como variable de entorno en tu servidor.")
    c1, c2 = st.columns([1,3])
    with c1:
        if st.button("Crear backup ahora"):
            try:
                dst = backup_data(DATA_FILE, BACKUP_DIR)
                st.success(f"Backup creado en: {dst}")
            except Exception as e:
                st.error(f"No se pudo crear el backup: {e}")
    with c2:
        if os.path.isdir(BACKUP_DIR):
            archivos = sorted(os.listdir(BACKUP_DIR))
            if archivos:
                st.markdown("**Archivos de backup disponibles:**")
                for f in archivos:
                    st.write(f"- {f}")
            else:
                st.info("Aún no hay backups.")
        else:
            st.info("No existe el directorio de backups. Será creado al generar el primero.")

# FIN DEL ARCHIVO
