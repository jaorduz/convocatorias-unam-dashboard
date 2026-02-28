<!-- # Funding Radar Agent -->

<div id="header"><p style="color:#3364ff; text-align:center; font-weight:bold; font-family:verdana; font-size:25px;">Sistema de Monitoreo de Convocatorias </p></div>

[![Open this NB in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/drive/1aqs2CUJESGhbhRJ4tfW5U8bN4yr5FtL_){:target="_blank"}


[licenseBDG:](https://img.shields.io/badge/License-CC-orange?style=plastic){:target="_blank"}
[license:](https://creativecommons.org/licenses/by-nc-sa/3.0/deed.en){:target="_blank"}

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
[![CC License][licenseBDG]][license]

---

<p style="text-align:right; font-family:verdana;"><a href="mywebsiteBDG" style="color:#3364ff; text-decoration:none;">@Javier Orduz</a></p>    

---
Este repositorio contiene la información sobre el sitio [Sistema de Monitoreo de Convocatorias-FESAc-UNAM](https://smcfesacatlanunam.streamlit.app/){:target="_blank"} 


## Contents
1. [Introduction](#intro)
1. [Installing](#installing)
1. [References](#references)


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