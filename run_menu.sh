#!/usr/bin/env bash
# Interactive wrapper for:
# - Funding calls sources
# - Dashboard updates
# - Local Streamlit preview
# - Newsletter preview
# - Newsletter sending
# - Weekly scheduling

# ======================================================================
# Todas las llamdas corran en WSl tambien
# ======================================================================
if ! command -v open >/dev/null 2>&1; then
  open() {
    if grep -qi microsoft /proc/version 2>/dev/null; then
      case "$1" in
        http://*|https://*) cmd.exe /c start "" "$1" ;;
        *) explorer.exe "$(wslpath -w "$(realpath "$1")")" || true ;;
      esac
    else
      xdg-open "$1"
    fi
  }
fi

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

STREAMLIT_PID_FILE=".streamlit_preview.pid"


stop_managed_dashboard_preview() {
  local managed_pid
  local process_command
  local process_state
  local attempt

  [[ -f "$STREAMLIT_PID_FILE" ]] || return 0
  read -r managed_pid < "$STREAMLIT_PID_FILE"
  rm -f "$STREAMLIT_PID_FILE"

  if ! [[ "$managed_pid" =~ ^[0-9]+$ ]]; then
    printf 'PID inválido en %s; se eliminó el archivo obsoleto.\n' "$STREAMLIT_PID_FILE"
    return 0
  fi

  process_command="$(ps -p "$managed_pid" -o command= 2>/dev/null || true)"
  case "$process_command" in
    *"streamlit run dashboard.py"*) ;;
    *)
      printf 'El PID guardado ya no corresponde a este preview; no se terminó ningún proceso.\n'
      return 0
      ;;
  esac

  printf 'Cerrando el preview anterior (PID %s)...\n' "$managed_pid"
  kill -CONT "$managed_pid" 2>/dev/null || true
  kill -TERM "$managed_pid" 2>/dev/null || true

  for attempt in {1..10}; do
    process_state="$(ps -p "$managed_pid" -o state= 2>/dev/null | tr -d ' ' || true)"
    [[ -z "$process_state" || "$process_state" == Z* ]] && return 0
    sleep 1
  done

  process_command="$(ps -p "$managed_pid" -o command= 2>/dev/null || true)"
  case "$process_command" in
    *"streamlit run dashboard.py"*) kill -KILL "$managed_pid" 2>/dev/null || true ;;
  esac
}


read_publish_to() {
  local target_variable="$1"
  local mode="${2:-default}"
  local choice
  local selected

  if [[ "$mode" == "remove" ]]; then
    printf '\nRetirar de:\n'
  else
    printf '\nPublicar en:\n'
  fi
  printf '1) Solo dashboard\n'
  printf '2) Solo boletín\n'
  printf '3) Ambos (por defecto)\n'
  if [[ "$mode" == "keep" ]]; then
    read -r -p "Seleccione destino [Enter conserva actuales]: " choice
  else
    read -r -p "Seleccione destino [3]: " choice
  fi

  if [[ -z "$choice" && "$mode" == "keep" ]]; then
    selected=""
  else
    case "${choice:-3}" in
    1) selected="dashboard" ;;
    2) selected="newsletter" ;;
    3) selected="dashboard,newsletter" ;;
    *)
      printf 'Opción de destino no válida.\n'
      return 1
      ;;
      esac
      fi

  printf -v "$target_variable" '%s' "$selected"
}


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
  printf '7) Administrar avisos y recursos\n'
  printf '8) Publicar actualización web en GitHub\n'
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


