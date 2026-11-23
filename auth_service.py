"""Authentication: registration, login, sessions, password reset, Google/GitHub OAuth."""
import base64
import hashlib
import hmac
import re
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from urllib.parse import urlencode

import requests

import config
import database as db
from database import DatabaseError, IntegrityViolation, now_iso

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
SESSION_HOURS_DEFAULT = 12
SESSION_DAYS_REMEMBER = 30
RESET_MINUTES = 60


class AuthError(Exception):
    """Error whose message is safe to show to the user."""


# ---------- helpers ----------
def _future(**kw) -> str:
    return (datetime.now(timezone.utc) + timedelta(**kw)).strftime("%Y-%m-%dT%H:%M:%S")


def _sha(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def validate_email(email: str) -> bool:
    return bool(EMAIL_RE.match(normalize_email(email))) and len(email) <= 254


def validate_password(pw: str) -> list:
    """Return a list of problems (empty list means the password is acceptable)."""
    problems = []
    if len(pw or "") < 8:
        problems.append("at least 8 characters")
    if not re.search(r"[A-Za-z]", pw or ""):
        problems.append("a letter")
    if not re.search(r"\d", pw or ""):
        problems.append("a number")
    return problems


# ---------- password hashing (scrypt, per-user salt) ----------
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    n, r, p = 2 ** 14, 8, 1
    dk = hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=32)
    return "scrypt${}${}${}${}${}".format(
        n, r, p, base64.b64encode(salt).decode(), base64.b64encode(dk).decode()
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, dk = stored.split("$")
        if scheme != "scrypt":
            return False
        calc = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=32
        )
        return hmac.compare_digest(calc, base64.b64decode(dk))
    except Exception:
        return False


# ---------- users ----------
def _create_profile_rows(user_id: int, role: str) -> None:
    db.execute("INSERT INTO student_profiles (user_id) VALUES (?)", (user_id,)) if role == "student" else \
        db.execute("INSERT INTO tutor_profiles (user_id) VALUES (?)", (user_id,))


def register_user(full_name: str, email: str, password: str, confirm: str, role: str) -> dict:
    full_name = (full_name or "").strip()
    email = normalize_email(email)
    if not full_name or len(full_name) > 100:
        raise AuthError("Please enter your full name (up to 100 characters).")
    if not validate_email(email):
        raise AuthError("Please enter a valid email address.")
    problems = validate_password(password)
    if problems:
        raise AuthError("Password needs " + ", ".join(problems) + ".")
    if password != confirm:
        raise AuthError("Passwords do not match.")
    if role not in ("student", "tutor"):
        raise AuthError("Please choose a student or tutor account.")
    if db.query_one("SELECT id FROM users WHERE email = ?", (email,)):
        raise AuthError("An account with this email already exists. Try logging in.")
    try:
        uid = db.insert(
            "INSERT INTO users (email, full_name, password_hash, role, created_at) VALUES (?,?,?,?,?)",
            (email, full_name, hash_password(password), role, now_iso()),
        )
        _create_profile_rows(uid, role)
    except IntegrityViolation:
        raise AuthError("An account with this email already exists. Try logging in.")
    return get_user(uid)


def get_user(user_id: int):
    return db.query_one(
        "SELECT id, email, full_name, role, is_active FROM users WHERE id = ?", (user_id,)
    )


def authenticate(email: str, password: str) -> dict:
    email = normalize_email(email)
    if not email or not password:
        raise AuthError("Enter your email and password.")
    row = db.query_one("SELECT * FROM users WHERE email = ?", (email,))
    if not row:
        raise AuthError("No account found with that email.")
    if not row["password_hash"]:
        raise AuthError("This account uses Google or GitHub sign-in. Use that button, or reset your password to add one.")
    if not verify_password(password, row["password_hash"]):
        raise AuthError("Incorrect password.")
    if not row["is_active"]:
        raise AuthError("This account has been deactivated.")
    return get_user(row["id"])


# ---------- sessions ----------
def create_session(user_id: int, remember: bool = False) -> str:
    token = secrets.token_urlsafe(32)
    exp = _future(days=SESSION_DAYS_REMEMBER) if remember else _future(hours=SESSION_HOURS_DEFAULT)
    db.execute("DELETE FROM sessions WHERE expires_at < ?", (now_iso(),))
    db.execute(
        "INSERT INTO sessions (token_hash, user_id, expires_at, created_at) VALUES (?,?,?,?)",
        (_sha(token), user_id, exp, now_iso()),
    )
    return token


