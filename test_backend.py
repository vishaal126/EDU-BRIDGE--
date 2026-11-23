import os, sys, tempfile, unittest
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ.pop("DATABASE_URL", None)

import database as db
import auth_service as auth
import services as svc
import matching
from auth_service import AuthError
from services import ServiceError

db.init_db()
_n = [0]


def mk(role="student", name=None):
    _n[0] += 1
    return auth.register_user(name or f"User{_n[0]}", f"u{_n[0]}@example.com", "Passw0rdX", "Passw0rdX", role)


class AuthTests(unittest.TestCase):
    def test_register_login_duplicate(self):
        u = auth.register_user("Ann", "ann@example.com", "abc12345", "abc12345", "student")
        self.assertEqual(auth.authenticate("ANN@example.com", "abc12345")["id"], u["id"])
        with self.assertRaises(AuthError): auth.authenticate("ann@example.com", "wrong1234")
        with self.assertRaises(AuthError): auth.authenticate("nobody@example.com", "abc12345")
        with self.assertRaises(AuthError): auth.register_user("Ann2", "ann@example.com", "abc12345", "abc12345", "student")

    def test_validation(self):
        with self.assertRaises(AuthError): auth.register_user("X", "bad-email", "abc12345", "abc12345", "student")
        with self.assertRaises(AuthError): auth.register_user("X", "x@example.com", "short", "short", "student")
        with self.assertRaises(AuthError): auth.register_user("X", "x2@example.com", "abc12345", "different1", "student")
        with self.assertRaises(AuthError): auth.register_user("X", "x3@example.com", "abc12345", "abc12345", "admin")

    def test_password_not_plaintext(self):
        u = mk()
        row = db.query_one("SELECT password_hash FROM users WHERE id=?", (u["id"],))
        self.assertTrue(row["password_hash"].startswith("scrypt$"))
        self.assertNotIn("Passw0rdX", row["password_hash"])

    def test_sessions(self):
        u = mk()
        t = auth.create_session(u["id"], remember=True)
        self.assertEqual(auth.get_session_user(t)["id"], u["id"])
        self.assertIsNone(auth.get_session_user("garbage"))
        db.execute("UPDATE sessions SET expires_at='2000-01-01T00:00:00'")
        self.assertIsNone(auth.get_session_user(t))
        t2 = auth.create_session(u["id"]); auth.delete_session(t2)
        self.assertIsNone(auth.get_session_user(t2))

    def test_reset_flow(self):
        import secrets
        u = mk()
        token = "tok-" + secrets.token_hex(8)
        db.execute("INSERT INTO password_resets (token_hash, user_id, expires_at, created_at) VALUES (?,?,?,?)",
                   (auth._sha(token), u["id"], auth._future(minutes=30), db.now_iso()))
        self.assertEqual(auth.validate_reset_token(token), u["id"])
        auth.reset_password(token, "NewPass123", "NewPass123")
        self.assertEqual(auth.authenticate(u["email"], "NewPass123")["id"], u["id"])
        with self.assertRaises(AuthError): auth.reset_password(token, "Another123", "Another123")  # single use
        expired = "old-token"
        db.execute("INSERT INTO password_resets (token_hash, user_id, expires_at, created_at) VALUES (?,?,?,?)",
                   (auth._sha(expired), u["id"], "2000-01-01T00:00:00", db.now_iso()))
        with self.assertRaises(AuthError): auth.reset_password(expired, "Another123", "Another123")

    def test_reset_requires_smtp(self):
        os.environ.pop("SMTP_HOST", None)
        with self.assertRaises(AuthError): auth.request_password_reset("a@example.com")

    def test_oauth_state_invalid(self):
        with self.assertRaises(AuthError): auth.oauth_complete("nope", "code")


