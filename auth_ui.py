"""Login, registration, forgot-password and reset-password screens."""
import time

import streamlit as st

import auth_service as auth
import theme
from ui_common import flash, safe_call, show_flash


def _oauth_links() -> None:
    """Google/GitHub buttons. target=_top is required: Google refuses to render inside an iframe."""
    cache = st.session_state.setdefault("_oauth_urls", {})
    for provider, label in (("google", "Continue with Google"), ("github", "Continue with GitHub")):
        if not auth.provider_configured(provider):
            st.markdown(f'<span class="eb-oauth off">{label} (not configured)</span>', unsafe_allow_html=True)
            continue
        url, ts = cache.get(provider, (None, 0))
        if not url or time.time() - ts > 480:  # state tokens live 10 minutes
            try:
                url = auth.oauth_authorize_url(provider)
            except Exception:
                st.error("Sign-in is temporarily unavailable.")
                continue
            cache[provider] = (url, time.time())
        st.markdown(f'<a class="eb-oauth" href="{theme.esc(url)}" target="_top">{label}</a>', unsafe_allow_html=True)


def _start_session(user: dict, remember: bool) -> None:
    token = auth.create_session(user["id"], remember)
    st.session_state["user"] = user
    st.session_state["sid"] = token
    st.query_params.clear()
    st.query_params["sid"] = token
    st.session_state.pop("_oauth_urls", None)


def _shell(title: str, subtitle: str):
    _, mid, _ = st.columns([1, 1.4, 1])
    with mid:
        st.markdown('<div class="eb-brand">Edu<span>Bridge</span>-AI</div>', unsafe_allow_html=True)
        st.markdown(f"## {title}")
        st.caption(subtitle)
        show_flash()
    return mid


def login_view() -> None:
    mid = _shell("Welcome back", "Learn together. Teach each other. Grow faster.")
    with mid:
        with st.form("login_form"):
            email = st.text_input("Email address", placeholder="you@example.com")
            password = st.text_input("Password", type="password")  # built-in show/hide toggle
            remember = st.checkbox("Remember me (30 days)")
            submit = st.form_submit_button("Log in", type="primary", use_container_width=True)
        if submit:
            ok, user = safe_call(auth.authenticate, email, password)
            if ok:
                _start_session(user, remember)
                st.rerun()
        st.button("Forgot password?", key="to_forgot", on_click=lambda: st.session_state.update(auth_view="forgot"))
        st.markdown("<div class='eb-sub' style='text-align:center;margin:.6rem 0'>or</div>", unsafe_allow_html=True)
        _oauth_links()
        st.markdown("---")
        st.button("New here? Create an account", key="to_register", use_container_width=True,
                  on_click=lambda: st.session_state.update(auth_view="register"))


def register_view() -> None:
    mid = _shell("Create your account", "Join as a student or a tutor.")
    with mid:
        with st.form("register_form"):
            name = st.text_input("Full name")
            email = st.text_input("Email address")
            role_label = st.radio("I am a…", ["Student", "Tutor"], horizontal=True)
            pw = st.text_input("Password", type="password", help="At least 8 characters, with a letter and a number.")
            confirm = st.text_input("Confirm password", type="password")
            submit = st.form_submit_button("Create account", type="primary", use_container_width=True)
        if submit:
            ok, _ = safe_call(auth.register_user, name, email, pw, confirm, role_label.lower())
            if ok:
                flash("Account created! Log in with your email and password.")
                st.session_state["auth_view"] = "login"
                st.rerun()
        st.button("Already have an account? Log in", key="reg_to_login",
                  on_click=lambda: st.session_state.update(auth_view="login"))
        st.markdown("<div class='eb-sub' style='text-align:center'>or sign up with</div>", unsafe_allow_html=True)
        _oauth_links()
        st.caption("Google/GitHub sign-ups start as student accounts; you can switch type in Profile.")


def forgot_view() -> None:
    mid = _shell("Reset your password", "We'll email you a link that works for 60 minutes.")
    with mid:
        with st.form("forgot_form"):
            email = st.text_input("Email address")
            submit = st.form_submit_button("Send reset link", type="primary", use_container_width=True)
        if submit:
            ok, _ = safe_call(auth.request_password_reset, email)
            if ok:
                st.success("If an account exists for that email, a reset link is on its way.")
        st.button("Back to login", key="forgot_back", on_click=lambda: st.session_state.update(auth_view="login"))


def reset_view(token: str) -> None:
    mid = _shell("Choose a new password", "Pick something you haven't used before.")
    with mid:
        if auth.validate_reset_token(token) is None:
            st.error("This reset link is invalid or has expired.")
            if st.button("Request a new link"):
                st.query_params.clear()
                st.session_state["auth_view"] = "forgot"
                st.rerun()
            return
        with st.form("reset_form"):
            pw = st.text_input("New password", type="password")
            confirm = st.text_input("Confirm new password", type="password")
            submit = st.form_submit_button("Update password", type="primary", use_container_width=True)
        if submit:
            ok, _ = safe_call(auth.reset_password, token, pw, confirm)
            if ok:
                flash("Password updated. Please log in.")
                st.query_params.clear()
                st.session_state["auth_view"] = "login"
                st.rerun()


def render_auth() -> None:
    view = st.session_state.get("auth_view", "login")
    {"login": login_view, "register": register_view, "forgot": forgot_view}.get(view, login_view)()