add_notice() {

  local title
  local category
  local message
  local source
  local link
  local poster
  local details
  local publish_to

  printf '\n=== Agregar aviso ===\n\n'

  read -r -p "Título del aviso: " title
  read -r -p "Categoría (ej. Reconocimiento, Capacitación, Convocatoria, Evento): " category
  read -r -p "Descripción o detalle del aviso: " message
  read -r -p "Fuente o dependencia: " source
  read -r -p "URL del sitio/web oficial (opcional): " link
  read -r -p "URL de póster o imagen PNG (opcional): " poster
  read -r -p "Más detalles o texto extra (opcional): " details

  if [[ -z "$title" || -z "$message" ]]; then
    printf '\nERROR: Se requieren título y descripción del aviso.\n'
    return
  fi

  if [[ -z "$link" && -z "$poster" ]]; then
    printf '\nERROR: Debe indicar al menos una URL de sitio o un póster/imagen.\n'
    return
  fi

  read_publish_to publish_to || return 0
  if [[ "$publish_to" == *newsletter* && -z "$link" ]]; then
    printf '\nERROR: Para publicar el aviso en el boletín se requiere una URL del sitio.\n'
    return
  fi

  "$PYTHON_BIN" - "$title" "$category" "$message" "$source" "$link" "$poster" "$details" "$publish_to" <<'PY'

import sys
from pathlib import Path
import yaml


title, category, message, source, link, poster, details, publish_to = sys.argv[1:]
path = Path("data/editorial_cards.yaml")

data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {"cards": []}
if data is None:
    data = {"cards": []}

cards = data.setdefault("cards", [])

entry = {
    "title": title.strip(),
    "category": category.strip() or "Aviso",
    "message": message.strip(),
    "source": source.strip() or "Fuente",
    "label": "Ver aviso",
    "publish_to": publish_to.split(","),
}
if link.strip():
    entry["link"] = link.strip()
if poster.strip():
    entry["poster"] = poster.strip()
if details.strip():
    entry["details"] = details.strip()

cards.append(entry)

path.write_text(
    yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
    encoding="utf-8",
)

print(f"\nAviso agregado correctamente: {title}")
PY

  printf '\nActualizando datos del dashboard y del boletín...\n'

  "$PYTHON_BIN" run.py

  printf '\nAviso agregado y datos actualizados.\n'
  printf 'Puede usar la opción 3 para revisar el dashboard y la opción 4 para revisar el boletín.\n'
}


edit_notice() {

  local idx
  local publish_to

  if [[ ! -f "data/editorial_cards.yaml" ]]; then
    printf '\nNo hay avisos registrados aún.\n'
    return
  fi

  "$PYTHON_BIN" - <<'PY'
import yaml
from pathlib import Path

path = Path('data/editorial_cards.yaml')
try:
    data = yaml.safe_load(path.read_text(encoding='utf-8')) or {'cards': []}
except FileNotFoundError:
    print('\nNo hay avisos registrados aún.')
    raise SystemExit(0)

cards = data.get('cards') or []
if not cards:
    print('\nNo hay avisos registrados aún.')
    raise SystemExit(0)

print('\nAvisos actuales:\n')
for i, card in enumerate(cards, start=1):
    print(f"{i}) {card.get('title', 'Sin título')} [{card.get('category', 'Aviso')}]")
PY

  read -r -p "\nNúmero del aviso a editar (o q para volver al menú principal): " idx
  [[ "$idx" == "q" ]] && return 0

  if ! [[ "$idx" =~ ^[0-9]+$ ]]; then
    printf 'Debes ingresar un número válido.\n'
    return
  fi

  "$PYTHON_BIN" - "$idx" <<'PY'
import sys
import yaml
from pathlib import Path

idx = int(sys.argv[1])
path = Path('data/editorial_cards.yaml')
data = yaml.safe_load(path.read_text(encoding='utf-8')) or {'cards': []}
cards = data.get('cards') or []

if not (1 <= idx <= len(cards)):
    print('Número fuera de rango.')
    raise SystemExit(1)

card = cards[idx - 1]
print(f'\nEditando: {card.get("title", "Sin título")}')
PY

  read -r -p "Título [$(grep -A1000 "cards:" data/editorial_cards.yaml | grep "title:" | head -$idx | tail -1 | sed 's/.*title: //' | sed 's/ *$//')]: " title
  read -r -p "Categoría: " category
  read -r -p "Descripción: " message
  read -r -p "Fuente: " source
  read -r -p "URL del sitio: " link
  read -r -p "URL del póster (opcional): " poster
  read -r -p "Detalles adicionales (opcional): " details
  read -r -p "Texto del botón: " label

  read_publish_to publish_to keep || return 0

  "$PYTHON_BIN" - "$idx" "$title" "$category" "$message" "$source" "$link" "$poster" "$details" "$label" "$publish_to" <<'PY' || return 0
import sys
import yaml
from pathlib import Path
from content_publication import publication_targets

idx, title, category, message, source, link, poster, details, label, publish_to = sys.argv[1:]
idx = int(idx)
path = Path('data/editorial_cards.yaml')
data = yaml.safe_load(path.read_text(encoding='utf-8')) or {'cards': []}
cards = data.get('cards') or []

if not (1 <= idx <= len(cards)):
    print('Número fuera de rango.')
    raise SystemExit(1)

card = cards[idx - 1]

if title.strip():
    card['title'] = title.strip()
if category.strip():
    card['category'] = category.strip()
if message.strip():
    card['message'] = message.strip()
if source.strip():
    card['source'] = source.strip()
if link.strip():
    card['link'] = link.strip()
if poster.strip():
    card['poster'] = poster.strip()
if details.strip():
    card['details'] = details.strip()
if label.strip():
    card['label'] = label.strip()
if publish_to.strip():
    card['publish_to'] = publish_to.split(',')
if 'newsletter' in publication_targets(card) and not str(card.get('link', '')).strip():
    print('ERROR: Para publicar el aviso en el boletín se requiere una URL del sitio.')
    raise SystemExit(1)

path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding='utf-8')
print(f'\nAviso #{idx} actualizado correctamente.')
PY

  printf '\nActualizando datos del dashboard y del boletín...\n'
  "$PYTHON_BIN" run.py

  printf '\nEdición del aviso finalizada.\n'
}