class OAuthLogicTests(unittest.TestCase):
    """Network calls are mocked: this tests account creation/linking, state handling, not Google/GitHub themselves."""
    def _login(self, provider, ident):
        os.environ["GOOGLE_CLIENT_ID"] = os.environ["GITHUB_CLIENT_ID"] = "id"
        os.environ["GOOGLE_CLIENT_SECRET"] = os.environ["GITHUB_CLIENT_SECRET"] = "secret"
        url = auth.oauth_authorize_url(provider)
        self.assertIn("state=", url); self.assertIn("redirect_uri=", url)
        state = url.split("state=")[1].split("&")[0]
        orig = (auth._exchange_code, auth._fetch_identity)
        auth._exchange_code = lambda p, c: "tok"; auth._fetch_identity = lambda p, t: ident
        try:
            return auth.oauth_complete(state, "code"), state
        finally:
            auth._exchange_code, auth._fetch_identity = orig

    def test_new_user_then_returning_and_state_single_use(self):
        ident = {"id": "g-1", "email": "oauth.new@example.com", "name": "Oauth New"}
        user, state = self._login("google", ident)
        self.assertEqual(user["email"], "oauth.new@example.com"); self.assertEqual(user["role"], "student")
        again, _ = self._login("google", ident)
        self.assertEqual(again["id"], user["id"])
        with self.assertRaises(AuthError): auth.oauth_complete(state, "code")  # state already consumed

    def test_links_to_existing_email_account(self):
        existing = mk()
        user, _ = self._login("github", {"id": "gh-9", "email": existing["email"], "name": "x"})
        self.assertEqual(user["id"], existing["id"])
        self.assertEqual(db.query_one("SELECT COUNT(*) AS c FROM auth_identities WHERE user_id=?", (existing["id"],))["c"], 1)

    def test_expired_state_rejected(self):
        os.environ["GOOGLE_CLIENT_ID"] = "id"; os.environ["GOOGLE_CLIENT_SECRET"] = "s"
        state = auth.oauth_authorize_url("google").split("state=")[1].split("&")[0]
        db.execute("UPDATE oauth_states SET expires_at='2000-01-01T00:00:00'")
        with self.assertRaises(AuthError): auth.oauth_complete(state, "c")

    def test_oauth_only_account_cannot_password_login(self):
        user, _ = self._login("google", {"id": "g-77", "email": "only.oauth@example.com", "name": "O"})
        with self.assertRaises(AuthError): auth.authenticate("only.oauth@example.com", "anything1")


class MarketTests(unittest.TestCase):
    def setUp(self):
        self.s, self.t, self.other = mk(), mk("tutor", "Tina Tutor"), mk()
        svc.update_tutor_profile(self.t["id"], "Python mentor", "Teaches Python and data science", "Python, Maths",
                                 "pandas", 5, "BSc CS", "Weekends", "Hyderabad", True)

    def test_publish_validation_and_search(self):
        t2 = mk("tutor")
        with self.assertRaises(ServiceError): svc.update_tutor_profile(t2["id"], "", "", "", "", 1, "", "", "", True)
        self.assertIn(self.t["id"], [x["id"] for x in svc.search_tutors(self.s["id"], "python")])
        self.assertIn(self.t["id"], [x["id"] for x in svc.search_tutors(self.s["id"], "", "Maths")])
        self.assertEqual(svc.search_tutors(self.s["id"], "zzz"), [])
        self.assertIn("Python", svc.list_subjects())

    def test_connection_lifecycle_and_messaging(self):
        svc.request_connection(self.s["id"], self.t["id"], "Hi!")
        with self.assertRaises(ServiceError): svc.request_connection(self.s["id"], self.t["id"], "again")
        self.assertEqual(svc.unread_count(self.t["id"]), 1)
        conn = svc.list_connections(self.t["id"], "tutor", ["pending"])[0]
        self.assertIsNone(conn["other_email"])  # hidden until accepted
        with self.assertRaises(ServiceError): svc.send_message(self.s["id"], conn["id"], "too early")
        with self.assertRaises(ServiceError): svc.respond_connection(self.other["id"], conn["id"], True)  # not the tutor
        svc.respond_connection(self.t["id"], conn["id"], True)
        self.assertEqual(svc.list_connections(self.s["id"], "student", ["accepted"])[0]["other_email"], self.t["email"])
        svc.send_message(self.s["id"], conn["id"], "Hello tutor")
        svc.send_message(self.t["id"], conn["id"], "Hello student")
        msgs = svc.get_messages(self.t["id"], conn["id"])
        self.assertEqual([m["body"] for m in msgs], ["Hello tutor", "Hello student"])
        with self.assertRaises(ServiceError): svc.get_messages(self.other["id"], conn["id"])  # outsider blocked
        with self.assertRaises(ServiceError): svc.send_message(self.other["id"], conn["id"], "intruder")
        svc.end_connection(self.s["id"], conn["id"])
        with self.assertRaises(ServiceError): svc.send_message(self.s["id"], conn["id"], "after end")
        svc.request_connection(self.s["id"], self.t["id"], "back again")  # re-request allowed after ending

    def test_reject_then_rerequest(self):
        svc.request_connection(self.s["id"], self.t["id"])
        c = svc.list_connections(self.t["id"], "tutor")[0]
        svc.respond_connection(self.t["id"], c["id"], False)
        with self.assertRaises(ServiceError): svc.respond_connection(self.t["id"], c["id"], True)
        svc.request_connection(self.s["id"], self.t["id"])

    def test_tutor_cannot_request(self):
        with self.assertRaises(ServiceError): svc.request_connection(self.t["id"], self.t["id"])

    def test_unpublished_tutor_hidden(self):
        t3 = mk("tutor")
        with self.assertRaises(ServiceError): svc.request_connection(self.s["id"], t3["id"])

    def test_avatar_validation(self):
        with self.assertRaises(ServiceError): svc.set_avatar(self.s["id"], b"notanimage", "image/png")
        png = b"\x89PNG\r\n\x1a\n" + b"0" * 20
        svc.set_avatar(self.s["id"], png, "image/png")
        self.assertEqual(svc.get_avatar(self.s["id"]), png)


