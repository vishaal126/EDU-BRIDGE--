"""Shared backend services: profiles, marketplace, connections, messaging, skills,
skill-exchange groups, learning sessions, feedback, notifications and AI history.

Every function takes the acting user's id and enforces authorization itself, so the UI
cannot accidentally expose another user's data.
"""
import re
from datetime import datetime

import database as db
import matching
from database import IntegrityViolation, now_iso
from models import MAX_GROUP_SIZE


class ServiceError(Exception):
    """Error whose message is safe to show to the user."""


def _clean(text, max_len, field="Text", required=False) -> str:
    text = (text or "").strip()
    if required and not text:
        raise ServiceError(f"{field} is required.")
    if len(text) > max_len:
        raise ServiceError(f"{field} must be at most {max_len} characters.")
    return text


def _csv(text: str) -> str:
    """Normalise a comma-separated list: trim, drop blanks, de-duplicate (case-insensitive)."""
    seen, items = set(), []
    for part in (text or "").split(","):
        p = re.sub(r"\s+", " ", part).strip()
        if p and p.lower() not in seen:
            seen.add(p.lower())
            items.append(p)
    return ", ".join(items)


# ====================== notifications ======================
def notify(user_id: int, kind: str, title: str, body: str = "") -> None:
    db.execute(
        "INSERT INTO notifications (user_id, kind, title, body, created_at) VALUES (?,?,?,?,?)",
        (user_id, kind, title[:200], body[:500], now_iso()),
    )


def list_notifications(user_id: int, limit: int = 100) -> list:
    return db.query(
        "SELECT * FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit)
    )


def unread_count(user_id: int) -> int:
    return db.query_one(
        "SELECT COUNT(*) AS c FROM notifications WHERE user_id = ? AND is_read = 0", (user_id,)
    )["c"]


def mark_notification_read(user_id: int, notif_id: int) -> None:
    db.execute("UPDATE notifications SET is_read = 1 WHERE id = ? AND user_id = ?", (notif_id, user_id))


def mark_all_read(user_id: int) -> None:
    db.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (user_id,))


# ====================== profiles ======================
def get_profile(user_id: int) -> dict:
    user = db.query_one(
        "SELECT id, email, full_name, role, created_at, (avatar IS NOT NULL) AS has_avatar FROM users WHERE id = ?",
        (user_id,),
    )
    if not user:
        raise ServiceError("User not found.")
    table = "student_profiles" if user["role"] == "student" else "tutor_profiles"
    extra = db.query_one(f"SELECT * FROM {table} WHERE user_id = ?", (user_id,))
    if extra is None:  # self-heal if the row is missing
        db.execute(f"INSERT INTO {table} (user_id) VALUES (?)", (user_id,))
        extra = db.query_one(f"SELECT * FROM {table} WHERE user_id = ?", (user_id,))
    return {**extra, **user}


def update_account(user_id: int, full_name: str, email: str) -> None:
    import auth_service as auth

    full_name = _clean(full_name, 100, "Full name", True)
    email = auth.normalize_email(email)
    if not auth.validate_email(email):
        raise ServiceError("Please enter a valid email address.")
    clash = db.query_one("SELECT id FROM users WHERE email = ? AND id <> ?", (email, user_id))
    if clash:
        raise ServiceError("That email is already used by another account.")
    db.execute("UPDATE users SET full_name = ?, email = ? WHERE id = ?", (full_name, email, user_id))


def update_student_profile(user_id: int, bio, interests, education, location) -> None:
    db.execute(
        "UPDATE student_profiles SET bio=?, interests=?, education=?, location=? WHERE user_id=?",
        (_clean(bio, 800, "Bio"), _csv(_clean(interests, 400, "Interests")),
         _clean(education, 200, "Education"), _clean(location, 100, "Location"), user_id),
    )


