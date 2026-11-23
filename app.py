"""EduBridge-AI entry point: routing, session handling, OAuth callback, sidebar navigation."""
import streamlit as st

st.set_page_config(page_title="EduBridge-AI", page_icon="🌉", layout="wide")

import auth_service as auth  # noqa: E402
import database as db  # noqa: E402
import services as svc  # noqa: E402
import theme  # noqa: E402
from auth_ui import render_auth, reset_view, _start_session  # noqa: E402
from ui_ai import render_ai  # noqa: E402
from ui_common import flash, show_flash  # noqa: E402
from ui_dashboard import render_dashboard, render_notifications  # noqa: E402
from ui_exchange import render_exchange  # noqa: E402
from ui_market import render_connections, render_find_tutors, render_requests  # noqa: E402
from ui_profile import render_profile  # noqa: E402

theme.inject()


@st.cache_resource
def _init_database() -> bool:
    db.init_db()
    return True


try:
    _init_database()
except db.DatabaseError as exc:
    st.error(f"{exc} If this keeps happening, check the database settings.")
    st.stop()


def _handle_oauth_callback() -> bool:
    """Process ?code=&state= (or ?error=) returned by Google/GitHub. Returns True if handled."""
    qp = st.query_params
    if "error" in qp and "state" in qp:
        flash("Sign-in was cancelled or denied. You can try again or use email and password.", "error")
    elif "code" in qp and "state" in qp:
        try:
            user = auth.oauth_complete(qp["state"], qp["code"])
        except auth.AuthError as exc:
            flash(str(exc), "error")
        except db.DatabaseError as exc:
            flash(str(exc), "error")
        else:
            _start_session(user, remember=False)
            return True
    else:
        return False
    st.query_params.clear()
    return True


def _current_user():
    sid = st.session_state.get("sid") or st.query_params.get("sid")
    try:
        user = auth.get_session_user(sid) if sid else None
    except db.DatabaseError:
        user = None
    if user:
        st.session_state["sid"] = sid
        st.session_state["user"] = user
    else:
        for k in ("sid", "user"):
            st.session_state.pop(k, None)
        if "sid" in st.query_params:
            del st.query_params["sid"]
    return user


def _logout() -> None:
    auth.delete_session(st.session_state.get("sid"))
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.query_params.clear()


# ---- routing ----
if "user" not in st.session_state and _handle_oauth_callback():
    st.rerun()

if "reset" in st.query_params and "user" not in st.session_state:
    reset_view(st.query_params["reset"])
    st.stop()

user = _current_user()
if not user:
    render_auth()
    st.stop()

STUDENT_PAGES = ["Dashboard", "AI Assistant", "Find Tutors", "My Connections", "Skill Exchange", "Notifications", "Profile"]
TUTOR_PAGES = ["Dashboard", "AI Assistant", "Student Requests", "My Students", "Notifications", "Profile"]
pages = STUDENT_PAGES if user["role"] == "student" else TUTOR_PAGES
if st.session_state.get("nav") not in pages:
    st.session_state["nav"] = "Dashboard"

unread = svc.unread_count(user["id"])
with st.sidebar:
    st.markdown('<div class="eb-brand">Edu<span>Bridge</span>-AI</div>', unsafe_allow_html=True)
    prof = svc.get_profile(user["id"])
    st.markdown(
        f'<div class="eb-row" style="margin:.8rem 0">{theme.avatar(user["id"], user["full_name"], prof["has_avatar"], 44)}'
        f'<div><div class="eb-title">{theme.esc(user["full_name"])}</div>'
        f'<div class="eb-sub">{theme.esc(user["role"].title())}</div></div></div>',
        unsafe_allow_html=True,
    )
    st.radio(
        "Navigate", pages, key="nav", label_visibility="collapsed",
        format_func=lambda p: f"{p} ({unread})" if p == "Notifications" and unread else p,
    )
    st.divider()
    st.button("Log out", on_click=_logout, use_container_width=True)

show_flash()
page = st.session_state["nav"]
if page == "Dashboard":
    render_dashboard(user)
elif page == "AI Assistant":
    render_ai(user)
elif page == "Find Tutors":
    render_find_tutors(user)
elif page in ("My Connections", "My Students"):
    render_connections(user)
elif page == "Student Requests":
    render_requests(user)
elif page == "Skill Exchange":
    render_exchange(user)
elif page == "Notifications":
    render_notifications(user)
elif page == "Profile":
    render_profile(user)
