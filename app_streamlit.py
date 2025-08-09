# app_streamlit.py
# -*- coding: utf-8 -*-
APP_VERSION = "2025-08-09 05:05"

import streamlit as st
st.set_page_config(layout="wide")

import pandas as pd
import os, io, re
import plotly.express as px
from datetime import datetime, date
import streamlit.components.v1 as components

INVENTARIO_FILE = "inventario_cuentas.xlsx"
USUARIOS_FILE   = "usuarios.xlsx"

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

@st.cache_data
def load_data():
    if not os.path.exists(INVENTARIO_FILE):
        cols = ["ID","NumeroFactura","Valor","EPS","Vigencia","Estado",
                "Mes","FechaRadicacion","FechaMovimiento","Observaciones"]
        return pd.DataFrame(columns=cols)
    df = pd.read_excel(INVENTARIO_FILE)
    # No normalizamos ni sobreescribimos columnas del archivo
    # Solo convertimos fechas a datetime para poder usarlas si existen
    for c in ["FechaRadicacion","FechaMovimiento"]:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce")
    return df

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

def exportar_dashboard_excel(df: pd.DataFrame) -> bytes:
    output = io.BytesIO()
    total = len(df)
    # Vista segura para conteos por estado
    df_view = df.copy()
    norm = df_view.get("Estado", pd.Series(dtype=object)).astype(str).str.strip().str.lower()
    mapa = {
        "radicada":"Radicada","radicadas":"Radicada",
        "pendiente":"Pendiente",
        "auditada":"Auditada","auditadas":"Auditada",
        "subsanada":"Subsanada","subsanadas":"Subsanada",
    }
    df_view["EstadoCanon"] = norm.map(mapa).fillna(df_view.get("Estado"))
    radicadas = (df_view["EstadoCanon"] == "Radicada").sum()

    total_valor = float(pd.to_numeric(df.get("Valor"), errors="coerce").fillna(0).sum()) if "Valor" in df.columns else 0.0
    avance = round((radicadas / total) * 100, 2) if total else 0.0

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame({
            "Métrica": ["Total facturas", "Valor total", "% Avance (radicadas)"],
            "Valor": [total, total_valor, avance]
        }).to_excel(writer, index=False, sheet_name="Resumen")
    return output.getvalue()

def main_app():
    st.caption(f"🆔 Versión: {APP_VERSION}")
    st.title("📊 AIPAD • Control de Radicación")

    df = load_data()

    # --- Vista segura (no tocar archivo) ---
    df_view = df.copy()
    norm = df_view.get("Estado", pd.Series(dtype=object)).astype(str).str.strip().str.lower()
    mapa = {
        "radicada":"Radicada","radicadas":"Radicada",
        "pendiente":"Pendiente",
        "auditada":"Auditada","auditadas":"Auditada",
        "subsanada":"Subsanada","subsanadas":"Subsanada",
    }
    df_view["EstadoCanon"] = norm.map(mapa).fillna(df_view.get("Estado"))

    tab1, = st.tabs(["📋 Dashboard"])

    with tab1:
        st.subheader("📈 Avance general del proyecto")
        if df_view.empty:
            st.info("No hay datos en el inventario.")
        else:
            total = len(df_view)
            total_valor = float(pd.to_numeric(df_view.get("Valor"), errors="coerce").fillna(0).sum()) if "Valor" in df_view.columns else 0.0
            radicadas = (df_view["EstadoCanon"] == "Radicada").sum()
            avance = round((radicadas / total) * 100, 2) if total else 0.0

            c1, c2, c3 = st.columns(3)
            c1.metric("📦 Total facturas", total)
            c2.metric("💰 Valor total", f"${total_valor:,.0f}")
            c3.metric("📊 Avance (radicadas)", f"{avance}%")

            # ---------------- EPS ----------------
            st.markdown("## 🏥 Por EPS")
            if {"EPS","NumeroFactura"}.issubset(df_view.columns):
                # Embudo: cantidad y % por EPS
                g = df_view.groupby("EPS", dropna=False)["NumeroFactura"].nunique().reset_index(name="Cantidad")
                g = g.sort_values("Cantidad", ascending=False).head(25)
                # Calcular porcentaje
                total_cant = g["Cantidad"].sum()
                g["%"] = (g["Cantidad"] / total_cant * 100).round(1) if total_cant else 0.0
                fig_funnel = px.funnel(g, x="Cantidad", y="EPS", title="Cantidad y % por EPS")
                fig_funnel.update_traces(text=g.apply(lambda r: f"{int(r['Cantidad'])} • {r['%']}%", axis=1))
                st.plotly_chart(fig_funnel, use_container_width=True)

                # Columnas: valor radicado por EPS (solo Radicadas)
                if {"Valor","Estado"}.issubset(df_view.columns):
                    df_rad = df_view[df_view["EstadoCanon"] == "Radicada"].copy()
                    if not df_rad.empty:
                        g_val = df_rad.groupby("EPS", dropna=False)["Valor"].sum().reset_index()
                        g_val = g_val.sort_values("Valor", ascending=False)
                        fig_val = px.bar(g_val, x="EPS", y="Valor", title="Valor radicado por EPS (solo Radicadas)", text_auto=".2s")
                        fig_val.update_layout(xaxis={'categoryorder':'total descending'})
                        st.plotly_chart(fig_val, use_container_width=True)

            # ---------------- VIGENCIA ----------------
            st.markdown("## 📆 Por Vigencia")
            if {"Vigencia"}.issubset(df_view.columns):
                # Barras de valor por Vigencia coloreado por EstadoCanon
                if {"Valor","Estado"}.issubset(df_view.columns):
                    g_val_vig = df_view.groupby(["Vigencia","EstadoCanon"], dropna=False)["Valor"].sum().reset_index()
                    fig_vig_val = px.bar(
                        g_val_vig, x="Vigencia", y="Valor", color="EstadoCanon", barmode="group",
                        title="Valor por Vigencia", color_discrete_map=ESTADO_COLORES, text_auto=".2s"
                    )
                    st.plotly_chart(fig_vig_val, use_container_width=True)

                # Donut distribución de cantidad por Vigencia
                if {"NumeroFactura"}.issubset(df_view.columns):
                    g_cnt_vig = df_view.groupby("Vigencia", dropna=False)["NumeroFactura"].nunique().reset_index(name="Cantidad")
                    fig_vig_donut = px.pie(g_cnt_vig, names="Vigencia", values="Cantidad", hole=0.5,
                                           title="Distribución de Facturas por Vigencia")
                    fig_vig_donut.update_traces(textinfo="percent", hovertemplate="%{label}: %{value} facturas (%{percent})")
                    st.plotly_chart(fig_vig_donut, use_container_width=True)

            st.divider()
            xls_bytes = exportar_dashboard_excel(df)
            st.download_button(
                "⬇️ Descargar Dashboard a Excel",
                data=xls_bytes,
                file_name="dashboard_radicacion.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )

# ===== BOOT =====
if "autenticado" not in st.session_state:
    login()
elif st.session_state.get("autenticado"):
    main_app()