def update_tutor_profile(user_id, headline, description, subjects, skills, experience_years,
                         qualifications, availability, location, is_published) -> None:
    subjects = _csv(_clean(subjects, 300, "Subjects"))
    if is_published and not subjects:
        raise ServiceError("Add at least one subject before publishing your profile.")
    if is_published and not _clean(description, 1500):
        raise ServiceError("Add a description before publishing your profile.")
    if not 0 <= int(experience_years) <= 60:
        raise ServiceError("Experience must be between 0 and 60 years.")
    db.execute(
        """UPDATE tutor_profiles SET headline=?, description=?, subjects=?, skills=?, experience_years=?,
           qualifications=?, availability=?, location=?, is_published=? WHERE user_id=?""",
        (_clean(headline, 120, "Headline"), _clean(description, 1500, "Description"), subjects,
         _csv(_clean(skills, 300, "Skills")), int(experience_years),
         _clean(qualifications, 500, "Qualifications"), _clean(availability, 300, "Availability"),
         _clean(location, 100, "Location"), 1 if is_published else 0, user_id),
    )


def set_avatar(user_id: int, data: bytes, mime: str) -> None:
    if mime not in ("image/png", "image/jpeg", "image/webp"):
        raise ServiceError("Please upload a PNG, JPG or WebP image.")
    if len(data) > 1_500_000:
        raise ServiceError("Image is too large (max 1.5 MB).")
    magic_ok = data[:8] == b"\x89PNG\r\n\x1a\n" or data[:3] == b"\xff\xd8\xff" or (data[:4] == b"RIFF" and data[8:12] == b"WEBP")
    if not magic_ok:
        raise ServiceError("That file is not a valid image.")
    db.execute("UPDATE users SET avatar = ?, avatar_mime = ? WHERE id = ?", (data, mime, user_id))


def get_avatar(user_id: int):
    row = db.query_one("SELECT avatar FROM users WHERE id = ?", (user_id,))
    return bytes(row["avatar"]) if row and row["avatar"] else None


def change_role(user_id: int, new_role: str) -> None:
    if new_role not in ("student", "tutor"):
        raise ServiceError("Invalid role.")
    cur = db.query_one("SELECT role FROM users WHERE id = ?", (user_id,))
    if cur["role"] == new_role:
        return
    if db.query_one("SELECT id FROM connections WHERE student_id = ? OR tutor_id = ?", (user_id, user_id)) or \
       db.query_one("SELECT id FROM group_members WHERE user_id = ?", (user_id,)):
        raise ServiceError("You can't switch account type while you have connections or exchange groups.")
    table = "student_profiles" if new_role == "student" else "tutor_profiles"
    db.execute("UPDATE users SET role = ? WHERE id = ?", (new_role, user_id))
    if not db.query_one(f"SELECT user_id FROM {table} WHERE user_id = ?", (user_id,)):
        db.execute(f"INSERT INTO {table} (user_id) VALUES (?)", (user_id,))


# ====================== tutor marketplace ======================
def list_subjects() -> list:
    rows = db.query("SELECT subjects FROM tutor_profiles WHERE is_published = 1")
    found = {}
    for r in rows:
        for s in r["subjects"].split(","):
            s = s.strip()
            if s:
                found.setdefault(s.lower(), s)
    return sorted(found.values(), key=str.lower)


def search_tutors(student_id: int, query_text: str = "", subject: str = "") -> list:
    rows = db.query(
        """SELECT u.id, u.full_name, (u.avatar IS NOT NULL) AS has_avatar, t.*
           FROM tutor_profiles t JOIN users u ON u.id = t.user_id
           WHERE t.is_published = 1 AND u.is_active = 1 AND u.id <> ?
           ORDER BY u.full_name""",
        (student_id,),
    )
    q, subj = (query_text or "").strip().lower(), (subject or "").strip().lower()
    out = []
    for r in rows:
        subjects = [s.strip().lower() for s in r["subjects"].split(",") if s.strip()]
        if subj and subj not in subjects:
            continue
        hay = " ".join([r["full_name"], r["headline"], r["subjects"], r["skills"], r["description"]]).lower()
        if q and q not in hay:
            continue
        conn = db.query_one(
            "SELECT id, status FROM connections WHERE student_id = ? AND tutor_id = ?", (student_id, r["id"])
        )
        r["connection"] = conn
        out.append(r)
    return out


