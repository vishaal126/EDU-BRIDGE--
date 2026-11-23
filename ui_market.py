"""Tutor marketplace, connection requests and one-to-one messaging."""
import streamlit as st

import services as svc
import theme
from ui_common import goto, safe_call


# ---------------- messaging ----------------
@st.fragment(run_every=5)
def _chat_log(user_id: int, conn_id: int) -> None:
    """Auto-refreshing message log (polls every 5s)."""
    try:
        msgs = svc.get_messages(user_id, conn_id)
    except Exception:
        st.error("Couldn't load this conversation.")
        return
    box = st.container(height=360, border=True)
    with box:
        if not msgs:
            st.caption("No messages yet. Say hello!")
        for m in msgs:
            mine = m["sender_id"] == user_id
            with st.chat_message("user" if mine else "assistant"):
                st.markdown(f"**{'You' if mine else theme.esc(m['sender_name'])}** · "
                            f"<span class='eb-sub'>{theme.esc(m['created_at'][5:16].replace('T', ' '))} UTC</span>",
                            unsafe_allow_html=True)
                st.text(m["body"])  # st.text: user content is never interpreted as markdown/HTML


def chat_panel(user_id: int, conn_id: int, key: str) -> None:
    _chat_log(user_id, conn_id)
    with st.form(f"msg_form_{key}", clear_on_submit=True):
        body = st.text_input("Message", placeholder="Write a message…", label_visibility="collapsed", max_chars=2000)
        if st.form_submit_button("Send", type="primary") and body.strip():
            ok, _ = safe_call(svc.send_message, user_id, conn_id, body)
            if ok:
                st.rerun()


# ---------------- student: marketplace ----------------
def _tutor_profile_body(t) -> None:
    st.markdown(f"**Subjects:** {theme.chips(t['subjects'])}", unsafe_allow_html=True)
    if t["skills"]:
        st.markdown(f"**Skills:** {theme.chips(t['skills'], 'teach')}", unsafe_allow_html=True)
    st.markdown(f"**Experience:** {t['experience_years']} year(s)")
    if t["qualifications"]:
        st.markdown(f"**Qualifications:** {theme.esc(t['qualifications'])}", unsafe_allow_html=True)
    if t["availability"]:
        st.markdown(f"**Availability:** {theme.esc(t['availability'])}", unsafe_allow_html=True)
    if t["location"]:
        st.markdown(f"**Location:** {theme.esc(t['location'])}", unsafe_allow_html=True)
    if t["description"]:
        st.text(t["description"])


def render_find_tutors(user) -> None:
    st.markdown("# Find a tutor")
    c1, c2 = st.columns([3, 2])
    q = c1.text_input("Search", placeholder="Name, subject or skill (e.g. Python)", label_visibility="collapsed")
    subject = c2.selectbox("Subject", ["All subjects"] + svc.list_subjects(), label_visibility="collapsed")
    tutors = svc.search_tutors(user["id"], q, "" if subject == "All subjects" else subject)
    st.caption(f"{len(tutors)} tutor{'s' if len(tutors) != 1 else ''} found")
    if not tutors:
        st.info("No tutors match your search yet. Try different keywords, or check back soon.")

    for t in tutors:
        conn = t["connection"]
        status = conn["status"] if conn else None
        theme.person_card(
            t["id"], t["full_name"], t["has_avatar"], t["headline"],
            f"{t['experience_years']} yrs experience" + (f" · {theme.esc(t['location'])}" if t["location"] else ""),
            "", theme.chips(t["subjects"]) + (theme.status_chip(status) if status else ""),
        )
        with st.expander("View profile & connect"):
            _tutor_profile_body(t)
            st.divider()
            if status == "accepted":
                st.success("You're connected.")
                st.button("Message this tutor", key=f"msg_{t['id']}", on_click=goto,
                          args=("My Connections",), kwargs={"chat_conn": conn["id"]})
            elif status == "pending":
                st.info("Request sent. Waiting for the tutor to respond.")
            else:
                if status == "rejected":
                    st.warning("Your earlier request was declined. You can send a new one.")
                elif status == "ended":
                    st.caption("You were connected before. You can reconnect.")
                with st.form(f"req_{t['id']}"):
                    msg = st.text_area("Introduce yourself (optional)", max_chars=500,
                                       placeholder="What would you like to learn?")
                    if st.form_submit_button("Send connection request", type="primary"):
                        safe_call(svc.request_connection, user["id"], t["id"], msg,
                                  success=f"Request sent to {t['full_name']}.", rerun=True)