class SkillExchangeTests(unittest.TestCase):
    def setUp(self):
        self.a, self.b, self.c = mk(), mk(), mk()
        for u, teach, learn in [(self.a, "Graphic Design", "Python"), (self.b, "Video Editing", "graphic design"),
                                (self.c, "python", "video  editing")]:
            svc.add_skill(u["id"], teach, "teach"); svc.add_skill(u["id"], learn, "learn")

    def test_skill_rules(self):
        with self.assertRaises(ServiceError): svc.add_skill(self.a["id"], "graphic design", "teach")  # duplicate
        with self.assertRaises(ServiceError): svc.add_skill(self.a["id"], "Python", "teach")  # on learn list
        with self.assertRaises(ServiceError): svc.add_skill(self.a["id"], "x", "teach")

    def test_three_person_cycle_found(self):
        m = svc.get_matches(self.a["id"])
        tri = [x for x in m["triangles"] if set(x["members"]) == {self.a["id"], self.b["id"], self.c["id"]}]
        self.assertEqual(len(tri), 1)

    def test_pair_match(self):
        d = mk(); svc.add_skill(d["id"], "python", "teach"); svc.add_skill(d["id"], "graphic design", "learn")
        m = svc.get_matches(self.a["id"])
        self.assertTrue(any(set(p["members"]) == {self.a["id"], d["id"]} for p in m["pairs"]))

    def test_no_match_without_reciprocity(self):
        e = mk(); svc.add_skill(e["id"], "python", "teach"); svc.add_skill(e["id"], "cooking", "learn")
        m = svc.get_matches(self.a["id"])
        self.assertFalse(any(e["id"] in p["members"] for p in m["pairs"]))

    def test_three_person_group_flow(self):
        gid = svc.create_group(self.a["id"], "Triad", [self.b["id"], self.c["id"]])
        self.assertEqual(svc.get_group(self.a["id"], gid)["status"], "forming")
        self.assertEqual(svc.pending_group_invites(self.b["id"]), 1)
        svc.respond_invite(self.b["id"], gid, True)
        self.assertEqual(svc.get_group(self.a["id"], gid)["status"], "active")
        svc.respond_invite(self.c["id"], gid, True)
        outsider = mk()
        with self.assertRaises(ServiceError): svc.get_group(outsider["id"], gid)
        with self.assertRaises(ServiceError): svc.send_group_message(outsider["id"], gid, "hi")
        with self.assertRaises(ServiceError): svc.invite_to_group(self.a["id"], gid, outsider["id"])  # full (3)
        svc.send_group_message(self.a["id"], gid, "Welcome!")
        self.assertEqual(svc.get_group_messages(self.c["id"], gid)[0]["body"], "Welcome!")
        when = datetime.now() + timedelta(days=1)
        svc.schedule_session(self.a["id"], gid, "Python basics", when, 60, self.c["id"], "https://meet.example", "")
        s = svc.list_sessions(self.b["id"], gid)[0]
        self.assertEqual(s["teacher_name"], self.c["full_name"])
        svc.update_session_status(self.b["id"], s["id"], "completed")
        with self.assertRaises(ServiceError): svc.submit_feedback(self.a["id"], gid, self.b["id"], 5)  # not completed yet
        svc.complete_group(self.a["id"], gid)
        svc.submit_feedback(self.a["id"], gid, self.b["id"], 5, "great")
        with self.assertRaises(ServiceError): svc.submit_feedback(self.a["id"], gid, self.b["id"], 4)  # duplicate
        with self.assertRaises(ServiceError): svc.submit_feedback(self.a["id"], gid, self.a["id"], 4)
        self.assertEqual(svc.feedback_received(self.b["id"]), {"avg": 5.0, "count": 1})

    def test_two_person_group_decline_and_leave(self):
        gid = svc.create_group(self.a["id"], "Duo", [self.b["id"]])
        svc.respond_invite(self.b["id"], gid, False)
        self.assertEqual(svc.get_group(self.a["id"], gid)["status"], "cancelled")
        gid2 = svc.create_group(self.a["id"], "Duo2", [self.b["id"]])
        svc.respond_invite(self.b["id"], gid2, True)
        svc.leave_group(self.b["id"], gid2)
        self.assertEqual(svc.get_group(self.a["id"], gid2)["status"], "cancelled")
        with self.assertRaises(ServiceError): svc.get_group(self.b["id"], gid2)

    def test_group_validation(self):
        t = mk("tutor")
        with self.assertRaises(ServiceError): svc.create_group(self.a["id"], "Bad", [t["id"]])
        with self.assertRaises(ServiceError): svc.create_group(self.a["id"], "Bad", [self.a["id"]])
        with self.assertRaises(ServiceError): svc.create_group(self.a["id"], "Bad", [])
        with self.assertRaises(ServiceError): svc.create_group(self.a["id"], "Bad", [mk()["id"], mk()["id"], mk()["id"]])


