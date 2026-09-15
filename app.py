"""
Streamlit entrypoint - login gate plus the top header menu.

Pages:
  - RCA Investigations (rca_page.py): the RCA Categorization & Trend Tool.
  - OCCI Analytics (occi_page.py): operational close call reports that
    replace the client's manual "OCCs Tables and Graphs" workbook.
"""

import hmac
import os

import streamlit as st

st.set_page_config(page_title="RCA Categorization & Trend Tool", layout="wide")

# Hide Streamlit's own chrome (hamburger menu, "Deploy"/GitHub actions, running
# status widget, "Made with Streamlit" footer, top decoration bar) so the app
# reads as a standalone tool. The toolbar itself stays visible because the
# top navigation menu is rendered inside it.
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    [data-testid="stMainMenu"] {display: none;}
    [data-testid="stToolbarActions"] {display: none;}
    [data-testid="stAppDeployButton"] {display: none;}
    [data-testid="stDecoration"] {visibility: hidden;}
    [data-testid="stStatusWidget"] {visibility: hidden;}
    </style>
""", unsafe_allow_html=True)


def require_login():
    """Simple username/password gate. Credentials come from APP_USERNAME /
    APP_PASSWORD (env var locally, Streamlit secrets when deployed) - not
    hardcoded in source so they don't end up in git history."""
    if st.session_state.get("authenticated"):
        return

    st.title("RCA Categorization & Trend Tool")
    st.subheader("Sign in")
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in")

    expected_user = os.environ.get("APP_USERNAME", "")
    expected_pass = os.environ.get("APP_PASSWORD", "")

    if submitted:
        if not expected_user or not expected_pass:
            st.error("Login is not configured — set APP_USERNAME and APP_PASSWORD "
                      "in the app secrets.")
        elif (hmac.compare_digest(username, expected_user)
                and hmac.compare_digest(password, expected_pass)):
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Incorrect username or password.")

    st.stop()


require_login()

navigation = st.navigation(
    [
        st.Page("rca_page.py", title="RCA Investigations", url_path="rca", default=True),
        st.Page("occi_page.py", title="OCCI Analytics", url_path="occi"),
    ],
    position="top",
)
navigation.run()
