"""Student Skill Exchange: skills, matching, groups, chat, sessions, feedback."""
from datetime import date, datetime, time, timedelta

import streamlit as st

import services as svc
import theme
from ui_common import safe_call


def render_exchange(user) -> None:
    st.markdown("# Student Skill Exchange")
    st.caption("Trade skills with other students. No money, just knowledge.")
    invites = svc.pending_group_invites(user["id"])
    t_match, t_skills, t_groups = st.tabs(["🔎 Matches", "🧠 My skills", f"👥 My groups{f' ({invites} new)' if invites else ''}"])
    with t_match:
        _matches_tab(user)
    with t_skills:
        _skills_tab(user)
    with t_groups:
        _groups_tab(user)


# ---------------- skills ----------------
def _skills_tab(user) -> None:
    skills = svc.list_skills(user["id"])
    popular = svc.popular_skills()
    if popular:
        st.caption("Popular on EduBridge: " + ", ".join(popular) + ". Use the same spelling as others so you match.")
    cols = st.columns(2)
    for col, kind, title, css in ((cols[0], "teach", "I can teach", "teach"), (cols[1], "learn", "I want to learn", "learn")):
        with col:
            st.markdown(f"### {title}")
            for s in skills[kind]:
                a, b = st.columns([5, 1])
                a.markdown(theme.chips([s["name"]], css), unsafe_allow_html=True)
                if b.button("✕", key=f"rm_{s['id']}", help="Remove"):
                    safe_call(svc.remove_skill, user["id"], s["id"], rerun=True)
            if not skills[kind]:
                st.caption("Nothing added yet.")
            with st.form(f"add_{kind}", clear_on_submit=True):
                name = st.text_input("Add a skill", key=f"new_{kind}", placeholder="e.g. Python", max_chars=50)
                if st.form_submit_button("Add"):
                    safe_call(svc.add_skill, user["id"], name, kind, rerun=True)


# ---------------- matches ----------------
def _edge_text(m, edge) -> str:
    return (f"<b>{theme.esc(m['names'][edge['teacher']])}</b> teaches "
            f"{theme.chips(edge['skills'], 'teach')} → <b>{theme.esc(m['names'][edge['learner']])}</b>")


def _matches_tab(user) -> None:
    skills = svc.list_skills(user["id"])
    if not skills["teach"] or not skills["learn"]:
        st.info("Add at least one skill you can teach and one you want to learn (My skills tab), and we'll find compatible students.")
        return
    result = svc.get_matches(user["id"])
    if not result["pairs"] and not result["triangles"]:
        st.info("No compatible students yet. Matches appear when other students teach what you want to learn "
                "and want to learn what you can teach. Check back as more students join.")
        return

    for title, key, items in (("Three-person learning cycles", "tri", result["triangles"]),
                              ("Two-person swaps", "pair", result["pairs"])):
        if not items:
            continue
        st.markdown(f"### {title}")
        for i, m in enumerate(items[:10]):
            rows = "".join(f"<div class='eb-body'>{_edge_text(m, e)}</div>" for e in m["edges"])
            others = [uid for uid in m["members"] if uid != user["id"]]
            theme.card(f"<div class='eb-title'>With {theme.esc(' & '.join(m['names'][u] for u in others))}</div>{rows}")
            with st.form(f"form_{key}_{i}"):
                default = " + ".join(dict.fromkeys(s for e in m["edges"] for s in e["skills"]))[:80]
                name = st.text_input("Group name", value=default, max_chars=80)
                if st.form_submit_button("Invite them & form group", type="primary"):
                    safe_call(svc.create_group, user["id"], name, others,
                              success="Group created and invitations sent.", rerun=True)