def get_tutor(tutor_id: int):
    return db.query_one(
        """SELECT u.id, u.full_name, (u.avatar IS NOT NULL) AS has_avatar, t.*
           FROM tutor_profiles t JOIN users u ON u.id = t.user_id
           WHERE u.id = ? AND t.is_published = 1 AND u.is_active = 1""",
        (tutor_id,),
    )


def recommended_tutors(student_id: int, limit: int = 3) -> list:
    """Tutors whose subjects overlap with the student's interests or skills-to-learn."""
    prof = get_profile(student_id)
    wants = {s.strip().lower() for s in prof.get("interests", "").split(",") if s.strip()}
    wants |= {s["name_norm"] for s in db.query("SELECT name_norm FROM skills WHERE user_id=? AND kind='learn'", (student_id,))}
    scored = []
    for t in search_tutors(student_id):
        if t["connection"] and t["connection"]["status"] in ("pending", "accepted"):
            continue
        tags = {s.strip().lower() for s in (t["subjects"] + "," + t["skills"]).split(",") if s.strip()}
        overlap = sum(1 for w in wants if any(w in tag or tag in w for tag in tags))
        if overlap:
            scored.append((overlap, t))
    scored.sort(key=lambda x: -x[0])
    return [t for _, t in scored[:limit]]


# ====================== tutor <-> student connections ======================
def request_connection(student_id: int, tutor_id: int, message: str = "") -> None:
    student = db.query_one("SELECT role, full_name FROM users WHERE id = ?", (student_id,))
    if not student or student["role"] != "student":
        raise ServiceError("Only student accounts can send connection requests.")
    if not get_tutor(tutor_id):
        raise ServiceError("That tutor is not available.")
    message = _clean(message, 500, "Message")
    existing = db.query_one("SELECT id, status FROM connections WHERE student_id=? AND tutor_id=?", (student_id, tutor_id))
    try:
        if existing:
            if existing["status"] in ("pending", "accepted"):
                raise ServiceError("You already have a pending or active connection with this tutor.")
            db.execute("UPDATE connections SET status='pending', intro_message=?, created_at=?, responded_at=NULL WHERE id=?",
                       (message, now_iso(), existing["id"]))
        else:
            db.insert("INSERT INTO connections (student_id, tutor_id, status, intro_message, created_at) VALUES (?,?,?,?,?)",
                      (student_id, tutor_id, "pending", message, now_iso()))
    except IntegrityViolation:
        raise ServiceError("You already have a connection with this tutor.")
    notify(tutor_id, "connection_request", f"New connection request from {student['full_name']}", message)


def respond_connection(tutor_id: int, conn_id: int, accept: bool) -> None:
    conn = db.query_one("SELECT * FROM connections WHERE id = ? AND tutor_id = ?", (conn_id, tutor_id))
    if not conn:
        raise ServiceError("Request not found.")
    if conn["status"] != "pending":
        raise ServiceError("This request has already been answered.")
    status = "accepted" if accept else "rejected"
    db.execute("UPDATE connections SET status=?, responded_at=? WHERE id=?", (status, now_iso(), conn_id))
    tutor = db.query_one("SELECT full_name FROM users WHERE id=?", (tutor_id,))
    notify(conn["student_id"], "connection_response",
           f"{tutor['full_name']} {'accepted' if accept else 'declined'} your request",
           "You can now message each other." if accept else "")


def end_connection(user_id: int, conn_id: int) -> None:
    conn = _get_conn(user_id, conn_id)
    if conn["status"] != "accepted":
        raise ServiceError("Only active connections can be ended.")
    db.execute("UPDATE connections SET status='ended', responded_at=? WHERE id=?", (now_iso(), conn_id))
    other = conn["tutor_id"] if user_id == conn["student_id"] else conn["student_id"]
    me = db.query_one("SELECT full_name FROM users WHERE id=?", (user_id,))
    notify(other, "connection_response", f"{me['full_name']} ended the connection")


def _get_conn(user_id: int, conn_id: int) -> dict:
    conn = db.query_one(
        "SELECT * FROM connections WHERE id = ? AND (student_id = ? OR tutor_id = ?)", (conn_id, user_id, user_id)
    )
    if not conn:
        raise ServiceError("Conversation not found.")  # same message whether missing or not yours
    return conn


