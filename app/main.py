import streamlit as st

st.set_page_config(
    page_title="MOGESTpy UI",
    page_icon="💧",
    layout="wide",
)

st.title("💧 MOGESTpy — Plataforma de Modelagem Hidrológica")
st.markdown(
    """
    Interface para modelagem do processo chuva-vazão baseada na biblioteca **mogestpy**.

    Selecione um módulo no menu lateral:

    | Módulo | Descrição |
    |--------|-----------|
    | **Simulação SMAP** | Modelo hidrológico diário (`SmapD`) e mensal (`SmapM`) para uma bacia |
    | **Rede Hidrológica** | Propagação SMAP + Muskingum em rede de subcatchments |
    """
)