delete_notice() {

  local idx
  local publish_to

  if [[ ! -f "data/editorial_cards.yaml" ]]; then
    printf '\nNo hay avisos registrados aún.\n'
    return
  fi

  "$PYTHON_BIN" - <<'PY'
import yaml
from pathlib import Path

path = Path('data/editorial_cards.yaml')
try:
    data = yaml.safe_load(path.read_text(encoding='utf-8')) or {'cards': []}
except FileNotFoundError:
    print('\nNo hay avisos registrados aún.')
    raise SystemExit(0)

cards = data.get('cards') or []
if not cards:
    print('\nNo hay avisos registrados aún.')
    raise SystemExit(0)

print('\nAvisos actuales:\n')
for i, card in enumerate(cards, start=1):
    print(f"{i}) {card.get('title', 'Sin título')} [{card.get('category', 'Aviso')}]")
PY

  read -r -p "\nNúmero del aviso a eliminar (o q para volver al menú principal): " idx
  [[ "$idx" == "q" ]] && return 0

  if ! [[ "$idx" =~ ^[0-9]+$ ]]; then
    printf 'Debes ingresar un número válido.\n'
    return
  fi

  read_publish_to publish_to remove || return 0

  "$PYTHON_BIN" - "$idx" "$publish_to" <<'PY'
import sys
import yaml
from pathlib import Path
from content_publication import publication_targets

idx = int(sys.argv[1])
remove_targets = sys.argv[2].split(',')
path = Path('data/editorial_cards.yaml')
data = yaml.safe_load(path.read_text(encoding='utf-8')) or {'cards': []}
cards = data.get('cards') or []

if not (1 <= idx <= len(cards)):
    print('Número fuera de rango.')
    raise SystemExit(1)

card = cards[idx - 1]
targets = publication_targets(card)
remaining_targets = [target for target in targets if target not in remove_targets]
if remaining_targets:
  card['publish_to'] = remaining_targets
  message = f"Aviso despublicado de: {', '.join(remove_targets)}"
else:
  removed = cards.pop(idx - 1)
  message = f"Aviso eliminado: {removed.get('title', 'Sin título')}"
path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding='utf-8')
print(f'\n{message}')
PY

  printf '\nActualizando datos del dashboard y del boletín...\n'
  "$PYTHON_BIN" run.py

  printf '\nOperación de retirada del aviso finalizada.\n'
}


# =========================================================
# OPTION 10
# ADD RESOURCE (INFORMACIÓN Y RECURSOS)
# =========================================================