def list_connections(user_id: int, role: str, statuses=None) -> list:
    me_col, other_col = ("student_id", "tutor_id") if role == "student" else ("tutor_id", "student_id")
    rows = db.query(
        f"""SELECT c.*, u.id AS other_id, u.full_name AS other_name, u.email AS other_email,
                   (u.avatar IS NOT NULL) AS other_has_avatar
            FROM connections c JOIN users u ON u.id = c.{other_col}
            WHERE c.{me_col} = ? ORDER BY c.id DESC""",
        (user_id,),
    )
    if statuses:
        rows = [r for r in rows if r["status"] in statuses]
    for r in rows:
        if r["status"] != "accepted":
            r["other_email"] = None  # contact details only after acceptance
    return rows


def send_message(user_id: int, conn_id: int, body: str) -> None:
    conn = _get_conn(user_id, conn_id)
    if conn["status"] != "accepted":
        raise ServiceError("You can only message people you're connected with.")
    body = _clean(body, 2000, "Message", True)
    db.insert("INSERT INTO messages (connection_id, sender_id, body, created_at) VALUES (?,?,?,?)",
              (conn_id, user_id, body, now_iso()))
    other = conn["tutor_id"] if user_id == conn["student_id"] else conn["student_id"]
    me = db.query_one("SELECT full_name FROM users WHERE id=?", (user_id,))
    # one unread notification per conversation, so a chat doesn't flood the inbox
    if not db.query_one("SELECT id FROM notifications WHERE user_id=? AND kind='message' AND is_read=0 AND title=?",
                        (other, f"New message from {me['full_name']}")):
        notify(other, "message", f"New message from {me['full_name']}", body[:140])


def get_messages(user_id: int, conn_id: int) -> list:
    _get_conn(user_id, conn_id)
    return db.query(
        """SELECT m.id, m.sender_id, m.body, m.created_at, u.full_name AS sender_name
           FROM messages m JOIN users u ON u.id = m.sender_id
           WHERE m.connection_id = ? ORDER BY m.id""",
        (conn_id,),
    )


# ====================== skills ======================
def _norm_skill(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip()).lower()


def add_skill(user_id: int, name: str, kind: str) -> None:
    if kind not in ("teach", "learn"):
        raise ServiceError("Invalid skill type.")
    name = re.sub(r"\s+", " ", (name or "").strip())
    if not 2 <= len(name) <= 50:
        raise ServiceError("Skill names must be 2 to 50 characters.")
    norm = _norm_skill(name)
    opposite = "learn" if kind == "teach" else "teach"
    if db.query_one("SELECT id FROM skills WHERE user_id=? AND name_norm=? AND kind=?", (user_id, norm, opposite)):
        raise ServiceError(f"'{name}' is already on your {opposite} list. A skill can't be on both lists.")
    count = db.query_one("SELECT COUNT(*) AS c FROM skills WHERE user_id=? AND kind=?", (user_id, kind))["c"]
    if count >= 20:
        raise ServiceError("You can list up to 20 skills in each category.")
    try:
        db.insert("INSERT INTO skills (user_id, name, name_norm, kind, created_at) VALUES (?,?,?,?,?)",
                  (user_id, name, norm, kind, now_iso()))
    except IntegrityViolation:
        raise ServiceError(f"'{name}' is already on your list.")


def remove_skill(user_id: int, skill_id: int) -> None:
    db.execute("DELETE FROM skills WHERE id=? AND user_id=?", (skill_id, user_id))


def list_skills(user_id: int) -> dict:
    rows = db.query("SELECT id, name, kind FROM skills WHERE user_id=? ORDER BY name_norm", (user_id,))
    return {"teach": [r for r in rows if r["kind"] == "teach"], "learn": [r for r in rows if r["kind"] == "learn"]}


def _skill_profiles() -> dict:
    rows = db.query(
        """SELECT u.id, u.full_name, s.name_norm, s.kind FROM users u
           JOIN skills s ON s.user_id = u.id WHERE u.role = 'student' AND u.is_active = 1"""
    )
    profiles = {}
    for r in rows:
        p = profiles.setdefault(r["id"], {"name": r["full_name"], "teach": set(), "learn": set()})
        p[r["kind"]].add(r["name_norm"])
    return profiles


