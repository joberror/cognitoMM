"""
Tests for the interactive /help menu (features/commands.py) and the Telegraph
publisher's content builder (scripts/publish_telegraph.py).

Pins:
- The home page renders category buttons and a Full Guide button only when
  HELP_GUIDE_URL is configured.
- The Admin section is gated: non-admins are bounced to home, admins get it.
- render_help_page sends on first call and edits on callback navigation.
- The Telegraph content is valid Node JSON, stays under the 64 KB limit, and
  the serializer rejects oversized content.
"""

import importlib.util
import json
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from pyrogram.enums import ParseMode  # noqa: E402

from features import commands as commands_mod  # noqa: E402


def _load_publish_module():
    """Load scripts/publish_telegraph.py as a module (not a package)."""
    path = os.path.join(ROOT_DIR, "scripts", "publish_telegraph.py")
    spec = importlib.util.spec_from_file_location("publish_telegraph", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


publish = _load_publish_module()


class _FakeMessage:
    """Records reply_text / edit_text calls instead of hitting Telegram."""

    def __init__(self):
        self.replies = []
        self.edits = []

    async def reply_text(self, text, **kwargs):
        self.replies.append((text, kwargs))

    async def edit_text(self, text, **kwargs):
        self.edits.append((text, kwargs))


def _button_labels(markup):
    return [btn.text for row in markup.inline_keyboard for btn in row]


def _button_urls(markup):
    return {btn.text: btn.url for row in markup.inline_keyboard for btn in row
            if getattr(btn, "url", None)}


def _flatten_text(*nodes):
    out = []
    for node in nodes:
        if isinstance(node, str):
            out.append(node)
        elif isinstance(node, dict):
            out.append(_flatten_text(*node.get("children", [])))
    return " ".join(out)


# ------------------------------------------------------------------ #
#  Help menu rendering                                               #
# ------------------------------------------------------------------ #


def test_home_shows_categories(monkeypatch):
    monkeypatch.setattr(commands_mod, "HELP_GUIDE_URL", "")
    monkeypatch.setattr(commands_mod, "ADMIN_GUIDE_URL", "")

    async def always_admin(uid):
        return False

    monkeypatch.setattr(commands_mod, "is_admin", always_admin)

    import asyncio
    text, keyboard = asyncio.run(commands_mod.build_help_page(1, "home"))
    labels = _button_labels(keyboard)

    assert "🔎 Search" in labels
    assert "📌 Discover" in labels
    assert "👤 Me" in labels
    assert "⭐ Premium" in labels
    # Non-admin: no admin button, no guide buttons (URLs unset).
    assert "👑 Admin" not in labels
    assert "📖 Full Guide" not in labels
    assert "/f" in text


def test_user_guide_button_on_every_page(monkeypatch):
    monkeypatch.setattr(commands_mod, "HELP_GUIDE_URL",
                        "https://telegra.ph/MovieBot--Help-Guide-10-04")
    monkeypatch.setattr(commands_mod, "ADMIN_GUIDE_URL",
                        "https://telegra.ph/MovieBot--Admin-Guide-10-04")

    async def admin(uid):
        return True

    monkeypatch.setattr(commands_mod, "is_admin", admin)

    import asyncio
    # Home: user guide only, never the admin guide.
    _, home_kb = asyncio.run(commands_mod.build_help_page(1, "home"))
    home_urls = _button_urls(home_kb)
    assert home_urls.get("📖 Full Guide") == (
        "https://telegra.ph/MovieBot--Help-Guide-10-04")
    assert "🛡️ Admin Guide" not in _button_labels(home_kb)

    # Search section: user guide still there.
    _, search_kb = asyncio.run(commands_mod.build_help_page(1, "search"))
    assert "📖 Full Guide" in _button_labels(search_kb)

    # Admin section: both guides, admin guide points at ADMIN_GUIDE_URL.
    _, admin_kb = asyncio.run(commands_mod.build_help_page(1, "admin"))
    admin_urls = _button_urls(admin_kb)
    assert admin_urls.get("🛡️ Admin Guide") == (
        "https://telegra.ph/MovieBot--Admin-Guide-10-04")


def test_admin_guide_never_shown_to_non_admin(monkeypatch):
    monkeypatch.setattr(commands_mod, "HELP_GUIDE_URL", "https://t.me/user")
    monkeypatch.setattr(commands_mod, "ADMIN_GUIDE_URL", "https://t.me/admin")

    async def not_admin(uid):
        return False

    monkeypatch.setattr(commands_mod, "is_admin", not_admin)

    import asyncio
    # Non-admin asking for the admin section is bounced to home (no admin URL).
    _, kb = asyncio.run(commands_mod.build_help_page(1, "admin"))
    assert "🛡️ Admin Guide" not in _button_labels(kb)


def test_admin_section_gated_for_non_admin(monkeypatch):
    monkeypatch.setattr(commands_mod, "HELP_GUIDE_URL", "")
    monkeypatch.setattr(commands_mod, "ADMIN_GUIDE_URL", "")

    async def not_admin(uid):
        return False

    monkeypatch.setattr(commands_mod, "is_admin", not_admin)

    import asyncio
    text, _ = asyncio.run(commands_mod.build_help_page(1, "admin"))
    # Bounced back to home.
    assert text == commands_mod.HELP_HOME


def test_admin_section_visible_for_admin(monkeypatch):
    monkeypatch.setattr(commands_mod, "HELP_GUIDE_URL", "")
    monkeypatch.setattr(commands_mod, "ADMIN_GUIDE_URL", "")

    async def admin(uid):
        return True

    monkeypatch.setattr(commands_mod, "is_admin", admin)

    import asyncio
    text, _ = asyncio.run(commands_mod.build_help_page(1, "admin"))
    assert text == commands_mod.HELP_SECTIONS["admin"]
    assert "/broadcast" in text


def test_render_sends_then_edits(monkeypatch):
    monkeypatch.setattr(commands_mod, "HELP_GUIDE_URL", "")
    monkeypatch.setattr(commands_mod, "ADMIN_GUIDE_URL", "")

    async def not_admin(uid):
        return False

    monkeypatch.setattr(commands_mod, "is_admin", not_admin)

    import asyncio
    msg = _FakeMessage()

    # /help and the Tutorial button send a fresh message.
    asyncio.run(commands_mod.render_help_page(None, msg, 1, "home"))
    assert len(msg.replies) == 1 and not msg.edits
    assert msg.replies[0][1]["parse_mode"] == ParseMode.HTML

    # Category navigation edits in place.
    asyncio.run(
        commands_mod.render_help_page(None, msg, 1, "search", edit=True))
    assert len(msg.edits) == 1
    assert "/search" in msg.edits[0][0]
    # Back button on a section page.
    assert "← Back" in _button_labels(msg.edits[0][1]["reply_markup"])


# ------------------------------------------------------------------ #
#  Telegraph content builder                                         #
# ------------------------------------------------------------------ #


def test_content_is_valid_node_json_under_limit():
    for role in ("user", "admin"):
        content = publish.build_content(role)
        body = publish._serialize(content)

        assert len(body.encode("utf-8")) <= publish.MAX_CONTENT_BYTES
        # Round-trips as JSON.
        parsed = json.loads(body)
        assert isinstance(parsed, list) and parsed
        assert all(isinstance(node, dict) and "tag" in node for node in parsed)


def test_user_guide_has_no_admin_commands():
    flat = _flatten_text(*publish.build_content("user"))

    for token in ("/search", "/watch", "/request", "/buy_premium",
                  "/genres", "/unwatch"):
        assert token in flat, f"missing {token}"
    # Admin commands must never leak into the public user guide.
    for token in ("/broadcast", "/user", "/reset", "/ban_user",
                  "/add_channel", "/manage_channel"):
        assert token not in flat, f"admin command {token} in user guide"


def test_admin_guide_documents_admin_commands():
    flat = _flatten_text(*publish.build_content("admin"))

    for token in ("/stat", "/broadcast", "/user", "/add_channel",
                  "/manage_channel", "/reset", "/ban_user", "/premium"):
        assert token in flat, f"missing {token}"


def test_serializer_rejects_oversized_content(monkeypatch):
    monkeypatch.setattr(publish, "MAX_CONTENT_BYTES", 10)
    raised = False
    try:
        publish._serialize(publish.build_content())
    except RuntimeError as exc:
        raised = True
        assert "limit" in str(exc)
    assert raised


if __name__ == "__main__":  # standalone runner: python tests/test_help_guide.py
    class _Monkeypatch:
        """Minimal pytest.monkeypatch shim for standalone runs (setattr)."""

        def __init__(self):
            self._undo = []

        def setattr(self, obj, name, value, raising=True):
            self._undo.append((obj, name, getattr(obj, name)))
            setattr(obj, name, value)

        def undo(self):
            while self._undo:
                obj, name, old = self._undo.pop()
                setattr(obj, name, old)

    failures = 0
    for name in sorted(k for k in list(globals()) if k.startswith("test_")):
        fn = globals()[name]
        mp = _Monkeypatch()
        try:
            import inspect
            if "monkeypatch" in inspect.signature(fn).parameters:
                fn(mp)
            else:
                fn()
            print(f"✅ {name}")
        except AssertionError as exc:
            failures += 1
            print(f"❌ {name}: {exc}")
        finally:
            mp.undo()
    sys.exit(1 if failures else 0)