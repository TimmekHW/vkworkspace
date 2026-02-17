"""Live API test — runs real requests against a VK Teams instance.

Usage::

    python tests/test_bot_live.py --token BOT_TOKEN \\
        --api-url https://myteam.mail.ru/bot/v1 --chat CHAT_ID

All arguments can also be set via environment variables:

    VKWS_TOKEN      — bot token (required)
    VKWS_API_URL    — API base URL (required)
    VKWS_CHAT_ID    — group chat id for testing (required)

The script sends real messages to *CHAT_ID*, then cleans them up.
"""
from __future__ import annotations

import argparse
import asyncio
import io
import os
import sys
import time

# make sure we import the local package, not an installed one
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from vkworkspace.client.bot import Bot
from vkworkspace.enums import ChatAction, ParseMode
from vkworkspace.exceptions import VKTeamsAPIError
from vkworkspace.types.input_file import InputFile

# ── colours ────────────────────────────────────────────────────────────

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"


def ok(name: str, detail: str = "") -> None:
    d = f"  ({detail})" if detail else ""
    print(f"  {GREEN}OK{RESET}  {name}{d}")


def fail(name: str, err: Exception) -> None:
    print(f"  {RED}FAIL{RESET}  {name}  — {err}")


def skip(name: str, reason: str) -> None:
    print(f"  {YELLOW}SKIP{RESET}  {name}  — {reason}")


def section(title: str) -> None:
    print(f"\n{BOLD}{CYAN}── {title} ──{RESET}")


def _is_unknown_method(e: Exception) -> bool:
    """Check if the error is 'Unknown method' — installation doesn't support it."""
    return isinstance(e, VKTeamsAPIError) and "unknown method" in e.message.lower()


# ── test runner ────────────────────────────────────────────────────────