# ---------------- groups ----------------
def _groups_tab(user) -> None:
    groups = svc.list_groups(user["id"])
    invited = [g for g in groups if g["my_status"] == "invited"]
    mine = [g for g in groups if g["my_status"] == "active"]

    for g in invited:
        theme.card(f"<div class='eb-title'>📨 Invitation: {theme.esc(g['name'])}</div>"
                   f"<div class='eb-sub'>Members: {theme.esc(', '.join(m['full_name'] for m in g['members']))}</div>")
        for m in g["members"]:
            st.markdown(f"**{theme.esc(m['full_name'])}** — teaches {theme.chips(m['teach'], 'teach')} · wants "
                        f"{theme.chips(m['learn'], 'learn')}", unsafe_allow_html=True)
        a, b, _ = st.columns([1, 1, 4])
        if a.button("Accept", key=f"gacc_{g['id']}", type="primary"):
            safe_call(svc.respond_invite, user["id"], g["id"], True, success="You joined the group!", rerun=True)
        if b.button("Decline", key=f"gdec_{g['id']}"):
            safe_call(svc.respond_invite, user["id"], g["id"], False, success="Invitation declined.", rerun=True)

    if not mine:
        if not invited:
            st.info("You're not in any exchange groups yet. Form one from the Matches tab.")
        return

    ids = [g["id"] for g in mine]
    names = {g["id"]: f"{g['name']} ({g['status']})" for g in mine}
    if st.session_state.get("grp_sel") not in ids:
        st.session_state["grp_sel"] = ids[0]
    gid = st.selectbox("Open group", ids, format_func=lambda i: names[i], key="grp_sel")
    group = svc.get_group(user["id"], gid)
    st.markdown(f"## {theme.esc(group['name'])} {theme.status_chip(group['status'])}", unsafe_allow_html=True)

    t_members, t_chat, t_sessions, t_manage = st.tabs(["Members", "Discussion", "Sessions", "Manage & feedback"])
    with t_members:
        _members(user, group)
    with t_chat:
        _group_chat(user, group)
    with t_sessions:
        _sessions(user, group)
    with t_manage:
        _manage(user, group)


def _members(user, group) -> None:
    for m in group["members"]:
        theme.card(
            f'<div class="eb-row">{theme.avatar(m["user_id"], m["full_name"], m["has_avatar"])}<div>'
            f'<div class="eb-title">{theme.esc(m["full_name"])} {theme.status_chip(m["status"]) if m["status"] != "active" else ""}</div>'
            f'<div class="eb-body">Can teach: {theme.chips(m["teach"], "teach") or "—"}</div>'
            f'<div class="eb-body">Wants to learn: {theme.chips(m["learn"], "learn") or "—"}</div></div></div>'
        )
    if group["status"] in ("forming", "active") and len(group["members"]) < 3:
        with st.expander("Invite another student"):
            q = st.text_input("Search students by name", key=f"inv_q_{group['id']}")
            found = svc.find_students(user["id"], q)
            member_ids = {m["user_id"] for m in group["members"]}
            found = [f for f in found if f["id"] not in member_ids]
            if q and not found:
                st.caption("No matching students.")
            if found:
                pick = st.selectbox("Student", [f["id"] for f in found],
                                    format_func=lambda i: next(f["full_name"] for f in found if f["id"] == i),
                                    key=f"inv_pick_{group['id']}")
                if st.button("Send invitation", key=f"inv_btn_{group['id']}"):
                    safe_call(svc.invite_to_group, user["id"], group["id"], pick, success="Invitation sent.", rerun=True)


@st.fragment(run_every=5)
def _group_log(user_id: int, group_id: int) -> None:
    try:
        msgs = svc.get_group_messages(user_id, group_id)
    except Exception:
        st.error("Couldn't load the discussion.")
        return
    with st.container(height=340, border=True):
        if not msgs:
            st.caption("No messages yet. Start the discussion!")
        for m in msgs:
            mine = m["sender_id"] == user_id
            with st.chat_message("user" if mine else "assistant"):
                st.markdown(f"**{'You' if mine else theme.esc(m['sender_name'])}** · "
                            f"<span class='eb-sub'>{theme.esc(m['created_at'][5:16].replace('T', ' '))} UTC</span>",
                            unsafe_allow_html=True)
                st.text(m["body"])


def _group_chat(user, group) -> None:
    if group["status"] == "cancelled":
        st.warning("This group was cancelled.")
        return
    _group_log(user["id"], group["id"])
    with st.form(f"gmsg_{group['id']}", clear_on_submit=True):
        body = st.text_input("Message", placeholder="Write to the group…", label_visibility="collapsed", max_chars=2000)
        if st.form_submit_button("Send", type="primary") and body.strip():
            ok, _ = safe_call(svc.send_group_message, user["id"], group["id"], body)
            if ok:
                st.rerun()


