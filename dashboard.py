import os
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

# =========================
# CONFIGURACIÓN INICIAL
# =========================
st.set_page_config(page_title="Convocatorias de Financiamiento", layout="wide")
load_dotenv(override=True)

# =========================
# AUTENTICACIÓN (ON / OFF)
# =========================
def require_password_enabled() -> bool:
    value = os.getenv("REQUIRE_PASSWORD")
    if value is None:
        try:
            value = st.secrets.get("REQUIRE_PASSWORD", "false")
        except Exception:
            value = "false"
    value = str(value).strip().lower()
    return value in {"1", "true", "yes", "on"}


def get_app_password() -> str | None:
    env_value = os.getenv("APP_PASSWORD")
    if env_value:
        return env_value
    try:
        return st.secrets.get("APP_PASSWORD")
    except Exception:
        return None


def check_password() -> bool:
    app_password = get_app_password()

    if not app_password:
        st.error("No se encontró APP_PASSWORD en variables de entorno ni en secrets.")
        return False

    def password_entered():
        if st.session_state["password"] == app_password:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input(
            "Contraseña institucional",
            type="password",
            key="password",
            on_change=password_entered,
        )
        return False

    if not st.session_state["password_correct"]:
        st.text_input(
            "Contraseña institucional",
            type="password",
            key="password",
            on_change=password_entered,
        )
        st.error("Contraseña incorrecta")
        return False

    return True


if require_password_enabled():
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

st.markdown(
    f"""
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
""",
    unsafe_allow_html=True,
)

# =========================
# CARGAR DATOS
# =========================
DATA_PATH = Path("data/calls.csv")

if not DATA_PATH.exists():
    st.warning("No hay datos disponibles todavía. Ejecuta primero el agente para generar data/calls.csv.")
    st.stop()

df = pd.read_csv(DATA_PATH)

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
        sorted(df["source"].dropna().unique().tolist()),
    )

with col2:
    langs = st.multiselect(
        "Filtrar por idioma",
        sorted(df["detected_language"].dropna().unique().tolist()),
    )

if sources:
    df = df[df["source"].isin(sources)]

if langs:
    df = df[df["detected_language"].isin(langs)]

# =========================
# FECHA
# =========================
df = df.copy()
df["detected_deadline"] = pd.to_datetime(df["detected_deadline"], errors="coerce")
today = pd.Timestamp.today().normalize()
df["days_remaining"] = (df["detected_deadline"] - today).dt.days
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

# =========================
# FORMATO DE TEXTO
# =========================
def wrap_text(text, width=40):
    words = str(text).split()
    lines = []
    line = ""

    for w in words:
        if len(line) + len(w) + (1 if line else 0) <= width:
            line += (" " + w) if line else w
        else:
            if line:
                lines.append(line)
            line = w

    if line:
        lines.append(line)

    return "\n".join(lines)


df_main["Título"] = df_main["title"].fillna("").apply(lambda x: wrap_text(x, 45))
df_main["Descripción"] = df_main["snippet"].fillna("").apply(lambda x: wrap_text(str(x)[:200], 55))

df_closed["Título"] = df_closed["title"].fillna("").apply(lambda x: wrap_text(x, 45))

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
# TABLA PRINCIPAL
# =========================
df_visual = df_main.rename(
    columns={
        "source": "Entidad convocante",
        "url": "Enlace",
    }
)

st.markdown("## Convocatorias")

st.dataframe(
    df_visual[
        [
            "Estado",
            "Fecha límite",
            "Entidad convocante",
            "Título",
            "Descripción",
            "Enlace",
        ]
    ],
    column_config={
        "Estado": st.column_config.TextColumn("Estado", width="small"),
        "Fecha límite": st.column_config.TextColumn("Fecha límite", width="small"),
        "Entidad convocante": st.column_config.TextColumn("Entidad convocante", width="medium"),
        "Título": st.column_config.TextColumn("Título", width="medium"),
        "Descripción": st.column_config.TextColumn("Descripción", width="medium"),
        "Enlace": st.column_config.LinkColumn(
            "Convocatoria",
            display_text="🔗 Ver",
        ),
    },
    hide_index=True,
    width="stretch",
)

# =========================
# HISTÓRICO
# =========================
with st.expander("Ver convocatorias cerradas (histórico)"):
    df_closed_visual = df_closed.copy()
    df_closed_visual = df_closed_visual.rename(
        columns={
            "source": "Entidad convocante",
            "url": "Enlace",
        }
    )
    df_closed_visual = df_closed_visual.loc[:, ~df_closed_visual.columns.duplicated()]

    st.dataframe(
        df_closed_visual[
            [
                "Estado",
                "Fecha límite",
                "Entidad convocante",
                "Título",
                "Enlace",
            ]
        ],
        column_config={
            "Enlace": st.column_config.LinkColumn(
                "Convocatoria",
                display_text="🔗 Ver",
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