async def run_tests(token: str, api_url: str, chat_id: str) -> tuple[int, int, int]:
    bot = Bot(token=token, api_url=api_url)
    passed = 0
    failed = 0
    skipped = 0
    cleanup_msgs: list[str] = []  # msg_ids to delete at the end

    # ── self/get ───────────────────────────────────────────────────
    section("self/get")
    try:
        me = await bot.get_me()
        ok("get_me", f"userId={me.user_id}, nick={me.nick}")
        passed += 1
    except Exception as e:
        fail("get_me", e)
        failed += 1

    # ── events/get ─────────────────────────────────────────────────
    section("events/get")
    try:
        events = await bot.get_events(poll_time=1)
        ok("get_events", f"got {len(events)} event(s), last_id={bot._last_event_id}")
        passed += 1
    except Exception as e:
        fail("get_events", e)
        failed += 1

    # ── messages/sendText ──────────────────────────────────────────
    section("messages/sendText")

    # basic
    try:
        r = await bot.send_text(chat_id, "vkworkspace live test: basic text")
        assert r.ok and r.msg_id
        cleanup_msgs.append(r.msg_id)
        ok("send_text (basic)", f"msgId={r.msg_id}")
        basic_msg_id = r.msg_id
        passed += 1
    except Exception as e:
        fail("send_text (basic)", e)
        failed += 1
        basic_msg_id = None

    # with parse_mode HTML
    try:
        r = await bot.send_text(
            chat_id,
            "<b>bold</b> <i>italic</i> <u>underline</u>",
            parse_mode=ParseMode.HTML,
        )
        assert r.ok
        if r.msg_id:
            cleanup_msgs.append(r.msg_id)
        ok("send_text (HTML)")
        passed += 1
    except Exception as e:
        fail("send_text (HTML)", e)
        failed += 1

    # with parse_mode MarkdownV2
    try:
        r = await bot.send_text(
            chat_id,
            "*bold* _italic_ ~strikethrough~",
            parse_mode=ParseMode.MARKDOWNV2,
        )
        assert r.ok
        if r.msg_id:
            cleanup_msgs.append(r.msg_id)
        ok("send_text (MarkdownV2)")
        passed += 1
    except Exception as e:
        fail("send_text (MarkdownV2)", e)
        failed += 1

    # with reply_msg_id (single string)
    if basic_msg_id:
        try:
            r = await bot.send_text(chat_id, "reply test", reply_msg_id=basic_msg_id)
            assert r.ok
            if r.msg_id:
                cleanup_msgs.append(r.msg_id)
            ok("send_text (reply)")
            passed += 1
        except Exception as e:
            fail("send_text (reply)", e)
            failed += 1

    # with reply_msg_id as list (comma-separated)
    if basic_msg_id:
        try:
            r = await bot.send_text(chat_id, "multi-reply test", reply_msg_id=[basic_msg_id])
            assert r.ok
            if r.msg_id:
                cleanup_msgs.append(r.msg_id)
            ok("send_text (reply list)")
            passed += 1
        except Exception as e:
            fail("send_text (reply list)", e)
            failed += 1

    # with forward
    if basic_msg_id:
        try:
            r = await bot.send_text(
                chat_id, "forward test",
                forward_chat_id=chat_id,
                forward_msg_id=basic_msg_id,
            )
            assert r.ok
            if r.msg_id:
                cleanup_msgs.append(r.msg_id)
            ok("send_text (forward)")
            passed += 1
        except Exception as e:
            fail("send_text (forward)", e)
            failed += 1

    # with inline keyboard
    try:
        kb = [[{"text": "Button 1", "callbackData": "btn1"}, {"text": "Button 2", "url": "https://example.com"}]]
        r = await bot.send_text(chat_id, "keyboard test", inline_keyboard_markup=kb)
        assert r.ok
        if r.msg_id:
            cleanup_msgs.append(r.msg_id)
        ok("send_text (keyboard)")
        passed += 1
    except Exception as e:
        fail("send_text (keyboard)", e)
        failed += 1

    # with format_ (rich formatting)
    try:
        r = await bot.send_text(
            chat_id, "format test bold",
            format_={"bold": [{"offset": 12, "length": 4}]},
        )
        assert r.ok
        if r.msg_id:
            cleanup_msgs.append(r.msg_id)
        ok("send_text (format_)")
        passed += 1
    except Exception as e:
        fail("send_text (format_)", e)
        failed += 1

    # with request_id (idempotency)
    try:
        rid = f"test-{int(time.time())}"
        r1 = await bot.send_text(chat_id, "idempotent msg", request_id=rid)
        assert r1.ok
        if r1.msg_id:
            cleanup_msgs.append(r1.msg_id)
        ok("send_text (request_id)", f"requestId={rid}")
        passed += 1
    except Exception as e:
        fail("send_text (request_id)", e)
        failed += 1

    # ── messages/sendTextWithDeeplink ──────────────────────────────
    section("messages/sendTextWithDeeplink")
    try:
        r = await bot.send_text_with_deeplink(chat_id, "deeplink test", deeplink="start_payload")
        assert r.ok
        if r.msg_id:
            cleanup_msgs.append(r.msg_id)
        ok("send_text_with_deeplink", f"msgId={r.msg_id}")
        passed += 1
    except Exception as e:
        if _is_unknown_method(e):
            skip("send_text_with_deeplink", "not supported on this installation")
            skipped += 1
        else:
            fail("send_text_with_deeplink", e)
            failed += 1

    # ── messages/editText ──────────────────────────────────────────
    section("messages/editText")
    if basic_msg_id:
        try:
            r = await bot.edit_text(chat_id, basic_msg_id, "EDITED: live test text")
            assert r.ok
            ok("edit_text")
            passed += 1
        except Exception as e:
            fail("edit_text", e)
            failed += 1
    else:
        skip("edit_text", "no basic_msg_id")
        skipped += 1

    # ── messages/sendFile ──────────────────────────────────────────
    section("messages/sendFile")
    try:
        buf = io.BytesIO(b"Hello from vkworkspace live test!\n")
        inp = InputFile(buf, filename="test.txt")
        r = await bot.send_file(chat_id, file=inp, caption="test file upload")
        assert r.ok
        if r.msg_id:
            cleanup_msgs.append(r.msg_id)
        ok("send_file (upload)", f"msgId={r.msg_id}")
        passed += 1
    except Exception as e:
        fail("send_file (upload)", e)
        failed += 1

    # send_file with request_id
    try:
        buf2 = io.BytesIO(b"idempotent file")
        inp2 = InputFile(buf2, filename="idem.txt")
        r = await bot.send_file(chat_id, file=inp2, request_id=f"file-{int(time.time())}")
        assert r.ok
        if r.msg_id:
            cleanup_msgs.append(r.msg_id)
        ok("send_file (request_id)")
        passed += 1
    except Exception as e:
        fail("send_file (request_id)", e)
        failed += 1

    # ── messages/sendVoice ─────────────────────────────────────────
    section("messages/sendVoice")
    try:
        # Minimal OGG header (won't actually play, but tests the endpoint)
        ogg_header = (
            b"OggS\x00\x02\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x01\x1e\x01vorbis"
        )
        buf = io.BytesIO(ogg_header)
        inp = InputFile(buf, filename="voice.ogg")
        r = await bot.send_voice(chat_id, file=inp)
        assert r.ok
        if r.msg_id:
            cleanup_msgs.append(r.msg_id)
        ok("send_voice (upload)", f"msgId={r.msg_id}")
        passed += 1
    except Exception as e:
        fail("send_voice (upload)", e)
        failed += 1

    # ── messages/answerCallbackQuery ───────────────────────────────
    section("messages/answerCallbackQuery")
    skip("answer_callback_query", "requires a real callback from user click")
    skipped += 1

    # ── chats/getInfo ──────────────────────────────────────────────
    section("chats/getInfo")
    info = None
    try:
        info = await bot.get_chat_info(chat_id)
        assert info.type in ("group", "channel", "private")
        ok("get_chat_info", f"type={info.type}, title={info.title}")
        passed += 1
    except Exception as e:
        fail("get_chat_info", e)
        failed += 1

    # ── chats/getAdmins ────────────────────────────────────────────
    section("chats/getAdmins")
    try:
        admins = await bot.get_chat_admins(chat_id)
        ok("get_chat_admins", f"{len(admins)} admin(s)")
        passed += 1
    except Exception as e:
        fail("get_chat_admins", e)
        failed += 1

    # ── chats/getMembers ───────────────────────────────────────────
    section("chats/getMembers")
    try:
        members_data = await bot.get_chat_members(chat_id)
        member_count = len(members_data.get("members", []))
        ok("get_chat_members", f"{member_count} member(s)")
        passed += 1
    except Exception as e:
        fail("get_chat_members", e)
        failed += 1

    # ── chats/getBlockedUsers ──────────────────────────────────────
    section("chats/getBlockedUsers")
    try:
        blocked = await bot.get_blocked_users(chat_id)
        ok("get_blocked_users", f"{len(blocked)} blocked")
        passed += 1
    except Exception as e:
        fail("get_blocked_users", e)
        failed += 1

    # ── chats/getPendingUsers ──────────────────────────────────────
    section("chats/getPendingUsers")
    try:
        pending = await bot.get_pending_users(chat_id)
        ok("get_pending_users", f"{len(pending)} pending")
        passed += 1
    except Exception as e:
        fail("get_pending_users", e)
        failed += 1

    # ── chats/sendActions ──────────────────────────────────────────
    section("chats/sendActions")
    try:
        r = await bot.send_actions(chat_id, ChatAction.TYPING)
        assert r.ok
        ok("send_actions (typing)")
        passed += 1
    except Exception as e:
        fail("send_actions (typing)", e)
        failed += 1

    try:
        r = await bot.send_actions(chat_id, ChatAction.LOOKING)
        assert r.ok
        ok("send_actions (looking)")
        passed += 1
    except Exception as e:
        fail("send_actions (looking)", e)
        failed += 1

    # ── chats/pinMessage / unpinMessage ────────────────────────────
    section("chats/pinMessage + unpinMessage")
    if basic_msg_id:
        try:
            r = await bot.pin_message(chat_id, basic_msg_id)
            assert r.ok
            ok("pin_message")
            passed += 1
        except Exception as e:
            fail("pin_message", e)
            failed += 1

        # give the server time to process the pin
        await asyncio.sleep(1)

        try:
            r = await bot.unpin_message(chat_id, basic_msg_id)
            assert r.ok
            ok("unpin_message")
            passed += 1
        except Exception as e:
            fail("unpin_message", e)
            failed += 1
    else:
        skip("pin_message", "no basic_msg_id")
        skip("unpin_message", "no basic_msg_id")
        skipped += 2

    # ── chats/setTitle ─────────────────────────────────────────────
    section("chats/setTitle + setAbout + setRules")
    original_title = info.title if info else None
    try:
        r = await bot.set_chat_title(chat_id, "vkworkspace test title")
        assert r.ok
        ok("set_chat_title")
        passed += 1
        # restore
        if original_title:
            await bot.set_chat_title(chat_id, original_title)
    except Exception as e:
        fail("set_chat_title", e)
        failed += 1

    try:
        r = await bot.set_chat_about(chat_id, "vkworkspace live test description")
        assert r.ok
        ok("set_chat_about")
        passed += 1
    except Exception as e:
        fail("set_chat_about", e)
        failed += 1

    try:
        r = await bot.set_chat_rules(chat_id, "vkworkspace live test rules")
        assert r.ok
        ok("set_chat_rules")
        passed += 1
    except Exception as e:
        fail("set_chat_rules", e)
        failed += 1

    # ── chats/avatar/set ───────────────────────────────────────────
    section("chats/avatar/set")
    try:
        # 800x800 valid PNG (red square)
        # Generated minimal valid PNG with IDAT
        import struct
        import zlib
        width, height = 800, 800
        # raw image data: filter byte 0 + 3 bytes RGB per pixel, per row
        raw_data = b""
        for _ in range(height):
            raw_data += b"\x00" + b"\xff\x00\x00" * width  # filter=0, red pixels
        compressed = zlib.compress(raw_data)

        def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
            c = chunk_type + data
            return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

        png = b"\x89PNG\r\n\x1a\n"
        png += _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        png += _png_chunk(b"IDAT", compressed)
        png += _png_chunk(b"IEND", b"")

        inp = InputFile(io.BytesIO(png), filename="avatar.png")
        r = await bot.set_chat_avatar(chat_id, inp)
        assert r.ok
        ok("set_chat_avatar")
        passed += 1
    except Exception as e:
        fail("set_chat_avatar", e)
        failed += 1

    # ── chats/members/add + delete ─────────────────────────────────
    section("chats/members/add + members/delete")
    skip("add_chat_members", "requires a real user_id — skipping to avoid side effects")
    skip("delete_chat_members", "requires a real user_id — skipping to avoid side effects")
    skipped += 2

    # ── chats/blockUser + unblockUser ──────────────────────────────
    section("chats/blockUser + unblockUser")
    skip("block_user", "requires a real user_id — skipping to avoid side effects")
    skip("unblock_user", "requires a real user_id — skipping to avoid side effects")
    skipped += 2

    # ── chats/resolvePending ───────────────────────────────────────
    section("chats/resolvePending")
    skip("resolve_pending", "requires pending join requests — skipping")
    skipped += 1

    # ── files/getInfo ──────────────────────────────────────────────
    section("files/getInfo")
    skip("get_file_info", "requires a valid fileId — tested indirectly via send_file")
    skipped += 1

    # ── threads ────────────────────────────────────────────────────
    section("threads/add + autosubscribe + subscribers/get")
    thread_id = None
    if basic_msg_id:
        try:
            thread = await bot.threads_add(chat_id, basic_msg_id)
            thread_id = thread.thread_id
            ok("threads_add", f"threadId={thread_id}")
            passed += 1
        except Exception as e:
            if _is_unknown_method(e):
                skip("threads_add", "not supported on this installation")
                skipped += 1
            else:
                fail("threads_add", e)
                failed += 1
    else:
        skip("threads_add", "no basic_msg_id")
        skipped += 1

    try:
        r = await bot.threads_autosubscribe(chat_id, enable=True)
        assert r.ok
        ok("threads_autosubscribe (enable)")
        passed += 1
    except Exception as e:
        if _is_unknown_method(e):
            skip("threads_autosubscribe", "not supported on this installation")
            skipped += 1
        else:
            fail("threads_autosubscribe", e)
            failed += 1

    if thread_id:
        try:
            subs = await bot.threads_get_subscribers(thread_id)
            ok("threads_get_subscribers", f"{len(subs.subscribers)} subscriber(s)")
            passed += 1
        except Exception as e:
            if _is_unknown_method(e):
                skip("threads_get_subscribers", "not supported on this installation")
                skipped += 1
            else:
                fail("threads_get_subscribers", e)
                failed += 1
    else:
        skip("threads_get_subscribers", "no thread_id")
        skipped += 1

    # ── messages/deleteMessages (cleanup) ──────────────────────────
    section("messages/deleteMessages (cleanup)")
    valid_msgs = [m for m in cleanup_msgs if m]
    if valid_msgs:
        deleted = 0
        delete_errors: list[str] = []
        for msg_id in valid_msgs:
            try:
                r = await bot.delete_messages(chat_id, msg_id)
                if r.ok:
                    deleted += 1
            except Exception as e:
                delete_errors.append(str(e))

        if deleted == len(valid_msgs):
            ok("delete_messages", f"deleted {deleted}/{len(valid_msgs)} test messages")
            passed += 1
        elif deleted > 0:
            ok("delete_messages", f"deleted {deleted}/{len(valid_msgs)} (some failed)")
            passed += 1
        else:
            first_err = delete_errors[0] if delete_errors else "?"
            fail("delete_messages", Exception(f"0/{len(valid_msgs)} deleted: {first_err}"))
            failed += 1
    else:
        skip("delete_messages", "no messages to clean up")
        skipped += 1

    await bot.close()
    return passed, failed, skipped