def _sessions(user, group) -> None:
    sessions = svc.list_sessions(user["id"], group["id"])
    if not sessions:
        st.caption("No sessions scheduled yet.")
    for s in sessions:
        when = s["scheduled_at"].replace("T", " ")
        link = f" · <a href='{theme.esc(s['meeting_link'])}' target='_blank' rel='noopener noreferrer'>Join link</a>" \
            if s["meeting_link"].startswith(("http://", "https://")) else ""
        theme.card(
            f"<div class='eb-title'>{theme.esc(s['title'])} {theme.status_chip(s['status'])}</div>"
            f"<div class='eb-sub'>{theme.esc(when)} · {s['duration_min']} min"
            f"{' · Teacher: ' + theme.esc(s['teacher_name']) if s['teacher_name'] else ''}{link}</div>"
            f"<div class='eb-body'>{theme.esc(s['notes'])}</div>"
        )
        if s["status"] == "scheduled":
            a, b, _ = st.columns([1, 1, 4])
            if a.button("Mark done", key=f"sd_{s['id']}"):
                safe_call(svc.update_session_status, user["id"], s["id"], "completed", rerun=True)
            if b.button("Cancel", key=f"sc_{s['id']}"):
                safe_call(svc.update_session_status, user["id"], s["id"], "cancelled", rerun=True)
    if group["status"] != "active":
        st.caption("Sessions can be scheduled once the group is active.")
        return
    with st.expander("➕ Schedule a learning session"):
        with st.form(f"sess_{group['id']}"):
            title = st.text_input("Title", placeholder="e.g. Python basics for designers", max_chars=120)
            c1, c2, c3 = st.columns(3)
            d = c1.date_input("Date", value=date.today() + timedelta(days=1))
            t = c2.time_input("Time", value=time(18, 0))
            dur = c3.number_input("Minutes", 15, 480, 60, step=15)
            actives = [m for m in group["members"] if m["status"] == "active"]
            teacher = st.selectbox("Who teaches?", [None] + [m["user_id"] for m in actives],
                                   format_func=lambda i: "Anyone / not set" if i is None else
                                   next(m["full_name"] for m in actives if m["user_id"] == i))
            link = st.text_input("Meeting link (optional)", placeholder="https://meet.google.com/…")
            notes = st.text_area("Notes (optional)", max_chars=500)
            if st.form_submit_button("Schedule", type="primary"):
                when = datetime.combine(d, t)
                if when < datetime.now():
                    st.error("Please choose a time in the future.")
                elif link.strip() and not link.strip().startswith(("http://", "https://")):
                    st.error("The meeting link must start with http:// or https://")
                else:
                    safe_call(svc.schedule_session, user["id"], group["id"], title, when, int(dur), teacher,
                              link.strip(), notes, success="Session scheduled.", rerun=True)


def _manage(user, group) -> None:
    status = group["status"]
    if status == "active":
        st.markdown("Finished exchanging skills? Mark the exchange as completed to unlock feedback.")
        if st.button("✅ Mark exchange completed", key=f"done_{group['id']}", type="primary"):
            safe_call(svc.complete_group, user["id"], group["id"], success="Exchange marked completed.", rerun=True)
    if status in ("forming", "active"):
        if st.button("Leave group", key=f"leave_{group['id']}"):
            safe_call(svc.leave_group, user["id"], group["id"], success="You left the group.", rerun=True)
    if status == "completed":
        st.markdown("### Feedback")
        given = svc.feedback_given(user["id"], group["id"])
        todo = [m for m in group["members"] if m["status"] == "active" and m["user_id"] != user["id"] and m["user_id"] not in given]
        if not todo:
            st.success("You've given feedback to everyone. Thank you!")
        for m in todo:
            with st.form(f"fb_{group['id']}_{m['user_id']}"):
                st.markdown(f"**How was learning with {theme.esc(m['full_name'])}?**", unsafe_allow_html=True)
                rating = st.slider("Rating", 1, 5, 5, key=f"fbr_{group['id']}_{m['user_id']}")
                comment = st.text_area("Comment (optional)", max_chars=500, key=f"fbc_{group['id']}_{m['user_id']}")
                if st.form_submit_button("Submit feedback", type="primary"):
                    safe_call(svc.submit_feedback, user["id"], group["id"], m["user_id"], rating, comment,
                              success="Feedback sent.", rerun=True)
    if status == "cancelled":
        st.info("This group was cancelled because too few members remained.")
