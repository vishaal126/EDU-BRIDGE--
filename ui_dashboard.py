"""Dashboard and notifications pages."""
import streamlit as st

import services as svc
import theme
from ui_common import goto, safe_call

KIND_ICON = {"connection_request": "🤝", "connection_response": "✅", "message": "💬", "group_invite": "📨", "group": "👥"}


def _stats_row(user) -> dict:
    stats = svc.dashboard_stats(user["id"], user["role"])
    if user["role"] == "student":
        items = [(stats["connections"], "Connected tutors"), (stats["pending"], "Pending requests"),
                 (stats["groups"], "Active exchanges"), (stats["unread"], "Unread notifications")]
    else:
        items = [(stats["connections"], "Connected students"), (stats["pending"], "Requests to review"),
                 (stats["ai_chats"], "AI chats"), (stats["unread"], "Unread notifications")]
    for col, (n, label) in zip(st.columns(4), items):
        col.markdown(theme.stat(n, label), unsafe_allow_html=True)
    return stats


def render_dashboard(user) -> None:
    first = user["full_name"].split()[0]
    st.markdown(f"# Welcome back, {theme.esc(first)} 👋")
    st.caption("Here's what's happening in your learning network." if user["role"] == "student"
               else "Here's what's happening with your students.")
    stats = _stats_row(user)
    st.write("")

    if user["role"] == "student":
        _student_body(user, stats)
    else:
        _tutor_body(user, stats)

    st.markdown("### Recent notifications")
    notes = svc.list_notifications(user["id"], 5)
    if not notes:
        st.caption("Nothing yet. Notifications about requests, messages and groups will appear here.")
    for n in notes:
        theme.card(f'<div class="eb-title">{KIND_ICON.get(n["kind"], "🔔")} {theme.esc(n["title"])}</div>'
                   f'<div class="eb-sub">{theme.esc(n["body"])}</div>', "" if n["is_read"] else "unread")
    st.button("View all notifications", on_click=goto, args=("Notifications",))


def _student_body(user, stats) -> None:
    left, right = st.columns([3, 2])
    with left:
        st.markdown("### Recommended tutors")
        recs = svc.recommended_tutors(user["id"])
        if not recs:
            st.caption("Add interests in your Profile or skills you want to learn, and matching tutors will show up here.")
        for t in recs:
            theme.person_card(t["id"], t["full_name"], t["has_avatar"], t["headline"], "",
                              "", theme.chips(t["subjects"]))
        st.button("Browse all tutors", on_click=goto, args=("Find Tutors",))
    with right:
        st.markdown("### Skill-exchange opportunities")
        skills = svc.list_skills(user["id"])
        if not skills["teach"] or not skills["learn"]:
            st.caption("List a skill you can teach and one you want to learn to get matched.")
        else:
            m = svc.get_matches(user["id"])
            st.markdown(theme.stat(len(m["triangles"]) + len(m["pairs"]), "Compatible groups found"), unsafe_allow_html=True)
            st.caption(f"{len(m['pairs'])} two-person matches · {len(m['triangles'])} three-person cycles")
        invites = svc.pending_group_invites(user["id"])
        if invites:
            st.info(f"You have {invites} pending group invitation{'s' if invites > 1 else ''}.")
        st.button("Open Skill Exchange", on_click=goto, args=("Skill Exchange",))
        st.markdown("### AI learning assistant")
        st.caption("Ask a question, get a plan, or summarize your notes.")
        st.button("Ask the AI", on_click=goto, args=("AI Assistant",), type="primary")
        if stats["pending"]:
            st.markdown("### Your pending requests")
            for c in svc.list_connections(user["id"], "student", ["pending"]):
                st.markdown(f"- {theme.esc(c['other_name'])} " + theme.status_chip("pending"), unsafe_allow_html=True)


def _tutor_body(user, stats) -> None:
    prof = svc.get_profile(user["id"])
    left, right = st.columns([3, 2])
    with left:
        st.markdown("### Student requests")
        pending = svc.list_connections(user["id"], "tutor", ["pending"])
        if not pending:
            st.caption("No requests waiting for you.")
        for c in pending[:3]:
            theme.person_card(c["other_id"], c["other_name"], c["other_has_avatar"], "wants to connect", "",
                              c["intro_message"])
        if pending:
            st.button("Review requests", on_click=goto, args=("Student Requests",), type="primary")
        st.markdown("### Connected students")
        students = svc.list_connections(user["id"], "tutor", ["accepted"])
        if not students:
            st.caption("Accepted students will appear here.")
        for c in students[:4]:
            theme.person_card(c["other_id"], c["other_name"], c["other_has_avatar"], "", "", "")
        if students:
            st.button("Open messages", on_click=goto, args=("My Students",))
    with right:
        st.markdown("### Your tutor profile")
        if prof["is_published"]:
            st.success("Your profile is live in the marketplace.")
        else:
            st.warning("Your profile is not published, so students can't find you yet.")
        st.button("Edit profile", on_click=goto, args=("Profile",))
        st.markdown("### AI learning assistant")
        st.caption("Draft lesson plans, explanations and practice questions.")
        st.button("Open AI assistant", on_click=goto, args=("AI Assistant",), type="primary")


def render_notifications(user) -> None:
    st.markdown("# Notifications")
    notes = svc.list_notifications(user["id"])
    c1, c2 = st.columns([4, 1])
    c1.caption(f"{sum(1 for n in notes if not n['is_read'])} unread")
    if c2.button("Mark all read", disabled=not any(not n["is_read"] for n in notes)):
        safe_call(svc.mark_all_read, user["id"], rerun=True)
    if not notes:
        st.info("You're all caught up.")
    for n in notes:
        col_a, col_b = st.columns([6, 1])
        with col_a:
            theme.card(
                f'<div class="eb-title">{KIND_ICON.get(n["kind"], "🔔")} {theme.esc(n["title"])}</div>'
                f'<div class="eb-sub">{theme.esc(n["body"])}</div>'
                f'<div class="eb-sub">{theme.esc(n["created_at"].replace("T", " "))} UTC</div>',
                "" if n["is_read"] else "unread",
            )
        with col_b:
            if not n["is_read"] and st.button("Mark read", key=f"nr_{n['id']}"):
                safe_call(svc.mark_notification_read, user["id"], n["id"], rerun=True)