def get_matches(user_id: int) -> dict:
    """Pair and three-person-cycle matches for this student, with member names attached."""
    profiles = _skill_profiles()
    result = matching.find_matches(user_id, profiles)
    for m in result["pairs"] + result["triangles"]:
        m["names"] = {uid: profiles[uid]["name"] for uid in m["members"]}
    return result


# ====================== skill-exchange groups ======================
def _group_member(user_id: int, group_id: int, statuses=("active",)):
    row = db.query_one("SELECT * FROM group_members WHERE group_id=? AND user_id=?", (group_id, user_id))
    if not row or row["status"] not in statuses:
        raise ServiceError("Group not found.")
    return row


def _group(group_id: int) -> dict:
    g = db.query_one("SELECT * FROM exchange_groups WHERE id = ?", (group_id,))
    if not g:
        raise ServiceError("Group not found.")
    return g


def _name(user_id: int) -> str:
    return db.query_one("SELECT full_name FROM users WHERE id=?", (user_id,))["full_name"]


def _count_live(group_id: int) -> int:
    return db.query_one(
        "SELECT COUNT(*) AS c FROM group_members WHERE group_id=? AND status IN ('active','invited')", (group_id,)
    )["c"]


def _notify_members(group_id: int, title: str, body: str = "", exclude=None, statuses=("active",)) -> None:
    marks = ",".join("?" * len(statuses))
    for m in db.query(f"SELECT user_id FROM group_members WHERE group_id=? AND status IN ({marks})", (group_id, *statuses)):
        if m["user_id"] != exclude:
            notify(m["user_id"], "group", title, body)


def create_group(creator_id: int, name: str, invitee_ids: list) -> int:
    name = _clean(name, 80, "Group name", True)
    invitee_ids = list(dict.fromkeys(invitee_ids))
    if creator_id in invitee_ids:
        raise ServiceError("You can't invite yourself.")
    if not 1 <= len(invitee_ids) <= MAX_GROUP_SIZE - 1:
        raise ServiceError("Invite one or two other students (groups have 2 or 3 members).")
    for uid in [creator_id, *invitee_ids]:
        u = db.query_one("SELECT role, is_active FROM users WHERE id=?", (uid,))
        if not u or u["role"] != "student" or not u["is_active"]:
            raise ServiceError("Skill exchange groups are for student accounts only.")
    gid = db.insert("INSERT INTO exchange_groups (name, creator_id, status, created_at) VALUES (?,?,?,?)",
                    (name, creator_id, "forming", now_iso()))
    db.insert("INSERT INTO group_members (group_id, user_id, status, created_at) VALUES (?,?,?,?)",
              (gid, creator_id, "active", now_iso()))
    for uid in invitee_ids:
        db.insert("INSERT INTO group_members (group_id, user_id, status, invited_by, created_at) VALUES (?,?,?,?,?)",
                  (gid, uid, "invited", creator_id, now_iso()))
        notify(uid, "group_invite", f"{_name(creator_id)} invited you to '{name}'", "Open Skill Exchange to accept or decline.")
    return gid


def invite_to_group(inviter_id: int, group_id: int, invitee_id: int) -> None:
    _group_member(inviter_id, group_id)
    g = _group(group_id)
    if g["status"] not in ("forming", "active"):
        raise ServiceError("This group is no longer open for new members.")
    if _count_live(group_id) >= MAX_GROUP_SIZE:
        raise ServiceError(f"Groups can have at most {MAX_GROUP_SIZE} members.")
    u = db.query_one("SELECT role, is_active FROM users WHERE id=?", (invitee_id,))
    if not u or u["role"] != "student" or not u["is_active"]:
        raise ServiceError("You can only invite student accounts.")
    existing = db.query_one("SELECT status FROM group_members WHERE group_id=? AND user_id=?", (group_id, invitee_id))
    if existing and existing["status"] in ("active", "invited"):
        raise ServiceError("That student is already in (or invited to) this group.")
    if existing:
        db.execute("UPDATE group_members SET status='invited', invited_by=?, created_at=? WHERE group_id=? AND user_id=?",
                   (inviter_id, now_iso(), group_id, invitee_id))
    else:
        db.insert("INSERT INTO group_members (group_id, user_id, status, invited_by, created_at) VALUES (?,?,?,?,?)",
                  (group_id, invitee_id, "invited", inviter_id, now_iso()))
    notify(invitee_id, "group_invite", f"{_name(inviter_id)} invited you to '{g['name']}'", "Open Skill Exchange to accept or decline.")


