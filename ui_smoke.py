"""Headless smoke test: runs every page function against a stub `streamlit` and a real database.
It proves the page code executes without NameError/KeyError/TypeError on realistic data.
It does NOT prove the visual rendering or widget behaviour in a real Streamlit server."""
import os, sys, tempfile, types
from datetime import date, time
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_PATH"] = os.path.join(tempfile.mkdtemp(), "smoke.db")


class State(dict):
    __getattr__ = dict.get
    def __setattr__(self, k, v): self[k] = v


class Stop(Exception): pass


class Proxy:
    """Column/tab/container stand-in: widgets called on it behave like the top-level stubs."""
    def __init__(self, st): self._st = st
    def __getattr__(self, name): return getattr(self._st, name)
    def __enter__(self): return self
    def __exit__(self, *a): return False


def make_st():
    st = MagicMock(name="streamlit")
    st.session_state, st.query_params = State(), {}
    st.columns.side_effect = lambda spec, **k: [Proxy(st) for _ in range(spec if isinstance(spec, int) else len(spec))]
    st.tabs.side_effect = lambda labels: [Proxy(st) for _ in labels]
    st.container.side_effect = lambda *a, **k: Proxy(st)
    st.expander.side_effect = lambda *a, **k: Proxy(st)
    st.form.side_effect = lambda *a, **k: Proxy(st)
    st.chat_message.side_effect = lambda *a, **k: Proxy(st)
    st.spinner.side_effect = lambda *a, **k: Proxy(st)
    st.selectbox.side_effect = lambda label, options, **k: (list(options)[0] if len(list(options)) else None)
    st.radio.side_effect = lambda label, options, **k: list(options)[0]
    for name in ("button", "form_submit_button"): getattr(st, name).return_value = False
    for name in ("text_input", "text_area"): getattr(st, name).return_value = ""
    st.checkbox.side_effect = lambda label, value=False, **k: value
    st.number_input.side_effect = lambda label, mn=0, mx=0, value=0, **k: value
    st.slider.return_value = 5
    st.date_input.return_value, st.time_input.return_value = date.today(), time(18, 0)
    st.file_uploader.return_value = None
    st.chat_input.return_value = None
    st.rerun.side_effect = Stop
    st.stop.side_effect = Stop
    st.cache_resource = lambda f: f
    st.fragment = lambda **kw: (lambda f: f)
    return st


st = make_st()
sys.modules["streamlit"] = st

import database as db, auth_service as auth, services as svc, ai_service
db.init_db()
from datetime import datetime, timedelta

mk = lambda role, n, e: auth.register_user(n, e, "Passw0rd1", "Passw0rd1", role)
s1, s2, s3 = mk("student", "Asha Rao", "a@x.com"), mk("student", "Bilal K", "b@x.com"), mk("student", "Chen Li", "c@x.com")
tut = mk("tutor", "Tara Singh", "t@x.com")
svc.update_tutor_profile(tut["id"], "Python mentor", "Teaches <b>Python</b>", "Python, Maths", "pandas", 4, "BSc", "Evenings", "Hyderabad", True)
svc.update_student_profile(s1["id"], "bio", "Python", "BTech", "Hyd")
for u, t, l in ((s1, "graphic design", "python"), (s2, "video editing", "graphic design"), (s3, "python", "video editing")):
    svc.add_skill(u["id"], t, "teach"); svc.add_skill(u["id"], l, "learn")
svc.request_connection(s1["id"], tut["id"], "<script>alert(1)</script>")
svc.respond_connection(tut["id"], svc.list_connections(tut["id"], "tutor")[0]["id"], True)
svc.send_message(s1["id"], svc.list_connections(s1["id"], "student")[0]["id"], "hello")
svc.request_connection(s2["id"], tut["id"], "pls")
gid = svc.create_group(s1["id"], "Triad", [s2["id"], s3["id"]])
svc.respond_invite(s2["id"], gid, True)
svc.schedule_session(s1["id"], gid, "Kickoff", datetime.now() + timedelta(days=1), 60, s2["id"], "https://meet.example", "n")
svc.send_group_message(s1["id"], gid, "hi team")
cid = svc.create_conversation(s1["id"]); svc.add_ai_message(s1["id"], cid, "user", "hi"); svc.add_ai_message(s1["id"], cid, "assistant", "hello")

import theme, ui_dashboard, ui_ai, ui_market, ui_exchange, ui_profile, auth_ui

def run(label, fn, *a):
    try:
        fn(*a)
    except Stop:
        pass
    print("ok  ", label)

for u in (auth.get_user(s1["id"]), auth.get_user(s3["id"]), auth.get_user(tut["id"])):
    st.session_state.clear()
    tag = f"{u['role']}:{u['full_name']}"
    run(tag + " dashboard", ui_dashboard.render_dashboard, u)
    run(tag + " notifications", ui_dashboard.render_notifications, u)
    run(tag + " ai", ui_ai.render_ai, u)
    run(tag + " connections", ui_market.render_connections, u)
    run(tag + " profile", ui_profile.render_profile, u)
    if u["role"] == "student":
        run(tag + " find tutors", ui_market.render_find_tutors, u)
        run(tag + " exchange", ui_exchange.render_exchange, u)
    else:
        run(tag + " requests", ui_market.render_requests, u)
st.session_state.clear()
for v in ("login", "register", "forgot"):
    st.session_state["auth_view"] = v
    run("auth " + v, auth_ui.render_auth)
run("auth reset", auth_ui.reset_view, "badtoken")

# XSS: user text must be escaped in generated HTML
html_calls = " ".join(str(c) for c in st.markdown.call_args_list)
assert "<script>alert(1)" not in html_calls, "unescaped user content found in HTML"
print("escape check ok")