class NotificationAndAITests(unittest.TestCase):
    def test_notifications(self):
        u = mk(); svc.notify(u["id"], "x", "Hello"); svc.notify(u["id"], "x", "Again")
        self.assertEqual(svc.unread_count(u["id"]), 2)
        svc.mark_notification_read(u["id"], svc.list_notifications(u["id"])[0]["id"])
        self.assertEqual(svc.unread_count(u["id"]), 1)
        svc.mark_all_read(u["id"]); self.assertEqual(svc.unread_count(u["id"]), 0)

    def test_ai_history_isolated(self):
        u, v = mk(), mk()
        cid = svc.create_conversation(u["id"])
        svc.add_ai_message(u["id"], cid, "user", "What is recursion?")
        svc.add_ai_message(u["id"], cid, "assistant", "A function calling itself.")
        self.assertEqual(len(svc.get_ai_messages(u["id"], cid)), 2)
        self.assertEqual(svc.list_conversations(u["id"])[0]["title"], "What is recursion?")
        with self.assertRaises(ServiceError): svc.get_ai_messages(v["id"], cid)
        with self.assertRaises(ServiceError): svc.delete_conversation(v["id"], cid)
        svc.delete_conversation(u["id"], cid); self.assertEqual(svc.list_conversations(u["id"]), [])

    def test_ai_missing_key(self):
        import ai_service
        os.environ.pop("ANTHROPIC_API_KEY", None)
        with self.assertRaises(ai_service.AIError): ai_service.ask([{"role": "user", "content": "hi"}])

    def test_role_change_blocked_with_connections(self):
        s, t = mk(), mk("tutor")
        svc.update_tutor_profile(t["id"], "h", "d", "Maths", "", 1, "", "", "", True)
        svc.change_role(mk()["id"], "tutor")
        svc.request_connection(s["id"], t["id"])
        with self.assertRaises(ServiceError): svc.change_role(s["id"], "tutor")


if __name__ == "__main__":
    unittest.main(verbosity=1)
