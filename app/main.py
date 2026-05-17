import sys
from pathlib import Path

# Ensure repo root is on sys.path so `app` and `core` are importable on
# Streamlit Cloud (where the package may not be installed via pip install .)
_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

import streamlit as st

st.set_page_config(
    page_title="Início",
    page_icon="💧",
    layout="wide",
)

st.title("💧 MOGESTpy — Plataforma de Modelagem Hidrológica")
st.markdown(
    """
    Interface para modelagem do processo chuva-vazão baseada na biblioteca
    [**mogestpy**](https://mogestpy.readthedocs.io/).

    Selecione um módulo no menu lateral:

    | Módulo | Descrição |
    |--------|-----------|
    | **Simulação SMAP** | Modelo hidrológico diário e mensal para uma bacia |
    | **Rede Hidrológica** | Propagação SMAP + Muskingum em rede de subcatchments |
    """
)
