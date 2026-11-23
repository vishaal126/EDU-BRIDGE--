"""Runs app.py end to end against the stub: logged-out, logged-in student/tutor, OAuth error callback."""
import os, sys, runpy
sys.argv = ["x"]
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
import ui_smoke as sm  # builds stub + sample data (also runs page smoke checks)
st = sm.st

def run_app(label):
    try:
        runpy.run_path(os.path.join(here, "..", "app.py"), run_name="__main__")
    except sm.Stop:
        pass
    print("app ok:", label, "| nav =", st.session_state.get("nav"))

st.session_state.clear(); st.query_params.clear()
run_app("logged out -> login")
import auth_service as auth
for email, nav in (("a@x.com", "Dashboard"), ("a@x.com", "Skill Exchange"), ("t@x.com", "Student Requests")):
    u = auth.authenticate(email, "Passw0rd1")
    tok = auth.create_session(u["id"])
    st.session_state.clear(); st.query_params.clear(); st.query_params["sid"] = tok
    st.session_state["nav"] = nav
    run_app(f"{u['role']} {nav}")
st.session_state.clear(); st.query_params.clear(); st.query_params["sid"] = "forged-token"
run_app("forged sid rejected"); assert "user" not in st.session_state
st.session_state.clear(); st.query_params.clear(); st.query_params.update({"code": "x", "state": "bogus"})
run_app("oauth bad state"); assert "user" not in st.session_state
print("APP SMOKE OK")
