"""Visual theme: dark base with violet/cyan neon accents, plus small HTML helpers.
All user-supplied text passes through html.escape before being placed in HTML."""
import html

import streamlit as st

import services as svc

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Inter:wght@400;500;600&display=swap');
:root{--bg:#0B0B14;--surface:#14142A;--surface2:#1B1B38;--violet:#8B5CF6;--cyan:#22D3EE;--text:#E8E8F5;--muted:#9A9AB8;--line:#2A2A4A;}
html,body,[class*="css"]{font-family:'Inter',sans-serif;}
h1,h2,h3,.eb-display{font-family:'Space Grotesk',sans-serif!important;letter-spacing:-.01em;}
.stApp{background:radial-gradient(1200px 600px at 85% -10%,rgba(139,92,246,.13),transparent 60%),var(--bg);}
[data-testid="stSidebar"]{background:var(--surface);border-right:1px solid var(--line);}
.block-container{padding-top:2rem;max-width:1200px;}
.eb-brand{font-family:'Space Grotesk';font-weight:700;font-size:1.45rem;color:var(--text);}
.eb-brand span{color:var(--cyan);text-shadow:0 0 14px rgba(34,211,238,.55);}
.eb-card{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:1rem 1.1rem;margin-bottom:.8rem;transition:border-color .2s,box-shadow .2s,transform .2s;}
.eb-card:hover{border-color:var(--violet);box-shadow:0 0 0 1px rgba(139,92,246,.35),0 8px 30px rgba(139,92,246,.12);transform:translateY(-1px);}
.eb-card.unread{border-left:3px solid var(--cyan);}
.eb-stat{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:1rem;text-align:left;}
.eb-stat .n{font-family:'Space Grotesk';font-size:2rem;font-weight:700;color:var(--cyan);text-shadow:0 0 18px rgba(34,211,238,.35);line-height:1.1;}
.eb-stat .l{color:var(--muted);font-size:.82rem;}
.eb-chip{display:inline-block;padding:.12rem .6rem;margin:.12rem .2rem .12rem 0;border-radius:999px;font-size:.76rem;border:1px solid var(--line);background:var(--surface2);color:var(--text);}
.eb-chip.teach{border-color:rgba(34,211,238,.55);color:var(--cyan);}
.eb-chip.learn{border-color:rgba(139,92,246,.7);color:#C4B5FD;}
.eb-chip.ok{border-color:#34d399;color:#34d399;} .eb-chip.warn{border-color:#fbbf24;color:#fbbf24;} .eb-chip.bad{border-color:#f87171;color:#f87171;}
.eb-row{display:flex;gap:.9rem;align-items:flex-start;}
.eb-av{width:52px;height:52px;border-radius:50%;flex:0 0 auto;object-fit:cover;border:2px solid var(--violet);box-shadow:0 0 14px rgba(139,92,246,.45);}
.eb-av.ph{display:flex;align-items:center;justify-content:center;background:linear-gradient(135deg,#5B21B6,#0891B2);color:#fff;font-weight:700;font-family:'Space Grotesk';}
.eb-title{font-weight:600;font-size:1.02rem;color:var(--text);}
.eb-sub{color:var(--muted);font-size:.85rem;}
.eb-body{color:#CFCFE6;font-size:.9rem;margin-top:.3rem;}
.eb-oauth{display:block;text-align:center;padding:.55rem 1rem;margin:.3rem 0;border-radius:10px;border:1px solid var(--line);background:var(--surface2);color:var(--text)!important;text-decoration:none!important;font-weight:500;transition:all .2s;}
.eb-oauth:hover{border-color:var(--cyan);box-shadow:0 0 14px rgba(34,211,238,.35);}
.eb-oauth.off{opacity:.5;pointer-events:none;}
.stButton>button,.stFormSubmitButton>button{border-radius:10px;border:1px solid var(--violet);transition:all .2s;}
.stButton>button:hover,.stFormSubmitButton>button:hover{border-color:var(--cyan);box-shadow:0 0 14px rgba(34,211,238,.35);color:var(--cyan);}
.stFormSubmitButton>button[kind="primaryFormSubmit"],.stButton>button[kind="primary"]{background:linear-gradient(135deg,#7C3AED,#8B5CF6);color:#fff;border:none;}
[data-testid="stForm"]{border:1px solid var(--line);border-radius:14px;background:var(--surface);}
@media (max-width:768px){.block-container{padding:1rem .8rem;}.eb-av{width:42px;height:42px;}.eb-stat .n{font-size:1.5rem;}}
</style>
"""


def inject() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def esc(text) -> str:
    return html.escape(str(text if text is not None else ""))


def initials(name: str) -> str:
    parts = (name or "?").split()
    return "".join(p[0] for p in parts[:2]).upper() or "?"


def avatar(user_id: int, name: str, has_avatar: bool = True, size: int = None) -> str:
    style = f' style="width:{size}px;height:{size}px;"' if size else ""
    uri = svc.avatar_data_uri(user_id) if has_avatar else None
    if uri:
        return f'<img class="eb-av" src="{uri}" alt="{esc(name)}"{style}>'
    return f'<div class="eb-av ph"{style}>{esc(initials(name))}</div>'


def chips(items, kind: str = "") -> str:
    if isinstance(items, str):
        items = [i.strip() for i in items.split(",") if i.strip()]
    return "".join(f'<span class="eb-chip {kind}">{esc(i)}</span>' for i in items)


STATUS_KIND = {"pending": "warn", "accepted": "ok", "active": "ok", "completed": "ok", "forming": "warn",
               "rejected": "bad", "cancelled": "bad", "ended": "bad", "invited": "warn", "scheduled": "warn"}


def status_chip(status: str) -> str:
    return f'<span class="eb-chip {STATUS_KIND.get(status, "")}">{esc(status.title())}</span>'


def card(inner_html: str, extra_class: str = "") -> None:
    st.markdown(f'<div class="eb-card {extra_class}">{inner_html}</div>', unsafe_allow_html=True)


def person_card(user_id, name, has_avatar, title="", sub="", body="", chip_html="") -> None:
    card(
        f'<div class="eb-row">{avatar(user_id, name, has_avatar)}<div>'
        f'<div class="eb-title">{esc(name)}</div>'
        + (f'<div class="eb-sub">{esc(title)}</div>' if title else "")
        + (f'<div class="eb-sub">{sub}</div>' if sub else "")
        + (f'<div class="eb-body">{esc(body)}</div>' if body else "")
        + (f"<div>{chip_html}</div>" if chip_html else "")
        + "</div></div>"
    )


def stat(value, label: str) -> str:
    return f'<div class="eb-stat"><div class="n">{esc(value)}</div><div class="l">{esc(label)}</div></div>'