add_resource() {

  local title
  local category
  local description
  local source
  local link
  local resource_type
  local publish_to

  printf '\n=== Agregar recurso a Información y Recursos ===\n\n'

  read -r -p "Título del recurso: " title
  read -r -p "Tipo de recurso (ej. Tutorial, Guía, Herramienta, Capacitación): " resource_type
  read -r -p "Descripción del recurso: " description
  read -r -p "Fuente o dependencia: " source
  read -r -p "URL del recurso: " link

  if [[ -z "$title" || -z "$description" || -z "$link" ]]; then
    printf '\nERROR: Se requieren título, descripción y URL del recurso.\n'
    return
  fi

  read_publish_to publish_to || return 0

  "$PYTHON_BIN" - "$title" "$resource_type" "$description" "$source" "$link" "$publish_to" <<'PY'

import sys
from pathlib import Path
import yaml


title, resource_type, description, source, link, publish_to = sys.argv[1:]
path = Path("data/recursos.yaml")

data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {"resources": []}
if data is None:
    data = {"resources": []}

resources = data.setdefault("resources", [])

entry = {
    "title": title.strip(),
    "type": resource_type.strip() or "Recurso",
    "message": description.strip(),
    "source": source.strip() or "Fuente",
    "link": link.strip(),
    "label": "Ver recurso",
    "publish_to": publish_to.split(","),
}

resources.append(entry)

path.write_text(
    yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
    encoding="utf-8",
)

print(f"\nRecurso agregado correctamente: {title}")
PY

  printf '\nActualizando datos del dashboard y del boletín...\n'

  "$PYTHON_BIN" run.py

  printf '\nRecurso agregado y datos actualizados.\n'
  printf 'Puede usar la opción 3 para revisar el dashboard y la opción 4 para revisar el boletín.\n'
}


# =========================================================
# OPTION 11
# EDIT RESOURCE (INFORMACIÓN Y RECURSOS)
# =========================================================

edit_resource() {

  local idx
  local publish_to

  if [[ ! -f "data/recursos.yaml" ]]; then
    printf '\nNo hay recursos registrados aún.\n'
    return
  fi

  "$PYTHON_BIN" - <<'PY'
import yaml
from pathlib import Path

path = Path('data/recursos.yaml')
try:
    data = yaml.safe_load(path.read_text(encoding='utf-8')) or {'resources': []}
except FileNotFoundError:
    print('\nNo hay recursos registrados aún.')
    raise SystemExit(0)

resources = data.get('resources') or []
if not resources:
    print('\nNo hay recursos registrados aún.')
    raise SystemExit(0)

print('\nRecursos actuales:\n')
for i, resource in enumerate(resources, start=1):
    print(f"{i}) {resource.get('title', 'Sin título')} [{resource.get('type', 'Recurso')}]")
PY

  read -r -p "\nNúmero del recurso a editar (o q para volver al menú principal): " idx
  [[ "$idx" == "q" ]] && return 0

  if ! [[ "$idx" =~ ^[0-9]+$ ]]; then
    printf 'Debes ingresar un número válido.\n'
    return
  fi

  read -r -p "Título: " title
  read -r -p "Tipo de recurso: " type
  read -r -p "Descripción: " message
  read -r -p "Fuente: " source
  read -r -p "URL del recurso: " link
  read -r -p "Texto del botón: " label

  read_publish_to publish_to keep || return 0

  "$PYTHON_BIN" - "$idx" "$title" "$type" "$message" "$source" "$link" "$label" "$publish_to" <<'PY' || return 0
import sys
import yaml
from pathlib import Path
from content_publication import publication_targets

idx, title, resource_type, message, source, link, label, publish_to = sys.argv[1:]
idx = int(idx)
path = Path('data/recursos.yaml')
data = yaml.safe_load(path.read_text(encoding='utf-8')) or {'resources': []}
resources = data.get('resources') or []

if not (1 <= idx <= len(resources)):
    print('Número fuera de rango.')
    raise SystemExit(1)

resource = resources[idx - 1]

if title.strip():
    resource['title'] = title.strip()
if resource_type.strip():
    resource['type'] = resource_type.strip()
if message.strip():
    resource['message'] = message.strip()
if source.strip():
    resource['source'] = source.strip()
if link.strip():
    resource['link'] = link.strip()
if label.strip():
    resource['label'] = label.strip()
if publish_to.strip():
    resource['publish_to'] = publish_to.split(',')
if 'newsletter' in publication_targets(resource) and not str(resource.get('link', '')).strip():
    print('ERROR: Para publicar el recurso en el boletín se requiere una URL.')
    raise SystemExit(1)

path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding='utf-8')
print(f'\nRecurso #{idx} actualizado correctamente.')
PY

  printf '\nActualizando datos del dashboard y del boletín...\n'
  "$PYTHON_BIN" run.py

  printf '\nEdición del recurso finalizada.\n'
}


