"""Profile management: picture, profile details, account settings, password."""
import streamlit as st

import auth_service as auth
import services as svc
import theme
from ui_common import flash, safe_call


def render_profile(user) -> None:
    st.markdown("# Your profile")
    prof = svc.get_profile(user["id"])
    top = st.columns([1, 5])
    top[0].markdown(theme.avatar(user["id"], user["full_name"], prof["has_avatar"], 84), unsafe_allow_html=True)
    rating = svc.feedback_received(user["id"])
    top[1].markdown(f"### {theme.esc(user['full_name'])}  {theme.status_chip(user['role'])}", unsafe_allow_html=True)
    top[1].caption(user["email"] + (f" · ⭐ {rating['avg']}/5 from {rating['count']} exchange review(s)" if rating["count"] else ""))

    t_prof, t_acct, t_sec = st.tabs(["Profile details", "Account", "Security"])
    with t_prof:
        _picture(user)
        if user["role"] == "student":
            _student_form(user, prof)
        else:
            _tutor_form(user, prof)
    with t_acct:
        _account(user, prof)
    with t_sec:
        _security(user)


def _picture(user) -> None:
    with st.expander("Profile picture"):
        file = st.file_uploader("Upload PNG, JPG or WebP (max 1.5 MB)", type=["png", "jpg", "jpeg", "webp"], key="avatar_up")
        if file and st.button("Save picture", key="avatar_save"):
            data = file.getvalue()
            mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}[file.name.rsplit(".", 1)[-1].lower()]
            safe_call(svc.set_avatar, user["id"], data, mime, success="Profile picture updated.", rerun=True)


def _student_form(user, prof) -> None:
    with st.form("student_profile"):
        bio = st.text_area("About me", value=prof["bio"], max_chars=800)
        interests = st.text_input("Interests (comma separated)", value=prof["interests"], help="Used to recommend tutors, e.g. Python, Maths")
        education = st.text_input("Education", value=prof["education"], max_chars=200)
        location = st.text_input("Location", value=prof["location"], max_chars=100)
        if st.form_submit_button("Save profile", type="primary"):
            safe_call(svc.update_student_profile, user["id"], bio, interests, education, location,
                      success="Profile saved.", rerun=True)
    skills = svc.list_skills(user["id"])
    st.markdown("**Skills I can teach:** " + (theme.chips([s["name"] for s in skills["teach"]], "teach") or "—"), unsafe_allow_html=True)
    st.markdown("**Skills I want to learn:** " + (theme.chips([s["name"] for s in skills["learn"]], "learn") or "—"), unsafe_allow_html=True)
    st.caption("Manage skills in Skill Exchange → My skills.")
    conns = svc.list_connections(user["id"], "student", ["accepted"])
    st.markdown("**My connections:** " + (", ".join(theme.esc(c["other_name"]) for c in conns) or "none yet"), unsafe_allow_html=True)


def _tutor_form(user, prof) -> None:
    with st.form("tutor_profile"):
        headline = st.text_input("Headline", value=prof["headline"], max_chars=120, placeholder="e.g. Python & data science mentor")
        description = st.text_area("Description", value=prof["description"], max_chars=1500)
        subjects = st.text_input("Subjects offered (comma separated)", value=prof["subjects"])
        skills = st.text_input("Skills (comma separated)", value=prof["skills"])
        c1, c2 = st.columns(2)
        years = c1.number_input("Years of experience", 0, 60, int(prof["experience_years"]))
        location = c2.text_input("Location", value=prof["location"], max_chars=100)
        quals = st.text_area("Qualifications", value=prof["qualifications"], max_chars=500)
        avail = st.text_input("Availability", value=prof["availability"], max_chars=300, placeholder="e.g. Weekdays 6–9 PM IST")
        published = st.checkbox("Publish my profile in the tutor marketplace", value=bool(prof["is_published"]))
        if st.form_submit_button("Save tutor profile", type="primary"):
            safe_call(svc.update_tutor_profile, user["id"], headline, description, subjects, skills, years,
                      quals, avail, location, published, success="Tutor profile saved.", rerun=True)
    conns = svc.list_connections(user["id"], "tutor", ["accepted"])
    st.markdown("**Connected students:** " + (", ".join(theme.esc(c["other_name"]) for c in conns) or "none yet"), unsafe_allow_html=True)


def _account(user, prof) -> None:
    with st.form("account_form"):
        name = st.text_input("Full name", value=user["full_name"], max_chars=100)
        email = st.text_input("Email address", value=user["email"])
        if st.form_submit_button("Save account", type="primary"):
            safe_call(svc.update_account, user["id"], name, email, success="Account updated.", rerun=True)
    with st.expander("Switch account type"):
        st.caption("Only possible before you have any connections or exchange groups.")
        other = "tutor" if user["role"] == "student" else "student"
        if st.button(f"Switch to {other} account", key="switch_role"):
            safe_call(svc.change_role, user["id"], other, success=f"You're now a {other}.", rerun=True)


def _security(user) -> None:
    has_pw = auth.has_password(user["id"])
    if not has_pw:
        st.info("You signed up with Google or GitHub. You can add a password to also log in with your email.")
    with st.form("pw_form", clear_on_submit=True):
        current = st.text_input("Current password", type="password") if has_pw else ""
        new = st.text_input("New password", type="password", help="At least 8 characters, with a letter and a number.")
        confirm = st.text_input("Confirm new password", type="password")
        if st.form_submit_button("Update password", type="primary"):
            safe_call(auth.change_password, user["id"], current, new, confirm, success="Password updated.", rerun=True)
