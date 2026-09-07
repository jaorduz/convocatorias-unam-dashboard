#!/usr/bin/env bash
# Interactive wrapper for:
# - Funding calls sources
# - Dashboard updates
# - Local Streamlit preview
# - Newsletter preview
# - Newsletter sending
# - Weekly scheduling

set -euo pipefail

# =========================================================
# PROJECT DIRECTORY
# =========================================================

cd "$(dirname "$0")"


# =========================================================
# LOAD ENVIRONMENT VARIABLES
# =========================================================

if [ -f .env ]; then
  set -a

  # shellcheck disable=SC1091
  . ./.env

  set +a
fi


# =========================================================
# PYTHON ENVIRONMENT
# =========================================================

if [[ -z "${PYTHON_BIN:-}" ]]; then

  if [[ -x "$HOME/miniconda3/envs/calls-agent/bin/python" ]]; then

    PYTHON_BIN="$HOME/miniconda3/envs/calls-agent/bin/python"

  elif [[ -x "../.venv/bin/python" ]]; then

    PYTHON_BIN="../.venv/bin/python"

  else

    PYTHON_BIN="$(command -v python3)"

  fi
fi


# =========================================================
# STREAMLIT
# =========================================================

STREAMLIT_BIN="${STREAMLIT_BIN:-}"

if [[ -z "$STREAMLIT_BIN" ]]; then
  STREAMLIT_BIN="$(dirname "$PYTHON_BIN")/streamlit"
fi


# =========================================================
# MENU
# =========================================================

show_menu() {

  printf '\n'
  printf '=============================================\n'
  printf ' Sistema Institucional de Monitoreo\n'
  printf ' de Convocatorias\n'
  printf '=============================================\n\n'

  printf '1) Agregar nuevo sitio web\n'
  printf '2) Actualizar datos del dashboard\n'
  printf '3) Abrir preview local del dashboard\n'
  printf '4) Abrir vista previa del boletín\n'
  printf '5) Enviar boletín a special_recipients.csv\n'
  printf '6) Programar envío semanal\n'
  printf 'q) Salir\n\n'
}


# =========================================================
# OPTION 1
# ADD NEW WEBSITE
# =========================================================

