# Convocatorias Dashboard & Weekly Digest

This project collects funding calls, exposes a Streamlit dashboard, and can send a weekly email digest.

Quick setup

1. Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Provide environment variables (prefer a `.env` file or system env):

- `EMAIL_USER` — sender email address
- `EMAIL_PASS` — SMTP password or app password
- Optional: `EMAIL_RECIPIENTS` — comma-separated recipients

Run dashboard locally

```bash
streamlit run dashboard.py
```

Send email manually

```bash
python run.py --send-email
```

Scheduling weekly (cron)

Edit your crontab (`crontab -e`) and add this line to run every Monday at 09:00 (adjust paths):

```
0 9 * * 1 /Users/lagrange/Documents/GithubIEEE/AgentsJO/public/convocatorias-unam-dashboard/run_send_email.sh >> /tmp/convocatorias_send.log 2>&1
```

Alternatives

- On macOS, you can create a `launchd` job instead of cron for better integration.
- Or embed `APScheduler` into a long-running process if you prefer Python-managed scheduling.

Notes

- The dashboard improvements include an Altair bar chart and sidebar filters.
- Keep `EMAIL_PASS` secure (use system keychain or environment configuration in production).
# Sistema Institucional de Monitoreo de Convocatorias
### Facultad de Estudios Superiores Acatlán – UNAM

[licenseBDG:](https://img.shields.io/badge/License-CC-orange?style=plastic)
[license:](https://creativecommons.org/licenses/by-nc-sa/3.0/deed.en)

[mywebsiteBDG]:https://img.shields.io/badge/website-jaorduz.github.io-0abeeb?style=plastic
[mywebsite]: https://jaorduz.github.io/

[mygithubBDG-jaorduz]: https://img.shields.io/badge/jaorduz-repos-blue?logo=github&label=jaorduz&style=plastic
[mygithub-jaorduz]: https://github.com/jaorduz/

[mygithubBDG-jaorduc]: https://img.shields.io/badge/jaorduc-repos-blue?logo=github&label=jaorduc&style=plastic 
[mygithub-jaorduc]: https://github.com/jaorduc/

[myXprofileBDG]: https://img.shields.io/static/v1?label=Follow&message=jaorduc&color=2ea44f&style=plastic&logo=X&logoColor=black
[myXprofile]:https://twitter.com/jaorduc


[![website - jaorduz.github.io][mywebsiteBDG]][mywebsite]
[![Github][mygithubBDG-jaorduz]][mygithub-jaorduz]
[![Github][mygithubBDG-jaorduc]][mygithub-jaorduc]
[![Follow @jaorduc][myXprofileBDG]][myXprofile]


![Version](https://img.shields.io/badge/version-1.0.0-blue)
![Python](https://img.shields.io/badge/python-3.11-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Status](https://img.shields.io/badge/status-stable-success)

[![DOI](https://zenodo.org/badge/1164379177.svg)](https://doi.org/10.5281/zenodo.19857397)


---

<p style="text-align:right; font-family:verdana;"><a href="mywebsiteBDG" style="color:#3364ff; text-decoration:none;">@Javier Orduz</a></p>    

---
Este repositorio contiene la información sobre el sitio [Sistema Institucional de Monitoreo de Convocatorias-FESAc-UNAM](https://smcfesacatlanunam.streamlit.app/)


<!-- ## Contents
1. [Introduction](#intro)
1. [Installing](#installing)
1. [References](#references) -->


# Convocatorias UNAM Dashboard (Interno)

Sistema automatizado para recolectar, normalizar, almacenar y publicar convocatorias (call for proposals/solicitations) con foco en México (español) y fuentes internacionales selectas.

## Componentes
- `run.py`: scraper + normalizador + SQLite + export (CSV/MD) + envío de correo (opcional).
- `sources.yaml`: listado de fuentes (HTML/RSS).
- `config.yaml`: keywords y settings (timeouts, max items, rutas de salida, etc.).
- `data/calls.csv`: dataset para el dashboard.
- `data/digest.md`: digest para correo.
- `dashboard.py`: Streamlit dashboard.
- `data/areas_estrategicas.csv`: keywords/pesos por línea estratégica.
- `data/divisiones_academicas.csv`: mapeo área → división.

## Requisitos
Python 3.11 recomendado (conda o venv).
Dependencias en `requirements.txt`.

## Setup local (Conda)
```bash
conda create -n calls-agent python=3.11 -y
conda activate calls-agent
pip install -r requirements.txt


```bibtex
@software{orduz_SIMC_2026,
  author       = {Orduz, Javier},
  title        = {{SIMC}: Sistema de Institucional de Monitoreo de Convocatorias},
  year         = 2026,
  version      = {1.0.0},
  publisher    = {Zenodo},
  doi          = {10.5281/zenodo.19857397},
  url          = {https://doi.org/10.5281/zenodo.19857397}
}
```