# ---------------- tutor: incoming requests ----------------
def render_requests(user) -> None:
    st.markdown("# Student requests")
    pending = svc.list_connections(user["id"], "tutor", ["pending"])
    if not pending:
        st.info("No pending requests right now.")
    for c in pending:
        theme.person_card(c["other_id"], c["other_name"], c["other_has_avatar"], "wants to connect with you", "",
                          c["intro_message"] or "(No introduction provided.)")
        a, b, _ = st.columns([1, 1, 4])
        if a.button("Accept", key=f"acc_{c['id']}", type="primary"):
            safe_call(svc.respond_connection, user["id"], c["id"], True,
                      success=f"You're now connected with {c['other_name']}.", rerun=True)
        if b.button("Decline", key=f"rej_{c['id']}"):
            safe_call(svc.respond_connection, user["id"], c["id"], False, success="Request declined.", rerun=True)
    with st.expander("Request history"):
        done = svc.list_connections(user["id"], "tutor", ["accepted", "rejected", "ended"])
        if not done:
            st.caption("No past requests.")
        for c in done:
            st.markdown(f"{theme.esc(c['other_name'])} {theme.status_chip(c['status'])} "
                        f"<span class='eb-sub'>{theme.esc(c['created_at'][:10])}</span>", unsafe_allow_html=True)


# ---------------- both roles: connections + chat ----------------
def render_connections(user) -> None:
    role = user["role"]
    st.markdown("# My connections" if role == "student" else "# My students")
    all_conns = svc.list_connections(user["id"], role)
    live = [c for c in all_conns if c["status"] == "accepted"]
    pending = [c for c in all_conns if c["status"] == "pending"]
    t_live, t_pending, t_hist = st.tabs([f"Connected ({len(live)})", f"Pending ({len(pending)})", "History"])

    with t_live:
        if not live:
            st.info("No active connections yet." + (" Find a tutor to get started." if role == "student" else ""))
        else:
            ids = [c["id"] for c in live]
            if st.session_state.get("chat_conn") not in ids:
                st.session_state["chat_conn"] = ids[0]
            names = {c["id"]: c["other_name"] for c in live}
            conn_id = st.selectbox("Conversation with", ids, format_func=lambda i: names[i], key="chat_conn")
            conn = next(c for c in live if c["id"] == conn_id)
            left, right = st.columns([2, 5])
            with left:
                theme.person_card(conn["other_id"], conn["other_name"], conn["other_has_avatar"],
                                  "Tutor" if role == "student" else "Student",
                                  f"✉ {theme.esc(conn['other_email'])}")
                if st.button("End connection", key=f"end_{conn_id}"):
                    safe_call(svc.end_connection, user["id"], conn_id, success="Connection ended.", rerun=True)
            with right:
                chat_panel(user["id"], conn_id, str(conn_id))

    with t_pending:
        if not pending:
            st.caption("No pending requests.")
        for c in pending:
            st.markdown(f"{theme.esc(c['other_name'])} {theme.status_chip('pending')}", unsafe_allow_html=True)
            if role == "tutor":
                st.caption("Review it under Student Requests.")

    with t_hist:
        if not all_conns:
            st.caption("Nothing here yet.")
        for c in all_conns:
            st.markdown(f"{theme.esc(c['other_name'])} {theme.status_chip(c['status'])} "
                        f"<span class='eb-sub'>requested {theme.esc(c['created_at'][:10])}</span>", unsafe_allow_html=True)
