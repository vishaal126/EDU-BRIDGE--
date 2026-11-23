"""Shared UI plumbing: safe service calls, flash messages, navigation."""
import logging

import streamlit as st

from ai_service import AIError
from auth_service import AuthError
from database import DatabaseError
from services import ServiceError

log = logging.getLogger("edubridge")
KNOWN = (ServiceError, AuthError, AIError, DatabaseError)


def flash(message: str, kind: str = "success") -> None:
    st.session_state["_flash"] = (kind, message)


def show_flash() -> None:
    item = st.session_state.pop("_flash", None)
    if item:
        {"success": st.success, "error": st.error, "info": st.info, "warning": st.warning}[item[0]](item[1])


def safe_call(fn, *args, success: str = None, rerun: bool = False, **kwargs):
    """Run a service call. Shows a friendly error instead of crashing.
    Returns (ok, result). With success=..., flashes it and (if rerun) reruns the script."""
    try:
        result = fn(*args, **kwargs)
    except KNOWN as exc:
        st.error(str(exc))
        return False, None
    except Exception:  # unexpected: log details, show a generic message
        log.exception("Unexpected error in %s", getattr(fn, "__name__", fn))
        st.error("Something went wrong. Please try again.")
        return False, None
    if success:
        flash(success)
    if rerun:
        st.rerun()
    return True, result


def goto(page: str, **state) -> None:
    """on_click callback: switch page (and optionally preset session state)."""
    st.session_state["nav"] = page
    for k, v in state.items():
        st.session_state[k] = v