# ── main ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="vkworkspace live API test")
    parser.add_argument("--token", default=os.getenv("VKWS_TOKEN"), help="Bot token")
    parser.add_argument("--api-url", default=os.getenv("VKWS_API_URL"), help="API base URL")
    parser.add_argument("--chat", default=os.getenv("VKWS_CHAT_ID"), help="Test group chat ID")
    args = parser.parse_args()

    if not args.token:
        print(f"{RED}ERROR:{RESET} --token or VKWS_TOKEN is required")
        sys.exit(1)
    if not args.api_url:
        print(f"{RED}ERROR:{RESET} --api-url or VKWS_API_URL is required")
        sys.exit(1)
    if not args.chat:
        print(f"{RED}ERROR:{RESET} --chat or VKWS_CHAT_ID is required")
        sys.exit(1)

    print(f"\n{BOLD}vkworkspace live API test{RESET}")
    print(f"  API:   {args.api_url}")
    print(f"  Chat:  {args.chat}")
    print(f"  Token: {args.token[:8]}...{args.token[-4:]}")

    passed, failed, skipped = asyncio.run(run_tests(args.token, args.api_url, args.chat))

    total = passed + failed + skipped
    print(f"\n{BOLD}{'═' * 50}{RESET}")
    print(
        f"  {GREEN}{passed} passed{RESET}  /  {RED}{failed} failed{RESET}"
        f"  /  {YELLOW}{skipped} skipped{RESET}  /  {total} total"
    )

    if failed == 0:
        print(f"\n  {GREEN}{BOLD}ALL TESTS PASSED{RESET}\n")
    else:
        print(f"\n  {RED}{BOLD}{failed} TEST(S) FAILED{RESET}\n")

    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
