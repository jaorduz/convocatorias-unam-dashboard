#!/bin/bash

echo "=== Starting update ==="

# Ir al directorio del proyecto (AJUSTA RUTA)
cd /Users/lagrange/Documents/GithubIEEE/AgentsJO/public/convocatorias-unam-dashboard || exit

# Activar entorno (si usas conda o venv, ajusta)
# source ~/miniconda3/bin/activate calls-agent

echo "=== Running scraper ==="
# python run.py
python run.py --send-email

echo "=== Preparing git ==="
git add data/calls.csv data/digest.md

# Commit solo si hay cambios
git diff --cached --quiet || git commit -m "Auto update calls $(date)"

echo "=== Pull latest changes (safe rebase) ==="
git pull --rebase origin main

echo "=== Push changes ==="
git push origin main

echo "=== Restart dashboard locally ==="
# Matar proceso previo de streamlit (opcional)
pkill -f "streamlit run dashboard.py"

# Levantar dashboard
nohup streamlit run dashboard.py > streamlit.log 2>&1 &

echo "=== Done ==="