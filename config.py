"""Central configuration: environment variables first, then Streamlit secrets."""
import os


def get(key: str, default: str = "") -> str:
    val = os.environ.get(key)
    if val:
        return val
    try:
        import streamlit as st  # optional at import time so backend can be tested headless

        if key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        pass
    return default


def base_url() -> str:
    return get("APP_BASE_URL", "http://localhost:8501").rstrip("/")


def oauth_redirect_uri() -> str:
    # Must exactly match the redirect URI registered with Google / GitHub.
    return get("OAUTH_REDIRECT_URI", base_url() + "/")
