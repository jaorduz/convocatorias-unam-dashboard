import pandas as pd
import streamlit as st
from datetime import datetime
import os
from dotenv import load_dotenv

# =========================
# CONFIGURACIÓN INICIAL
# =========================
st.set_page_config(page_title="Convocatorias de Financiamiento", layout="wide")

# CARGAR VARIABLES DE ENTORNO
load_dotenv()

# =========================
# AUTENTICACIÓN
# =========================
def check_password():
    def password_entered():
        if st.session_state["password"] == st.secrets["APP_PASSWORD"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input("Contraseña institucional", type="password", key="password", on_change=password_entered)
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("Contraseña institucional", type="password", key="password", on_change=password_entered)
        st.error("Contraseña incorrecta")
        return False
    else:
        return True

if not check_password():
    st.stop()

# =========================
# COLORES INSTITUCIONALES
# =========================
UNAM_BLUE = "#002855"
UNAM_GOLD = "#B38E2D"
BG_SOFT = "#e6ebf2"
CARD_BG = "#f7f9fc"
TEXT_MAIN = "#1e293b"

st.markdown(f"""
<style>
    .stApp {{ background-color: {BG_SOFT}; }}
    h1 {{ color: {UNAM_BLUE}; font-weight: 700; }}
    h2 {{ color: {UNAM_BLUE}; }}
    div[data-testid="stMetric"] {{
        background-color: {CARD_BG};
        padding: 18px;
        border-radius: 12px;
        border-top: 4px solid {UNAM_GOLD};
        box-shadow: 0px 2px 6px rgba(0,0,0,0.05);
    }}
    div[data-testid="stMetricValue"] {{
        color: {TEXT_MAIN};
        font-weight: 700;
    }}
</style>
""", unsafe_allow_html=True)

# =========================
# CARGAR DATOS
# =========================
df = pd.read_csv("data/calls.csv")

if "detected_status" not in df.columns:
    df["detected_status"] = "unknown"

if "detected_language" not in df.columns:
    df["detected_language"] = "unknown"

st.title("Sistema Institucional de Monitoreo de Convocatorias")
st.caption("FES Acatlán-UNAM | Inteligencia Estratégica para la Investigación")

# =========================
# BUSCADOR
# =========================
q = st.text_input("Buscar (título / descripción / entidad convocante):").strip().lower()

if q:
    mask = (
        df["title"].fillna("").str.lower().str.contains(q)
        | df["snippet"].fillna("").str.lower().str.contains(q)
        | df["source"].fillna("").str.lower().str.contains(q)
    )
    df = df[mask]

# =========================
# FILTROS
# =========================
col1, col2 = st.columns(2)

with col1:
    sources = st.multiselect(
        "Filtrar por entidad convocante",
        sorted(df["source"].dropna().unique().tolist())
    )

with col2:
    langs = st.multiselect(
        "Filtrar por idioma",
        sorted(df["detected_language"].dropna().unique().tolist())
    )

if sources:
    df = df[df["source"].isin(sources)]

if langs:
    df = df[df["detected_language"].isin(langs)]

# =========================
# FECHA
# =========================
df = df.copy()

# Convertir a datetime
df["detected_deadline"] = pd.to_datetime(df["detected_deadline"], errors="coerce")

today = pd.Timestamp.today().normalize()

# Calcular días restantes
df["days_remaining"] = (df["detected_deadline"] - today).dt.days

# Formato visible para la tabla
df["Fecha límite"] = df["detected_deadline"].dt.strftime("%Y-%m-%d")
df["Fecha límite"] = df["Fecha límite"].fillna("—")


# =========================
# ESTADO
# =========================
def calcular_estado(row):
    status = str(row.get("detected_status", "unknown")).lower()
    dias = row.get("days_remaining")

    if status == "closed":
        return "⚫ Cerrada"
    if pd.notna(dias) and dias < 0:
        return "⚫ Cerrada"
    if status == "open":
        if pd.notna(dias) and dias <= 14:
            return "🔴 Cierre próximo"
        return "🟢 Abierta"
    if pd.isna(dias):
        return "⚪ Sin fecha"
    if dias <= 14:
        return "🔴 Cierre próximo"
    return "🟡 En curso"

df["Estado"] = df.apply(calcular_estado, axis=1)

# =========================
# SEPARAR ABIERTAS Y CERRADAS
# =========================
df_main = df[df["Estado"] != "⚫ Cerrada"].copy()
df_closed = df[df["Estado"] == "⚫ Cerrada"].copy()

# Crear snippet corto SOLO para main
df_main["snippet_short"] = df_main["snippet"].fillna("").apply(
    lambda x: x[:120] + "..." if len(x) > 120 else x
)

# =========================
# KPIs
# =========================
total_convocatorias = len(df)
num_vigentes = len(df_main)
sin_fecha = df_main["detected_deadline"].isna().sum()

k1, k2, k3 = st.columns(3)
k1.metric("Total encontradas", total_convocatorias)
k2.metric("Convocatorias vigentes", num_vigentes)
k3.metric("Sin fecha límite", int(sin_fecha))

# =========================
# TABLA PRINCIPAL. Rename
# =========================
df_visual = df_main.rename(columns={
    "source": "Entidad convocante",
    "title": "Título",
    "snippet_short": "Descripción",
    "url": "Enlace"
})

st.markdown("## Convocatorias")

st.dataframe(
    df_visual[[
        "Estado",
        "Fecha límite",
        "Entidad convocante",
        "Título",
        "Descripción",
        "Enlace"
    ]],
    column_config={
        "Enlace": st.column_config.LinkColumn(
            "Enlace",
            display_text="🔗 Ver"
        )
    },
    hide_index=True,
    width="stretch",
)

# =========================
# HISTÓRICO
# =========================
with st.expander("Ver convocatorias cerradas (histórico)"):
    df_closed_visual = df_closed.copy()

    # Asegurar que Fecha límite exista
    if "Fecha límite" not in df_closed_visual.columns:
        df_closed_visual["Fecha límite"] = df_closed_visual["detected_deadline"]

    df_closed_visual = df_closed_visual.rename(columns={
        "source": "Entidad convocante",
        "title": "Título",
        "url": "Enlace"
    })

    # Eliminar duplicados por seguridad
    df_closed_visual = df_closed_visual.loc[:, ~df_closed_visual.columns.duplicated()]

    st.dataframe(
        df_closed_visual[[
            "Estado",
            "Fecha límite",
            "Entidad convocante",
            "Título",
            "Enlace"
        ]],
        column_config={
            "Enlace": st.column_config.LinkColumn(
                "Convocatoria",
                display_text="🔗 Ver"
            )
        },
        hide_index=True,
        width="stretch",
    )

# =========================
# GRÁFICO
# =========================
st.markdown("## 📊 Distribución por Entidad")

st.bar_chart(df["source"].value_counts())