def get_session_user(token: str):
    if not token:
        return None
    row = db.query_one(
        "SELECT user_id, expires_at FROM sessions WHERE token_hash = ?", (_sha(token),)
    )
    if not row or row["expires_at"] < now_iso():
        return None
    user = get_user(row["user_id"])
    return user if user and user["is_active"] else None


def delete_session(token: str) -> None:
    if token:
        db.execute("DELETE FROM sessions WHERE token_hash = ?", (_sha(token),))


# ---------- email / password reset ----------
def smtp_configured() -> bool:
    return bool(config.get("SMTP_HOST") and config.get("SMTP_FROM"))


def send_email(to: str, subject: str, body: str) -> None:
    if not smtp_configured():
        raise AuthError("Email sending is not configured on this server. Ask the site admin to set the SMTP settings.")
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = config.get("SMTP_FROM"), to, subject
    msg.set_content(body)
    host, port = config.get("SMTP_HOST"), int(config.get("SMTP_PORT", "587"))
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=20)
        else:
            server = smtplib.SMTP(host, port, timeout=20)
            server.starttls()
        with server:
            if config.get("SMTP_USER"):
                server.login(config.get("SMTP_USER"), config.get("SMTP_PASSWORD"))
            server.send_message(msg)
    except Exception as exc:
        raise AuthError("We could not send the email right now. Please try again later.") from exc


def request_password_reset(email: str) -> None:
    """Always behaves the same for unknown emails (no account enumeration)."""
    email = normalize_email(email)
    if not validate_email(email):
        raise AuthError("Please enter a valid email address.")
    if not smtp_configured():
        raise AuthError("Email sending is not configured on this server. Ask the site admin to set the SMTP settings.")
    user = db.query_one("SELECT id, full_name FROM users WHERE email = ?", (email,))
    if not user:
        return
    token = secrets.token_urlsafe(32)
    db.execute("DELETE FROM password_resets WHERE user_id = ?", (user["id"],))
    db.execute(
        "INSERT INTO password_resets (token_hash, user_id, expires_at, created_at) VALUES (?,?,?,?)",
        (_sha(token), user["id"], _future(minutes=RESET_MINUTES), now_iso()),
    )
    link = f"{config.base_url()}/?reset={token}"
    send_email(
        email,
        "Reset your EduBridge-AI password",
        f"Hi {user['full_name']},\n\nUse this link to set a new password (valid for {RESET_MINUTES} minutes):\n{link}\n\n"
        "If you did not request this, you can ignore this email.",
    )


def validate_reset_token(token: str):
    row = db.query_one("SELECT user_id, expires_at, used FROM password_resets WHERE token_hash = ?", (_sha(token or ""),))
    if not row or row["used"] or row["expires_at"] < now_iso():
        return None
    return row["user_id"]


def reset_password(token: str, password: str, confirm: str) -> None:
    uid = validate_reset_token(token)
    if uid is None:
        raise AuthError("This reset link is invalid or has expired. Please request a new one.")
    problems = validate_password(password)
    if problems:
        raise AuthError("Password needs " + ", ".join(problems) + ".")
    if password != confirm:
        raise AuthError("Passwords do not match.")
    db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(password), uid))
    db.execute("UPDATE password_resets SET used = 1 WHERE token_hash = ?", (_sha(token),))
    db.execute("DELETE FROM sessions WHERE user_id = ?", (uid,))  # sign out everywhere


def change_password(user_id: int, current: str, new: str, confirm: str) -> None:
    row = db.query_one("SELECT password_hash FROM users WHERE id = ?", (user_id,))
    if row and row["password_hash"] and not verify_password(current, row["password_hash"]):
        raise AuthError("Current password is incorrect.")
    problems = validate_password(new)
    if problems:
        raise AuthError("Password needs " + ", ".join(problems) + ".")
    if new != confirm:
        raise AuthError("Passwords do not match.")
    db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(new), user_id))


# ---------- OAuth (Google + GitHub) ----------
PROVIDERS = {
    "google": {
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "scope": "openid email profile",
        "id_key": "GOOGLE_CLIENT_ID",
        "secret_key": "GOOGLE_CLIENT_SECRET",
    },
    "github": {
        "auth_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "scope": "read:user user:email",
        "id_key": "GITHUB_CLIENT_ID",
        "secret_key": "GITHUB_CLIENT_SECRET",
    },
}


def provider_configured(provider: str) -> bool:
    p = PROVIDERS[provider]
    return bool(config.get(p["id_key"]) and config.get(p["secret_key"]))


