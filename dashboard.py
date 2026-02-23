import pandas as pd
import streamlit as st
from datetime import datetime
import pandas as pd
import streamlit as st
from datetime import datetime
import os
from dotenv import load_dotenv

# CARGAR VARIABLES DE ENTORNO
load_dotenv()

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

st.set_page_config(page_title="Convocatorias de Financiamiento", layout="wide")

st.markdown(f"""
<style>
    .stApp {{
        background-color: {BG_SOFT};
    }}

    h1 {{
        color: {UNAM_BLUE};
        font-weight: 700;
    }}

    h2 {{
        color: {UNAM_BLUE};
    }}

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

st.title("Sistema de Monitoreo de Convocatorias")
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
# FECHA Y DÍAS RESTANTES
# =========================
df = df.copy()
df["detected_deadline"] = pd.to_datetime(df["detected_deadline"], errors="coerce")

today = pd.Timestamp.today().normalize()
df["days_remaining"] = (df["detected_deadline"] - today).dt.days

# =========================
# CARGAR ÁREAS Y DIVISIONES
# =========================
areas_df = pd.read_csv("data/areas_estrategicas.csv")
divisiones_df = pd.read_csv("data/divisiones_academicas.csv")

def analizar_estrategia(row):
    texto = f"{row.get('title','')} {row.get('snippet','')}".lower()
    puntaje_total = 0
    puntaje_por_area = {}

    for _, r in areas_df.iterrows():
        area = r["area"]
        palabra = str(r["palabra_clave"]).lower()
        peso = r["peso"]

        if palabra in texto:
            puntaje_total += peso
            puntaje_por_area[area] = puntaje_por_area.get(area, 0) + peso

    # Urgencia
    if pd.notna(row["days_remaining"]):
        if row["days_remaining"] <= 14:
            puntaje_total += 5
        elif row["days_remaining"] <= 30:
            puntaje_total += 3
        elif row["days_remaining"] <= 60:
            puntaje_total += 1

    if puntaje_por_area:
        area_dominante = max(puntaje_por_area, key=puntaje_por_area.get)
    else:
        area_dominante = "General"

    return pd.Series([puntaje_total, area_dominante])

df[["puntaje_estrategico", "area_estrategica"]] = df.apply(
    analizar_estrategia, axis=1
)

# =========================
# MAPEO A DIVISIÓN
# =========================
mapa_divisiones = dict(zip(divisiones_df["area"], divisiones_df["division"]))
df["division_academica"] = df["area_estrategica"].map(mapa_divisiones).fillna("General")

# =========================
# PRIORIDAD Y URGENCIA
# =========================
def convertir_a_estrellas(puntaje):
    if puntaje >= 10:
        return "⭐⭐⭐"
    elif puntaje >= 6:
        return "⭐⭐"
    elif puntaje >= 3:
        return "⭐"
    else:
        return ""

df["Prioridad"] = df["puntaje_estrategico"].apply(convertir_a_estrellas)

def urgencia_icono(dias):
    if pd.isna(dias):
        return "⚪"
    if dias < 0:
        return "⚫"
    elif dias <= 14:
        return "🔴"
    elif dias <= 30:
        return "🟡"
    else:
        return "🟢"

df["Urgencia"] = df["days_remaining"].apply(urgencia_icono)

# =========================
# ORDENAMIENTO
# =========================
df = df.sort_values(
    by=["puntaje_estrategico", "days_remaining"],
    ascending=[False, True],
    na_position="last"
)

# =========================
# KPIs
# =========================
total_convocatorias = len(df)
vigentes = df[df["days_remaining"].notna() & (df["days_remaining"] >= 0)]
num_vigentes = len(vigentes)
sin_fecha = df["detected_deadline"].isna().sum()

k1, k2, k3 = st.columns(3)
k1.metric("Total encontradas", total_convocatorias)
k2.metric("Convocatorias vigentes", num_vigentes)
k3.metric("Sin fecha límite", int(sin_fecha))

# =========================
# TABLA PRINCIPAL (COMPACTA)
# =========================

# Reducir longitud de descripción
df["snippet_short"] = df["snippet"].fillna("").apply(
    lambda x: x[:120] + "..." if len(x) > 120 else x
)

df_visual = df.rename(columns={
    "detected_deadline": "Fecha límite",
    "days_remaining": "Días restantes",
    "convocatoria": "Convocatoria",   # CAMBIO AQUÍ
    "title": "Título",
    "snippet_short": "Descripción",
    "url": "Enlace"
})

st.markdown("## Convocatorias")

st.dataframe(
    df_visual[[
        "Urgencia",
        "Fecha límite",
        "Días restantes",
        "Convocatoria",
        "Título",
        "Descripción",
        "Enlace"
    ]],
    column_config={
        "Urgencia": st.column_config.Column(width="small"),
        "Fecha límite": st.column_config.DateColumn(width="small"),
        "Días restantes": st.column_config.NumberColumn(width="small"),
        "Convocatoria": st.column_config.Column(width="medium"),
        "Título": st.column_config.Column(width="large"),
        "Descripción": st.column_config.Column(width="large"),
        "Enlace": st.column_config.LinkColumn(
            "Convocatoria",
            display_text="🔗 Ver"
        )
    },
    hide_index=True,
    width="stretch",
)

st.caption("🔴 ≤14 días | 🟡 ≤30 días | 🟢 >30 días")

# =========================
# GRÁFICO POR ÁREA
# =========================
st.markdown("## 📊 Distribución por Área Estratégica")

area_counts = df["area_estrategica"].value_counts().reset_index()
area_counts.columns = ["Área Estratégica", "Convocatorias"]

st.bar_chart(area_counts.set_index("Área Estratégica"))

# =========================
# TABLA CONSOLIDADA
# =========================
st.markdown("## 📈 Análisis Institucional Consolidado")

consolidado = (
    df.groupby(["division_academica", "area_estrategica"])
    .size()
    .reset_index(name="Convocatorias")
)

consolidado["Porcentaje (%)"] = (
    consolidado["Convocatorias"] / total_convocatorias * 100
).round(1)

consolidado = consolidado.rename(columns={
    "division_academica": "División Académica",
    "area_estrategica": "Área Estratégica"
}).sort_values("Convocatorias", ascending=False)

st.dataframe(
    consolidado,
    hide_index=True,
    width="stretch"
)