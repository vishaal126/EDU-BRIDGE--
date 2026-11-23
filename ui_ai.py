"""AI learning assistant page with persistent conversation history."""
import streamlit as st

import ai_service
import services as svc
import theme
from ui_common import safe_call


def _answer(user, conv_id: int, mode: str) -> None:
    msgs = svc.get_ai_messages(user["id"], conv_id)
    history = [{"role": m["role"], "content": m["content"]} for m in msgs]
    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            try:
                text = ai_service.ask(history, mode)
            except ai_service.AIError as exc:
                st.error(str(exc))
                return
    safe_call(svc.add_ai_message, user["id"], conv_id, "assistant", text, rerun=True)


def render_ai(user) -> None:
    st.markdown("# AI Learning Assistant")
    if not ai_service.is_configured():
        st.warning("The AI assistant isn't set up on this server yet (missing ANTHROPIC_API_KEY). "
                   "Your saved conversations are still available.")

    convs = svc.list_conversations(user["id"])
    ids = [c["id"] for c in convs]
    pending = st.session_state.pop("_ai_select", "__keep__")  # applied before the widget exists
    if pending != "__keep__":
        st.session_state["ai_conv_select"] = pending
    if st.session_state.get("ai_conv_select") not in [None] + ids:
        st.session_state["ai_conv_select"] = None

    top = st.columns([3, 2, 1, 1])
    labels = {c["id"]: c["title"] for c in convs}
    current = top[0].selectbox(
        "Conversation", [None] + ids, format_func=lambda i: "➕ New chat" if i is None else labels[i],
        key="ai_conv_select",
    )
    mode = top[1].selectbox("Mode", list(ai_service.MODES.keys()))
    if current is not None and top[3].button("Delete chat", key="ai_del"):
        ok, _ = safe_call(svc.delete_conversation, user["id"], current)
        if ok:
            st.session_state["_ai_select"] = None
            st.rerun()

    history = svc.get_ai_messages(user["id"], current) if current else []
    if not history:
        st.caption("Try: “Explain recursion with an example”, “Make me a 4-week plan to learn SQL”, or paste text to summarize.")
    for m in history:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    # A user message with no answer yet (first send, or the API failed earlier): answer / offer retry.
    if history and history[-1]["role"] == "user":
        run = st.session_state.pop("_ai_run", False)
        retry = st.button("Retry answer", key="ai_retry")
        if run or retry:
            _answer(user, current, mode)

    prompt = st.chat_input("Ask a question…", max_chars=4000, disabled=not ai_service.is_configured())
    if prompt:
        conv_id = current
        if conv_id is None:
            ok, conv_id = safe_call(svc.create_conversation, user["id"])
            if not ok:
                return
        ok, _ = safe_call(svc.add_ai_message, user["id"], conv_id, "user", prompt)
        if ok:
            st.session_state["_ai_run"] = True
            st.session_state["_ai_select"] = conv_id
            st.rerun()
