import os
from pathlib import Path
from typing import Optional

import pandas as pd
import streamlit as st
import altair as alt
import streamlit.components.v1 as components
import yaml
from dotenv import load_dotenv
from content_publication import is_published_to

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


def get_app_password() -> Optional[str]:
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
BG_SOFT = "#EEF2F7"
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

    .editorial-card {{
        min-height: 220px;
        padding: 20px;
        border: 1px solid rgba(0, 40, 85, 0.12);
        border-top: 5px solid var(--editorial-accent);
        border-radius: 16px;
        background: linear-gradient(180deg, var(--editorial-bg) 0%, rgba(255,255,255,0.94) 100%);
        box-shadow: 0 8px 22px rgba(15, 23, 42, 0.08);
    }}

    .editorial-category {{
        color: var(--editorial-accent);
        font-size: 12px;
        font-weight: 800;
        letter-spacing: .2px;
        text-transform: uppercase;
    }}

    .editorial-title {{
        margin: 8px 0 8px 0;
        color: #102A43;
        font-size: 18px;
        font-weight: 800;
        line-height: 1.3;
    }}

    .editorial-message {{
        min-height: 54px;
        color: #486581;
        font-size: 14px;
        line-height: 1.55;
    }}

    .notice-image {{
        display: block;
        width: 100%;
        height: 190px;
        object-fit: cover;
        margin: 12px 0 10px 0;
        border-radius: 12px;
        border: 1px solid rgba(0, 40, 85, 0.08);
        box-shadow: 0 10px 18px rgba(15, 23, 42, 0.08);
        background: #edf5ff;
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

# Simple share link button removed to avoid clipboard issues in Streamlit's iframe environment.
st.caption("Dashboard de convocatorias")

# =========================
# INFORMACIÓN Y RECURSOS
try:
    with open("data/editorial_cards.yaml", "r", encoding="utf-8") as file:
        editorial_cards = yaml.safe_load(file).get("cards", [])
except (FileNotFoundError, AttributeError):
    editorial_cards = []

try:
    with open("data/recursos.yaml", "r", encoding="utf-8") as file:
        resources = yaml.safe_load(file).get("resources", [])
except (FileNotFoundError, AttributeError):
    resources = []

# Combine avisos and resources
all_items = []
for card in editorial_cards:
    if not is_published_to(card, "dashboard"):
        continue
    card_copy = dict(card)
    card_copy["item_type"] = "aviso"
    all_items.append(card_copy)

for resource in resources:
    if not is_published_to(resource, "dashboard"):
        continue
    resource_copy = dict(resource)
    resource_copy["item_type"] = "recurso"
    all_items.append(resource_copy)

if all_items:
    st.markdown("## Avisos e Información y Recursos")
    st.caption("Comunicados, recordatorios, materiales y recursos relevantes para la comunidad académica.")
    card_columns = st.columns(min(len(all_items), 2))
    for index, item in enumerate(all_items):
        link = str(item.get("link", "")).strip()
        poster = str(item.get("poster", "") or item.get("image", "") or item.get("poster_url", "")).strip()
        if not link.startswith(("http://", "https://")) and not poster.startswith(("http://", "https://")):
            continue
        
        item_type = item.get("item_type", "aviso")
        
        # Determine styling based on item type
        if item_type == "recurso":
            accent = "#6366F1"  # Indigo for resources
            card_background = "#E0E7FF"
            type_label = "RECURSO"
        else:
            is_recognition = "reconocimiento" in str(item.get("category", "")).lower()
            accent = UNAM_GOLD if is_recognition else "#1F5F6B"
            card_background = "#F8F1D8" if is_recognition else "#E5F2F3"
            type_label = item.get("category", "Aviso")
        
        title = item.get("title", "Aviso")
        message = item.get("message", "")
        source = item.get("source", "Fuente oficial")
        label = item.get("label", "Ver" if item_type == "recurso" else "Ver aviso")
        details = str(item.get("details", "")).strip()
        details_html = (
            f'<div style="margin-top:10px;color:#374151;font-size:13px;line-height:1.6;">{details}</div>'
            if details
            else ""
        )
        poster_html = (
            f'<div style="margin:12px 0 10px 0;"><img src="{poster}" alt="{title}" class="notice-image" /></div>'
            if poster.startswith(("http://", "https://"))
            else ""
        )
        primary_link = link if link.startswith(("http://", "https://")) else poster
        convocatoria = str(item.get("convocatoria", "")).strip()
        convocatoria_link = (
            f'<a href="{convocatoria}" target="_blank" rel="noopener noreferrer" '
            'style="display:inline-block;padding:9px 13px;border-radius:9px;background:#E6EEF8;'
            'color:#002855;text-decoration:none;font-size:13px;font-weight:700;">convocatoria</a>'
            if convocatoria.startswith(("http://", "https://"))
            else ""
        )
        with card_columns[index % len(card_columns)]:
            st.html(
                f"""
                <div class="editorial-card" style="--editorial-accent:{accent};--editorial-bg:{card_background};">
                    <div class="editorial-category">{type_label}</div>
                    <div class="editorial-title">{title}</div>
                    <div class="editorial-message">{message}</div>
                    {poster_html}
                    {details_html}
                    <div style="margin-top:10px;color:#64748B;font-size:12px;">{source}</div>
                    <div style="margin-top:12px;">
                        <a href="{primary_link}" target="_blank" rel="noopener noreferrer" style="display:inline-block;margin-right:8px;padding:9px 13px;border-radius:9px;background:{accent};color:#ffffff;text-decoration:none;font-size:13px;font-weight:700;">{label}</a>
                        {convocatoria_link}
                    </div>
                </div>
                """,
            )


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

# (KPIs removed here — will display after the main table)

# =========================
# SIDEBAR: filtros rápidos
with st.sidebar:
    st.header("Filtros rápidos")
    timeframe = st.radio("Rango", ("Todos", "Próximos 7 días", "Próximos 30 días"))
    show_only_with_date = st.checkbox("Mostrar solo con fecha conocida", value=False)

# aplicar filtros al conjunto de convocatorias vigentes
df_main_filtered = df_main.copy()
if timeframe == "Próximos 7 días":
    df_main_filtered = df_main_filtered[df_main_filtered["days_remaining"].notna() & (df_main_filtered["days_remaining"] <= 7) & (df_main_filtered["days_remaining"] >= 0)]
elif timeframe == "Próximos 30 días":
    df_main_filtered = df_main_filtered[df_main_filtered["days_remaining"].notna() & (df_main_filtered["days_remaining"] <= 30) & (df_main_filtered["days_remaining"] >= 0)]

if show_only_with_date:
    df_main_filtered = df_main_filtered[df_main_filtered["detected_deadline"].notna()]

# Tabla principal (filtrada)
df_visual = df_main_filtered.rename(
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
# KPIs (for filtered data) and CSV download
total_in_table = len(df_visual)
num_vigentes = len(df_main_filtered)
sin_fecha = int(df_main_filtered["detected_deadline"].isna().sum())

k1, k2, k3 = st.columns(3)
k1.metric("En tabla", total_in_table)
k2.metric("Vigentes (filtradas)", num_vigentes)
k3.metric("Sin fecha límite", sin_fecha)

# Descargar CSV filtrado
csv_bytes = df_visual.to_csv(index=False).encode("utf-8")
st.download_button("Descargar CSV (filtrado)", data=csv_bytes, file_name="convocatorias_filtradas.csv", mime="text/csv")

# =========================
# GRÁFICO (Altair) — mostrado después de tabla/stats
st.markdown("## 📊 Distribución por Entidad")
counts = df_main_filtered["source"].fillna("—").value_counts().reset_index()
if not counts.empty:
    counts.columns = ["Entidad convocante", "count"]
    chart = (
        alt.Chart(counts)
        .mark_bar()
        .encode(
            x=alt.X("count:Q", title="Número de convocatorias"),
            y=alt.Y("Entidad convocante:N", sort="-x"),
            color=alt.Color("count:Q", scale=alt.Scale(scheme="blues")),
            tooltip=[alt.Tooltip("Entidad convocante:N"), alt.Tooltip("count:Q")],
        )
        .properties(height=400)
    )
    st.altair_chart(chart, use_container_width=True)
else:
    st.info("No hay datos para mostrar en el rango seleccionado.")

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