def oauth_authorize_url(provider: str) -> str:
    p = PROVIDERS[provider]
    state = secrets.token_urlsafe(24)
    db.execute("DELETE FROM oauth_states WHERE expires_at < ?", (now_iso(),))
    db.execute(
        "INSERT INTO oauth_states (state, provider, expires_at) VALUES (?,?,?)",
        (state, provider, _future(minutes=10)),
    )
    params = {
        "client_id": config.get(p["id_key"]),
        "redirect_uri": config.oauth_redirect_uri(),
        "response_type": "code",
        "scope": p["scope"],
        "state": state,
    }
    if provider == "google":
        params["prompt"] = "select_account"
    return p["auth_url"] + "?" + urlencode(params)


def _exchange_code(provider: str, code: str) -> str:
    p = PROVIDERS[provider]
    try:
        resp = requests.post(
            p["token_url"],
            data={
                "client_id": config.get(p["id_key"]),
                "client_secret": config.get(p["secret_key"]),
                "code": code,
                "redirect_uri": config.oauth_redirect_uri(),
                "grant_type": "authorization_code",
            },
            headers={"Accept": "application/json"},
            timeout=15,
        )
        data = resp.json()
    except Exception as exc:
        raise AuthError(f"Could not reach {provider.title()}. Please try again.") from exc
    token = data.get("access_token")
    if not token:
        raise AuthError(f"{provider.title()} sign-in failed ({data.get('error_description') or data.get('error') or 'no token returned'}).")
    return token


def _fetch_identity(provider: str, access_token: str) -> dict:
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    try:
        if provider == "google":
            info = requests.get("https://openidconnect.googleapis.com/v1/userinfo", headers=headers, timeout=15).json()
            if not info.get("email") or not info.get("email_verified"):
                raise AuthError("Your Google account does not have a verified email address.")
            return {"id": str(info["sub"]), "email": info["email"], "name": info.get("name") or info["email"].split("@")[0]}
        info = requests.get("https://api.github.com/user", headers=headers, timeout=15).json()
        emails = requests.get("https://api.github.com/user/emails", headers=headers, timeout=15).json()
        verified = [e for e in emails if isinstance(e, dict) and e.get("verified")]
        primary = next((e for e in verified if e.get("primary")), verified[0] if verified else None)
        if not primary or "id" not in info:
            raise AuthError("Your GitHub account has no verified email address. Verify one on GitHub and try again.")
        return {"id": str(info["id"]), "email": primary["email"], "name": info.get("name") or info.get("login") or primary["email"].split("@")[0]}
    except AuthError:
        raise
    except Exception as exc:
        raise AuthError(f"Could not read your {provider.title()} profile. Please try again.") from exc


def oauth_complete(state: str, code: str) -> dict:
    """Finish an OAuth login. Returns the user row; raises AuthError on any failure."""
    row = db.query_one("SELECT provider, expires_at FROM oauth_states WHERE state = ?", (state or "",))
    if not row or row["expires_at"] < now_iso():
        raise AuthError("Sign-in session expired or was invalid. Please try again.")
    db.execute("DELETE FROM oauth_states WHERE state = ?", (state,))  # single use
    provider = row["provider"]
    ident = _fetch_identity(provider, _exchange_code(provider, code))
    linked = db.query_one(
        "SELECT user_id FROM auth_identities WHERE provider = ? AND provider_user_id = ?", (provider, ident["id"])
    )
    if linked:
        user = get_user(linked["user_id"])
    else:
        email = normalize_email(ident["email"])
        user = db.query_one("SELECT id, email, full_name, role, is_active FROM users WHERE email = ?", (email,))
        if not user:  # new account (students by default; role can be changed in Profile)
            uid = db.insert(
                "INSERT INTO users (email, full_name, password_hash, role, created_at) VALUES (?,?,NULL,'student',?)",
                (email, ident["name"][:100], now_iso()),
            )
            _create_profile_rows(uid, "student")
            user = get_user(uid)
        db.execute(
            "INSERT INTO auth_identities (user_id, provider, provider_user_id, created_at) VALUES (?,?,?,?)",
            (user["id"], provider, ident["id"], now_iso()),
        )
    if not user or not user["is_active"]:
        raise AuthError("This account has been deactivated.")
    return user


def has_password(user_id: int) -> bool:
    row = db.query_one("SELECT password_hash FROM users WHERE id = ?", (user_id,))
    return bool(row and row["password_hash"])