# =========================================================
# OPTION 12
# DELETE RESOURCE (INFORMACIÓN Y RECURSOS)
# =========================================================

delete_resource() {

  local idx
  local publish_to

  if [[ ! -f "data/recursos.yaml" ]]; then
    printf '\nNo hay recursos registrados aún.\n'
    return
  fi

  "$PYTHON_BIN" - <<'PY'
import yaml
from pathlib import Path

path = Path('data/recursos.yaml')
try:
    data = yaml.safe_load(path.read_text(encoding='utf-8')) or {'resources': []}
except FileNotFoundError:
    print('\nNo hay recursos registrados aún.')
    raise SystemExit(0)

resources = data.get('resources') or []
if not resources:
    print('\nNo hay recursos registrados aún.')
    raise SystemExit(0)

print('\nRecursos actuales:\n')
for i, resource in enumerate(resources, start=1):
    print(f"{i}) {resource.get('title', 'Sin título')} [{resource.get('type', 'Recurso')}]")
PY

  read -r -p "\nNúmero del recurso a eliminar (o q para volver al menú principal): " idx
  [[ "$idx" == "q" ]] && return 0

  if ! [[ "$idx" =~ ^[0-9]+$ ]]; then
    printf 'Debes ingresar un número válido.\n'
    return
  fi

  read_publish_to publish_to remove || return 0

  "$PYTHON_BIN" - "$idx" "$publish_to" <<'PY'
import sys
import yaml
from pathlib import Path
from content_publication import publication_targets

idx = int(sys.argv[1])
remove_targets = sys.argv[2].split(',')
path = Path('data/recursos.yaml')
data = yaml.safe_load(path.read_text(encoding='utf-8')) or {'resources': []}
resources = data.get('resources') or []

if not (1 <= idx <= len(resources)):
    print('Número fuera de rango.')
    raise SystemExit(1)

resource = resources[idx - 1]
targets = publication_targets(resource)
remaining_targets = [target for target in targets if target not in remove_targets]
if remaining_targets:
    resource['publish_to'] = remaining_targets
    message = f"Recurso despublicado de: {', '.join(remove_targets)}"
else:
    removed = resources.pop(idx - 1)
    message = f"Recurso eliminado: {removed.get('title', 'Sin título')}"
path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding='utf-8')
print(f'\n{message}')
PY

  printf '\nActualizando datos del dashboard y del boletín...\n'
  "$PYTHON_BIN" run.py

  printf '\nOperación de retirada del recurso finalizada.\n'
}


archive_content() {
  local content_type="$1"
  local data_file
  local collection_key
  local archive_file
  local item_label
  local idx

  case "$content_type" in
    1)
      data_file="data/editorial_cards.yaml"
      collection_key="cards"
      archive_file="data/archive/avisos.yaml"
      item_label="aviso"
      ;;
    2)
      data_file="data/recursos.yaml"
      collection_key="resources"
      archive_file="data/archive/recursos.yaml"
      item_label="recurso"
      ;;
    *)
      printf '\nTipo de contenido no válido.\n'
      return 1
      ;;
  esac

  if ! "$PYTHON_BIN" - "$data_file" "$collection_key" <<'PY'
import sys
import yaml
from pathlib import Path

path = Path(sys.argv[1])
collection_key = sys.argv[2]
if not path.exists():
    print('\nNo hay elementos para archivar.')
    raise SystemExit(1)

data = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
items = data.get(collection_key, [])
if not items:
    print('\nNo hay elementos para archivar.')
    raise SystemExit(1)

print('\nElementos actuales:\n')
for index, item in enumerate(items, start=1):
    print(f"{index}) {item.get('title', 'Sin título')}")