add_website() {

  local source_name
  local source_url
  local newsletter_section
  local keywords

  printf '\n=== Agregar nuevo sitio web ===\n\n'

  read -r -p "Nombre de la organización o sitio: " source_name

  read -r -p "URL oficial: " source_url

  read -r -p \
    "Sección (México/Internacionales/Investigadores senior; por defecto México): " \
    newsletter_section

  read -r -p \
    "Palabras clave separadas por coma (por defecto convocatoria,investigacion,proyecto,funding,grant): " \
    keywords


  newsletter_section="${newsletter_section:-México}"

  keywords="${keywords:-convocatoria,investigacion,proyecto,funding,grant}"


  if [[ -z "$source_name" || ! "$source_url" =~ ^https?:// ]]; then

    printf '\nERROR: Se requieren un nombre y una URL http(s) válida.\n'

    return
  fi


  "$PYTHON_BIN" - \
    "$source_name" \
    "$source_url" \
    "$newsletter_section" \
    "$keywords" <<'PY'

import sys
from pathlib import Path
import yaml


name, url, section, keywords = sys.argv[1:]


path = Path("sources.yaml")


data = yaml.safe_load(
    path.read_text(encoding="utf-8")
) or {"sources": []}


sources = data.setdefault("sources", [])


if any(item.get("url") == url for item in sources):

    raise SystemExit(
        f"La URL ya existe en sources.yaml:\n{url}"
    )


sources.append({
    "name": name,
    "type": "html",
    "url": url,
    "newsletter_section": section,
    "include_if_url_contains": [
        item.strip()
        for item in keywords.split(",")
        if item.strip()
    ],
})


path.write_text(
    yaml.safe_dump(
        data,
        allow_unicode=True,
        sort_keys=False
    ),
    encoding="utf-8",
)


print(f"\nSitio agregado correctamente: {name}")

PY


  printf '\nActualizando datos después de agregar la fuente...\n'

  "$PYTHON_BIN" run.py

  printf '\nSitio agregado y datos actualizados.\n'
  printf 'Puede usar la opción 3 para revisar el dashboard.\n'
}


# =========================================================
# OPTION 2
# UPDATE DASHBOARD DATA
# =========================================================

update_dashboard_data() {

  printf '\n=== Actualizando datos ===\n\n'

  "$PYTHON_BIN" run.py

  printf '\nDatos actualizados correctamente.\n'
}


# =========================================================
# OPTION 3
# OPEN LOCAL DASHBOARD
# =========================================================

open_dashboard_preview() {

  printf '\n=== Actualizando datos y abriendo dashboard local ===\n\n'

  # Force the current dataset to match the final published state before opening the preview.
  "$PYTHON_BIN" run.py


  # Stop an existing local Streamlit process for this dashboard.
  pkill -f "streamlit run dashboard.py" 2>/dev/null || true


  # Start a fresh Streamlit instance with a fixed local address/port.
  nohup "$STREAMLIT_BIN" run dashboard.py \
    --server.headless true \
    --server.address 127.0.0.1 \
    --server.port 8501 \
    > streamlit.log 2>&1 &


  STREAMLIT_PID=$!


  printf 'Streamlit iniciado. PID: %s\n' "$STREAMLIT_PID"

  printf 'Esperando que el servidor local esté disponible...\n'


  # Give Streamlit a few seconds to initialize.
  sleep 4


  printf 'Abriendo http://127.0.0.1:8501\n'

  open "http://127.0.0.1:8501"


  printf '\nDashboard local abierto con datos actualizados.\n'
  printf 'Log disponible en: streamlit.log\n'
}


# =========================================================
# OPTION 4
# NEWSLETTER PREVIEW
# =========================================================

open_newsletter_preview() {

  printf '\n=== Generando preview final del boletín ===\n\n'

  # Regenerate the digest and HTML preview from the current data before opening it.
  "$PYTHON_BIN" run.py
  "$PYTHON_BIN" run.py --preview-email


  if [[ -f "data/email_preview.html" ]]; then

    open "data/email_preview.html"

    printf '\nPreview del boletín abierto con la versión actualizada.\n'

  else

    printf '\nERROR: No se encontró data/email_preview.html\n'

  fi
}


# =========================================================
# OPTION 5
# SEND NEWSLETTER
# =========================================================

send_newsletter() {

  printf '\n=== Enviar boletín ===\n\n'


  if [[ ! -f "data/special_recipients.csv" ]]; then

    printf 'ERROR: No existe data/special_recipients.csv\n'

    return
  fi


  "$PYTHON_BIN" run.py --send-email


  printf '\nProceso de envío terminado.\n'
}


# =========================================================
# OPTION 6
# SCHEDULE WEEKLY EMAIL
# =========================================================

schedule_email() {

  local schedule_time
  local hour
  local minute
  local cron_line
  local current_cron
  local confirm


  printf '\n=== Programar boletín semanal ===\n\n'


  read -r -p \
    "Hora de envío (HH:MM, 24 horas; por defecto 09:00): " \
    schedule_time


  schedule_time="${schedule_time:-09:00}"


  if [[ ! "$schedule_time" =~ ^([01][0-9]|2[0-3]):[0-5][0-9]$ ]]; then

    printf 'Hora no válida. Use HH:MM.\n'

    return
  fi


  hour="${schedule_time%%:*}"

  minute="${schedule_time##*:}"


  cron_line="$minute $hour * * 1 $PWD/run_send_email.sh --send"


  printf '\nProgramación propuesta:\n'
  printf 'Cada lunes a las %s\n\n' "$schedule_time"
  printf '%s\n\n' "$cron_line"


  read -r -p \
    "¿Agregar esta programación al crontab? [y/N]: " \
    confirm


  if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then

    printf 'Programación cancelada.\n'

    return
  fi


  current_cron="$(crontab -l 2>/dev/null || true)"


  if printf '%s\n' "$current_cron" | grep -Fqx "$cron_line"; then

    printf 'Esta programación ya existe.\n'

    return
  fi


  {
    printf '%s\n' "$current_cron"
    printf '%s\n' "$cron_line"

  } | crontab -


  printf 'Programación guardada correctamente en crontab.\n'
}


# =========================================================
# NON-INTERACTIVE EMAIL MODE
# Used by cron:
#
# run_send_email.sh --send
# =========================================================

if [[ "${1:-}" == "--send" ]]; then

  exec "$PYTHON_BIN" run.py --send-email

fi


# =========================================================
# INTERACTIVE MENU
# =========================================================

while true; do

  show_menu

  read -r -p "Seleccione una opción: " option


  case "$option" in

    1)

      add_website
      ;;


    2)

      update_dashboard_data
      ;;


    3)

      open_dashboard_preview
      ;;


    4)

      open_newsletter_preview
      ;;


    5)

      send_newsletter
      ;;


    6)

      schedule_email
      ;;


    q|Q)

      printf '\nSalida.\n'

      exit 0
      ;;


    *)

      printf '\nOpción no válida.\n'
      ;;

  esac

done