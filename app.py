import os

import streamlit as st

st.set_page_config(
    page_title="Palantir 博客归档",
    page_icon="📰",
    layout="wide",
)

# The archive is a static site with relative JSON and content URLs. Streamlit does
# not serve those repository files, so embed the deployed GitHub Pages site.
ARCHIVE_URL = os.getenv("ARCHIVE_URL", "https://fushanua.github.io/PBA/index.html")

# Hide Streamlit chrome and make the component iframe use the browser viewport.
st.markdown(
    """
<style>
    #MainMenu, footer, header { visibility: hidden; }
    .stApp { padding: 0 !important; margin: 0 !important; }
    .block-container { padding: 0 !important; max-width: 100% !important; }
    .st-emotion-cache-1wmy9hl { gap: 0; }
    iframe { border: none; }
    [data-testid="stIFrame"] {
        display: block;
        width: 100%;
        height: calc(100vh - 16px) !important;
        min-height: 640px;
    }
</style>
""",
    unsafe_allow_html=True,
)

st.iframe(
    ARCHIVE_URL,
    width="stretch",
    height="stretch",
)