PY
  then
    return 0
  fi

  read -r -p "\nNúmero del ${item_label} a archivar (o q para volver al menú principal): " idx
  [[ "$idx" == "q" ]] && return 0
  if ! [[ "$idx" =~ ^[0-9]+$ ]]; then
    printf 'Debes ingresar un número válido.\n'
    return 0
  fi

  if ! "$PYTHON_BIN" - "$data_file" "$collection_key" "$archive_file" "$idx" <<'PY'
import sys
import yaml
from pathlib import Path

data_path = Path(sys.argv[1])
collection_key = sys.argv[2]
archive_path = Path(sys.argv[3])
index = int(sys.argv[4]) - 1

data = yaml.safe_load(data_path.read_text(encoding='utf-8')) or {}
items = data.get(collection_key, [])
if not isinstance(items, list) or not (0 <= index < len(items)):
    print('Número fuera de rango.')
    raise SystemExit(1)

archive_data = {}
if archive_path.exists():
    archive_data = yaml.safe_load(archive_path.read_text(encoding='utf-8')) or {}
archive_items = archive_data.setdefault(collection_key, [])
if not isinstance(archive_items, list):
    print(f'ERROR: Formato inválido en {archive_path}.')
    raise SystemExit(1)

item = items.pop(index)
archive_items.append(item)
archive_path.parent.mkdir(parents=True, exist_ok=True)
archive_path.write_text(
    yaml.safe_dump(archive_data, allow_unicode=True, sort_keys=False),
    encoding='utf-8',
)
data_path.write_text(
    yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
    encoding='utf-8',
)
print(f"\nArchivado: {item.get('title', 'Sin título')} -> {archive_path}")
PY
  then
    return 0
  fi

  printf '\nActualizando datos del dashboard y del boletín...\n'
  "$PYTHON_BIN" run.py
}


manage_content() {
  local content_type
  local action

  printf '\n=== Administrar avisos y recursos ===\n'
  printf '1) Aviso\n'
  printf '2) Recurso (Información y Recursos)\n'
  printf 'q) Volver al menú principal\n'
  read -r -p "Seleccione tipo de contenido: " content_type
  [[ "$content_type" == "q" ]] && return 0

  printf '\n1) Agregar\n'
  printf '2) Editar\n'
  printf '3) Eliminar o retirar de un canal\n'
  printf '4) Archivar\n'
  printf 'q) Volver al menú principal\n'
  read -r -p "Seleccione acción: " action

  case "$content_type:$action" in
    *:q) return 0 ;;
    1:1) add_notice ;;
    1:2) edit_notice ;;
    1:3) delete_notice ;;
    1:4) archive_content "$content_type" ;;
    2:1) add_resource ;;
    2:2) edit_resource ;;
    2:3) delete_resource ;;
    2:4) archive_content "$content_type" ;;
    *) printf '\nSelección no válida.\n' ;;
  esac
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
#Sustituir open para poder modificar tambien en windows el preview
#===========================================================

open_url() {
  case "$(uname -s)" in
    Darwin) open "$1" ;;
    MINGW*|MSYS*|CYGWIN*) cmd.exe //c start "" "$1" ;;
    Linux) xdg-open "$1" ;;
  esac
}

# =========================================================
# OPTION 3
# OPEN LOCAL DASHBOARD
# =========================================================

