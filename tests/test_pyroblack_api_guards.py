#!/usr/bin/env python3
"""
Test: pyroblack deprecated kwarg families never appear in app code

The project currently does NOT call these APIs at all (the earlier sweep
found zero usages), so there is nothing to spy on behaviorally - the pin is
source-level: the deprecated kwarg spellings must never be introduced.

Guarded families (all replaced in pyroblack 3.0.3, see the deprecation
sweep in the git history):

- Reply targeting:  reply_to_message_id / reply_to_chat_id / reply_to_sender_id
                    / reply_to_story_id  ->  reply_parameters=
- Inline thumbnails: thumb_url / thumb_width / thumb_height / thumb_mime_type
                    ->  thumbnail_url / thumbnail_width / thumbnail_height /
                        thumbnail_mime_type
- Documents:        force_document  ->  disable_content_type_detection
- Chat history:     offset_id (get_chat_history)  ->  min_id / max_id
- Keyboards:        placeholder (ReplyKeyboardMarkup/ForceReply)
                    ->  input_field_placeholder

Only the app modules (features/, main.py, scripts/) are scanned - test files
are excluded because the guard's own data table legitimately contains these
strings. This mirrors the filterwarnings module scope in pyproject.toml.

"#" line comments are stripped before scanning, so developers can document
the deprecated spellings (e.g. "use reply_parameters= instead of
reply_to_message_id=") without tripping the guard - the pin targets actual
code, not prose. Docstrings are still scanned; keep prose out of them.

Note: "placeholder=" is the broadest token (any future kwarg named
placeholder would match) - acceptable for this codebase, where placeholder
only ever refers to the keyboard APIs.
"""

import sys
import os
import glob

# Ensure project root on path so `features` is importable
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

APP_FILES = [os.path.join(ROOT_DIR, "main.py")] + \
    sorted(p for p in glob.glob(os.path.join(ROOT_DIR, "features", "**", "*.py"),
                                recursive=True)
           if "__pycache__" not in p) + \
    sorted(p for p in glob.glob(os.path.join(ROOT_DIR, "scripts", "**", "*.py"),
                                recursive=True)
           if "__pycache__" not in p)

# Deprecated kwarg spelling -> modern replacement (shown in failure messages)
DEPRECATED_KWARGS = {
    "reply_to_message_id=": "reply_parameters=",
    "reply_to_chat_id=": "reply_parameters=",
    "reply_to_sender_id=": "reply_parameters=",
    "reply_to_story_id=": "reply_parameters=",
    "thumb_url=": "thumbnail_url=",
    "thumb_width=": "thumbnail_width=",
    "thumb_height=": "thumbnail_height=",
    "thumb_mime_type=": "thumbnail_mime_type=",
    "force_document=": "disable_content_type_detection=",
    "offset_id=": "min_id= / max_id=",
    "placeholder=": "input_field_placeholder=",
}


def _scan(tokens):
    """Return [file:line: source] for every code hit of any token in app
    modules. "#" line comments are stripped so prose never trips the guard."""
    hits = []
    for path in APP_FILES:
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                code = line.split("#", 1)[0]
                for token in tokens:
                    if token in code:
                        rel = os.path.relpath(path, ROOT_DIR)
                        hits.append(f"{rel}:{lineno}: {line.strip()[:80]}")
    return hits


def _assert_no_deprecated(tokens, replacement_note):
    hits = _scan(tokens)
    assert not hits, (
        f"deprecated pyroblack kwarg(s) used - replace with {replacement_note}:\n"
        + "\n".join(hits)
    )


def test_deprecated_reply_kwargs_never_used():
    """Reply targeting must use reply_parameters, never reply_to_* kwargs."""
    _assert_no_deprecated(
        ["reply_to_message_id=", "reply_to_chat_id=",
         "reply_to_sender_id=", "reply_to_story_id="],
        "reply_parameters=",
    )


def test_deprecated_thumbnail_kwargs_never_used():
    """Inline results must use the thumbnail_* family, never thumb_* kwargs."""
    _assert_no_deprecated(
        ["thumb_url=", "thumb_width=", "thumb_height=", "thumb_mime_type="],
        "thumbnail_*",
    )


def test_other_deprecated_kwargs_never_used():
    """force_document / offset_id / placeholder must use their replacements."""
    _assert_no_deprecated(
        ["force_document=", "offset_id=", "placeholder="],
        "disable_content_type_detection= / min_id= / max_id= / input_field_placeholder=",
    )


def test_all_deprecated_kwargs_never_used():
    """The full table at once - a single gate covering every family."""
    _assert_no_deprecated(list(DEPRECATED_KWARGS), "the modern replacements")


def main():
    test_deprecated_reply_kwargs_never_used()
    test_deprecated_thumbnail_kwargs_never_used()
    test_other_deprecated_kwargs_never_used()
    test_all_deprecated_kwargs_never_used()
    print("✅ pyroblack deprecated-kwarg guards passed")
    print("   - reply_to_*  -> reply_parameters")
    print("   - thumb_*     -> thumbnail_*")
    print("   - force_document / offset_id / placeholder -> modern replacements")


if __name__ == "__main__":
    main()