def respond_invite(user_id: int, group_id: int, accept: bool) -> None:
    _group_member(user_id, group_id, ("invited",))
    g = _group(group_id)
    if g["status"] not in ("forming", "active"):
        raise ServiceError("This group is no longer open.")
    db.execute("UPDATE group_members SET status=? WHERE group_id=? AND user_id=?",
               ("active" if accept else "declined", group_id, user_id))
    me = _name(user_id)
    _notify_members(group_id, f"{me} {'joined' if accept else 'declined to join'} '{g['name']}'", exclude=user_id)
    _refresh_group_status(group_id)


def _refresh_group_status(group_id: int) -> None:
    g = _group(group_id)
    if g["status"] in ("completed", "cancelled"):
        return
    active = db.query_one("SELECT COUNT(*) AS c FROM group_members WHERE group_id=? AND status='active'", (group_id,))["c"]
    invited = db.query_one("SELECT COUNT(*) AS c FROM group_members WHERE group_id=? AND status='invited'", (group_id,))["c"]
    if active >= 2 and g["status"] == "forming":
        db.execute("UPDATE exchange_groups SET status='active' WHERE id=?", (group_id,))
        _notify_members(group_id, f"'{g['name']}' is now active", "You can start scheduling learning sessions.")
    elif active < 2 and invited == 0:
        db.execute("UPDATE exchange_groups SET status='cancelled' WHERE id=?", (group_id,))
        _notify_members(group_id, f"'{g['name']}' was cancelled", "Not enough members remain.")


def leave_group(user_id: int, group_id: int) -> None:
    _group_member(user_id, group_id)
    g = _group(group_id)
    db.execute("UPDATE group_members SET status='left' WHERE group_id=? AND user_id=?", (group_id, user_id))
    _notify_members(group_id, f"{_name(user_id)} left '{g['name']}'", exclude=user_id)
    _refresh_group_status(group_id)


def complete_group(user_id: int, group_id: int) -> None:
    _group_member(user_id, group_id)
    g = _group(group_id)
    if g["status"] != "active":
        raise ServiceError("Only active exchanges can be marked completed.")
    db.execute("UPDATE exchange_groups SET status='completed', completed_at=? WHERE id=?", (now_iso(), group_id))
    _notify_members(group_id, f"'{g['name']}' was marked completed", "Please leave feedback for your group members.", exclude=user_id)


def list_groups(user_id: int) -> list:
    groups = db.query(
        """SELECT g.*, gm.status AS my_status FROM exchange_groups g
           JOIN group_members gm ON gm.group_id = g.id
           WHERE gm.user_id = ? AND gm.status IN ('active','invited') ORDER BY g.id DESC""",
        (user_id,),
    )
    for g in groups:
        g["members"] = group_members(g["id"])
    return groups


def group_members(group_id: int) -> list:
    members = db.query(
        """SELECT gm.user_id, gm.status, u.full_name, (u.avatar IS NOT NULL) AS has_avatar
           FROM group_members gm JOIN users u ON u.id = gm.user_id
           WHERE gm.group_id = ? AND gm.status IN ('active','invited') ORDER BY gm.id""",
        (group_id,),
    )
    for m in members:
        sk = list_skills(m["user_id"])
        m["teach"], m["learn"] = [s["name"] for s in sk["teach"]], [s["name"] for s in sk["learn"]]
    return members


def get_group(user_id: int, group_id: int) -> dict:
    _group_member(user_id, group_id, ("active", "invited"))
    g = _group(group_id)
    g["members"] = group_members(group_id)
    return g