open_dashboard_preview() {
  local preview_port
  local attempt

  printf '\n=== Actualizando datos y abriendo dashboard local ===\n\n'

  # Force the current dataset to match the final published state before opening the preview.
  "$PYTHON_BIN" run.py

  stop_managed_dashboard_preview

  if ! preview_port="$("$PYTHON_BIN" - <<'PY'
import socket

with socket.socket() as probe:
    try:
        probe.bind(("127.0.0.1", 8501))
        print(8501)
    except OSError:
        for candidate in range(8502, 8601):
            with socket.socket() as probe:
                try:
                    probe.bind(("127.0.0.1", candidate))
                except OSError:
                    continue
                print(candidate)
                break
        else:
            raise SystemExit("No hay puertos libres entre 8501 y 8600")
PY
)"; then
    printf '\nERROR: No se encontró un puerto libre para Streamlit.\n'
    return 1
  fi

  printf 'Iniciando Streamlit en el puerto %s...\n' "$preview_port"

  nohup "$STREAMLIT_BIN" run dashboard.py \
    --server.headless true \
    --server.address 127.0.0.1 \
    --server.port "$preview_port" \
    > streamlit.log 2>&1 &


  STREAMLIT_PID=$!
  printf '%s\n' "$STREAMLIT_PID" > "$STREAMLIT_PID_FILE"


  printf 'Streamlit iniciado. PID: %s\n' "$STREAMLIT_PID"

  printf 'Esperando que el servidor local esté disponible...\n'
  for attempt in {1..30}; do
    if curl --fail --silent "http://127.0.0.1:${preview_port}/_stcore/health" >/dev/null; then
      break
    fi
    if ! kill -0 "$STREAMLIT_PID" 2>/dev/null; then
      rm -f "$STREAMLIT_PID_FILE"
      printf '\nERROR: Streamlit terminó antes de estar disponible. Últimas líneas del log:\n'
      tail -n 30 streamlit.log
      return 1
    fi
    sleep 1
  done

  if ! curl --fail --silent "http://127.0.0.1:${preview_port}/_stcore/health" >/dev/null; then
    stop_managed_dashboard_preview
    printf '\nERROR: Streamlit no respondió a tiempo. Últimas líneas del log:\n'
    tail -n 30 streamlit.log
    return 1
  fi

  printf 'Abriendo http://127.0.0.1:%s\n' "$preview_port"

  open_url "http://127.0.0.1:${preview_port}"

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


publish_dashboard_to_github() {
  local branch
  local commit_message
  local confirm
  local -a publish_files=(
    .gitignore
    dashboard.py
    readme.md
    content_publication.py
    data/calls.csv
    data/editorial_cards.yaml
    data/recursos.yaml
  )

  printf '\n=== Publicar actualización web en GitHub ===\n\n'

  if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    printf 'ERROR: Este directorio no pertenece a un repositorio Git.\n'
    return 0
  fi

  if ! git diff --cached --quiet; then
    printf 'ERROR: Hay cambios staged previamente. Confírmalos o retíralos antes de publicar.\n'
    return 0
  fi

  if ! git remote get-url origin >/dev/null 2>&1; then
    printf 'ERROR: No está configurado el remoto Git "origin".\n'
    return 0
  fi

  branch="$(git branch --show-current)"
  if [[ -z "$branch" ]]; then
    printf 'ERROR: No se pudo determinar la rama actual.\n'
    return 0
  fi

  printf 'Repositorio: %s\n' "$(git remote get-url origin)"
  printf 'Rama: %s\n\n' "$branch"
  printf 'Archivos que se incluirán:\n'
  printf ' - %s\n' "${publish_files[@]}"
  printf '\nSe excluirán archivos generados y otros cambios fuera de esta lista.\n'
  read -r -p 'Mensaje del commit [Actualizar dashboard web]: ' commit_message
  commit_message="${commit_message:-Actualizar dashboard web}"
  read -r -p '¿Confirmas crear el commit y enviarlo a GitHub? [y/N]: ' confirm

  if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    printf 'Publicación cancelada; no se modificó el índice de Git.\n'
    return 0
  fi

  if ! git add -- "${publish_files[@]}"; then
    printf 'ERROR: No se pudieron preparar los archivos para publicar.\n'
    return 0
  fi

  if git diff --cached --quiet; then
    printf 'No hay cambios en los archivos seleccionados para publicar.\n'
    git restore --staged -- "${publish_files[@]}"
    return 0
  fi

  printf '\nCambios que se publicarán:\n'
  git diff --cached --stat

  if ! git commit -m "$commit_message"; then
    printf 'ERROR: No se creó el commit; los cambios permanecen locales.\n'
    git restore --staged -- "${publish_files[@]}"
    return 0
  fi

  if ! git push -u origin "$branch"; then
    printf 'ERROR: El commit quedó local, pero no se pudo enviar a GitHub.\n'
    printf 'Revisa la conexión, autenticación y si la rama remota tiene cambios nuevos.\n'
    return 0
  fi

  printf '\nActualización enviada a GitHub. Si Streamlit Cloud está conectado a esta rama, iniciará el despliegue automáticamente.\n'
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


    7)

      manage_content
      ;;


    8)

      publish_dashboard_to_github
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