def send_group_message(user_id: int, group_id: int, body: str) -> None:
    _group_member(user_id, group_id)
    if _group(group_id)["status"] == "cancelled":
        raise ServiceError("This group was cancelled.")
    body = _clean(body, 2000, "Message", True)
    db.insert("INSERT INTO group_messages (group_id, sender_id, body, created_at) VALUES (?,?,?,?)",
              (group_id, user_id, body, now_iso()))


def get_group_messages(user_id: int, group_id: int) -> list:
    _group_member(user_id, group_id)
    return db.query(
        """SELECT m.id, m.sender_id, m.body, m.created_at, u.full_name AS sender_name
           FROM group_messages m JOIN users u ON u.id = m.sender_id
           WHERE m.group_id = ? ORDER BY m.id""",
        (group_id,),
    )


# ---- learning sessions ----
def schedule_session(user_id, group_id, title, scheduled_at: datetime, duration_min, teacher_id, meeting_link="", notes="") -> None:
    _group_member(user_id, group_id)
    g = _group(group_id)
    if g["status"] != "active":
        raise ServiceError("Sessions can only be scheduled for active exchanges.")
    title = _clean(title, 120, "Session title", True)
    if not 15 <= int(duration_min) <= 480:
        raise ServiceError("Duration must be between 15 and 480 minutes.")
    if teacher_id:
        _group_member(teacher_id, group_id)
    db.insert(
        """INSERT INTO learning_sessions (group_id, title, teacher_id, scheduled_at, duration_min, meeting_link, notes, created_by, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (group_id, title, teacher_id or None, scheduled_at.strftime("%Y-%m-%dT%H:%M"), int(duration_min),
         _clean(meeting_link, 300, "Meeting link"), _clean(notes, 500, "Notes"), user_id, now_iso()),
    )
    _notify_members(group_id, f"New session in '{g['name']}': {title}", scheduled_at.strftime("%d %b %Y, %H:%M"), exclude=user_id)


def list_sessions(user_id: int, group_id: int) -> list:
    _group_member(user_id, group_id, ("active", "invited"))
    return db.query(
        """SELECT s.*, u.full_name AS teacher_name FROM learning_sessions s
           LEFT JOIN users u ON u.id = s.teacher_id WHERE s.group_id = ? ORDER BY s.scheduled_at""",
        (group_id,),
    )


def update_session_status(user_id: int, session_id: int, status: str) -> None:
    if status not in ("completed", "cancelled"):
        raise ServiceError("Invalid status.")
    s = db.query_one("SELECT * FROM learning_sessions WHERE id=?", (session_id,))
    if not s:
        raise ServiceError("Session not found.")
    _group_member(user_id, s["group_id"])
    if s["status"] != "scheduled":
        raise ServiceError("This session was already updated.")
    db.execute("UPDATE learning_sessions SET status=? WHERE id=?", (status, session_id))
    _notify_members(s["group_id"], f"Session '{s['title']}' was {status}", exclude=user_id)


# ---- feedback ----
def submit_feedback(user_id: int, group_id: int, to_user_id: int, rating: int, comment: str = "") -> None:
    _group_member(user_id, group_id)
    _group_member(to_user_id, group_id)
    if _group(group_id)["status"] != "completed":
        raise ServiceError("Feedback opens once the exchange is marked completed.")
    if user_id == to_user_id:
        raise ServiceError("You can't review yourself.")
    if not 1 <= int(rating) <= 5:
        raise ServiceError("Rating must be 1 to 5.")
    try:
        db.insert(
            "INSERT INTO exchange_feedback (group_id, from_user_id, to_user_id, rating, comment, created_at) VALUES (?,?,?,?,?,?)",
            (group_id, user_id, to_user_id, int(rating), _clean(comment, 500, "Comment"), now_iso()),
        )
    except IntegrityViolation:
        raise ServiceError("You've already given feedback to this member.")
    notify(to_user_id, "group", f"{_name(user_id)} left you feedback", f"Rating: {int(rating)}/5")


def feedback_given(user_id: int, group_id: int) -> set:
    _group_member(user_id, group_id)
    return {r["to_user_id"] for r in db.query(
        "SELECT to_user_id FROM exchange_feedback WHERE group_id=? AND from_user_id=?", (group_id, user_id))}


def feedback_received(user_id: int) -> dict:
    row = db.query_one("SELECT AVG(rating) AS avg, COUNT(*) AS n FROM exchange_feedback WHERE to_user_id=?", (user_id,))
    return {"avg": round(row["avg"], 1) if row["avg"] else None, "count": row["n"]}


# ====================== AI conversation history ======================
def create_conversation(user_id: int, title: str = "New chat") -> int:
    return db.insert("INSERT INTO ai_conversations (user_id, title, created_at) VALUES (?,?,?)",
                     (user_id, title[:60], now_iso()))


def list_conversations(user_id: int) -> list:
    return db.query("SELECT id, title, created_at FROM ai_conversations WHERE user_id=? ORDER BY id DESC", (user_id,))


def _own_conv(user_id: int, conv_id: int) -> dict:
    c = db.query_one("SELECT * FROM ai_conversations WHERE id=? AND user_id=?", (conv_id, user_id))
    if not c:
        raise ServiceError("Conversation not found.")
    return c


def get_ai_messages(user_id: int, conv_id: int) -> list:
    _own_conv(user_id, conv_id)
    return db.query("SELECT role, content, created_at FROM ai_messages WHERE conversation_id=? ORDER BY id", (conv_id,))


def add_ai_message(user_id: int, conv_id: int, role: str, content: str) -> None:
    c = _own_conv(user_id, conv_id)
    db.insert("INSERT INTO ai_messages (conversation_id, role, content, created_at) VALUES (?,?,?,?)",
              (conv_id, role, content, now_iso()))
    if role == "user" and c["title"] == "New chat":
        db.execute("UPDATE ai_conversations SET title=? WHERE id=?", (content.strip().replace("\n", " ")[:60], conv_id))


def delete_conversation(user_id: int, conv_id: int) -> None:
    _own_conv(user_id, conv_id)
    db.execute("DELETE FROM ai_conversations WHERE id=?", (conv_id,))


# ====================== dashboard ======================
def dashboard_stats(user_id: int, role: str) -> dict:
    stats = {"unread": unread_count(user_id)}
    col = "student_id" if role == "student" else "tutor_id"
    stats["connections"] = db.query_one(f"SELECT COUNT(*) AS c FROM connections WHERE {col}=? AND status='accepted'", (user_id,))["c"]
    stats["pending"] = db.query_one(f"SELECT COUNT(*) AS c FROM connections WHERE {col}=? AND status='pending'", (user_id,))["c"]
    stats["groups"] = db.query_one("SELECT COUNT(*) AS c FROM group_members gm JOIN exchange_groups g ON g.id=gm.group_id WHERE gm.user_id=? AND gm.status='active' AND g.status IN ('forming','active')", (user_id,))["c"]
    stats["ai_chats"] = db.query_one("SELECT COUNT(*) AS c FROM ai_conversations WHERE user_id=?", (user_id,))["c"]
    return stats


def pending_group_invites(user_id: int) -> int:
    return db.query_one("SELECT COUNT(*) AS c FROM group_members gm JOIN exchange_groups g ON g.id=gm.group_id WHERE gm.user_id=? AND gm.status='invited' AND g.status IN ('forming','active')", (user_id,))["c"]


# ====================== small UI helpers ======================
def avatar_data_uri(user_id: int):
    import base64

    row = db.query_one("SELECT avatar, avatar_mime FROM users WHERE id = ?", (user_id,))
    if not row or not row["avatar"]:
        return None
    return f"data:{row['avatar_mime']};base64," + base64.b64encode(bytes(row["avatar"])).decode()


def popular_skills(limit: int = 12) -> list:
    rows = db.query(
        "SELECT MIN(name) AS name, COUNT(*) AS c FROM skills GROUP BY name_norm ORDER BY c DESC, name_norm LIMIT ?", (limit,)
    )
    return [r["name"] for r in rows]


def find_students(user_id: int, text: str, limit: int = 20) -> list:
    text = (text or "").strip().lower()
    if len(text) < 2:
        return []
    rows = db.query(
        "SELECT id, full_name FROM users WHERE role='student' AND is_active=1 AND id <> ? ORDER BY full_name", (user_id,)
    )
    return [r for r in rows if text in r["full_name"].lower()][:limit]
