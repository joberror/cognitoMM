"""
Premium Payments Module (Telegram Stars)

Telegram Stars (currency ``XTR``) purchases need no external payment provider:
the bot sends an invoice, Telegram collects the Stars, and the bot receives a
``successful_payment`` update to activate premium.

Flow:
    /buy_premium            -> plan buttons (``buyplan:<key>``)
    buyplan:<key> callback  -> send_premium_invoice()
    Telegram                -> pre_checkout_query  -> handle_pre_checkout()
    Telegram                -> successful_payment  -> handle_successful_payment()
                              -> activate_payment() (idempotent per charge id)

The invoice payload embeds the plan key + buyer id, so a payment can only be
applied to the user who paid for the plan they chose.
"""

from datetime import datetime, timezone
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice

from .config import PREMIUM_STARS_ENABLED, PREMIUM_STARS_CURRENCY, PREMIUM_PLANS
from .database import premium_payments_col
from .premium_management import add_premium_user
from .user_management import log_action


def build_plans_keyboard() -> InlineKeyboardMarkup:
    """Inline keyboard of purchasable premium plans (empty -> None)."""
    rows = []
    for key, plan in PREMIUM_PLANS.items():
        label = f"{plan['days']} days — {plan['stars']} ⭐"
        rows.append([InlineKeyboardButton(label, callback_data=f"buyplan:{key}")])
    return InlineKeyboardMarkup(rows) if rows else None


def format_plans_text() -> str:
    """Human description of the available plans + what premium unlocks."""
    lines = [
        "⭐ **Get Premium**",
        "",
        "Premium unlocks: no daily download limit, /recent, /request, "
        "Get All in search results.",
        "",
    ]
    for plan in PREMIUM_PLANS.values():
        lines.append(f"• **{plan['days']} days** — {plan['stars']} ⭐")
    lines.append("")
    lines.append("Pick a plan below to pay with Telegram Stars.")
    return "\n".join(lines)


def build_payment_payload(plan_key: str, user_id: int) -> str:
    """Invoice payload embedding the plan + buyer (``premium:<key>:<uid>``)."""
    return f"premium:{plan_key}:{user_id}"


def parse_payment_payload(payload):
    """Validate a payment payload.

    Returns ``{"plan_key", "user_id", "plan"}`` or None when malformed /
    unknown (so neither a pre-checkout nor a stray successful_payment is
    trusted).
    """
    parts = (payload or "").split(":")
    if len(parts) != 3 or parts[0] != "premium":
        return None
    plan_key, uid_str = parts[1], parts[2]
    plan = PREMIUM_PLANS.get(plan_key)
    if not plan:
        return None
    try:
        user_id = int(uid_str)
    except (TypeError, ValueError):
        return None
    return {"plan_key": plan_key, "user_id": user_id, "plan": plan}


async def send_premium_invoice(client, chat_id: int, plan_key: str, user_id=None):
    """Send a Stars invoice for ``plan_key`` to ``chat_id``.

    Returns ``(ok: bool, error: str|None)``. Never raises - the caller shows a
    toast either way.
    """
    plan = PREMIUM_PLANS.get(plan_key)
    if not plan:
        return False, "Unknown plan."
    if not PREMIUM_STARS_ENABLED:
        return False, "Payments are currently disabled."
    payload = build_payment_payload(plan_key, user_id if user_id is not None else chat_id)
    try:
        await client.send_invoice(
            chat_id=chat_id,
            title=f"Premium — {plan['days']} days",
            description=f"{plan['days']} days of premium access.",
            payload=payload,
            currency=PREMIUM_STARS_CURRENCY,
            prices=[LabeledPrice(label=f"Premium {plan['days']} days",
                                 amount=plan["stars"])],
        )
        return True, None
    except Exception as e:
        print(f"⚠️ send_premium_invoice failed: {e}")
        return False, str(e)


async def handle_pre_checkout(client, pre_checkout_query):
    """Answer Telegram's pre-checkout query (reject malformed payloads)."""
    info = parse_payment_payload(getattr(pre_checkout_query, "invoice_payload", None))
    if not info:
        await client.answer_pre_checkout_query(
            pre_checkout_query.id, ok=False,
            error_message="This plan is no longer available. Use /buy_premium.")
        return False
    await client.answer_pre_checkout_query(pre_checkout_query.id, ok=True)
    return True


async def activate_payment(user_id: int, plan_key: str, charge_id: str = None,
                           provider_charge_id: str = None, username: str = None):
    """Grant premium for a paid invoice (idempotent per Telegram charge id).

    Returns ``(ok: bool, reason: str)`` where reason is ``"ok"``,
    ``"duplicate"`` or an error string.
    """
    plan = PREMIUM_PLANS.get(plan_key)
    if not plan:
        return False, "unknown_plan"

    # Idempotency: a replayed successful_payment (Telegram retries) must not
    # grant premium twice.
    if charge_id:
        try:
            existing = await premium_payments_col.find_one({"charge_id": charge_id})
        except Exception:
            existing = None
        if existing:
            return False, "duplicate"

    ok, message = await add_premium_user(
        user_id, plan["days"], added_by=0, username=username)
    if not ok:
        return False, message

    try:
        await premium_payments_col.insert_one({
            "user_id": user_id,
            "username": username,
            "plan_key": plan_key,
            "days": plan["days"],
            "stars": plan["stars"],
            "currency": PREMIUM_STARS_CURRENCY,
            "charge_id": charge_id,
            "provider_charge_id": provider_charge_id,
            "created_at": datetime.now(timezone.utc),
            "status": "completed",
        })
    except Exception as e:
        # A unique-index race (same charge id) is harmless: premium was already
        # granted on the first insert.
        print(f"⚠️ premium payment record insert failed: {e}")

    await log_action("premium_purchased", by=user_id, target=user_id, extra={
        "plan": plan_key, "days": plan["days"], "stars": plan["stars"],
        "charge_id": charge_id,
    })
    return True, "ok"


async def handle_successful_payment(client, message):
    """Activate premium after Telegram confirms a Stars payment."""
    payment = getattr(message, "successful_payment", None)
    if not payment:
        return
    info = parse_payment_payload(getattr(payment, "invoice_payload", None))
    if not info:
        print("⚠️ successful_payment with unrecognised payload - ignored")
        return

    user = getattr(message, "from_user", None)
    user_id = getattr(user, "id", info["user_id"])
    username = getattr(user, "username", None)
    charge_id = getattr(payment, "telegram_payment_charge_id", None)
    provider_charge_id = getattr(payment, "provider_payment_charge_id", None)

    ok, reason = await activate_payment(
        user_id, info["plan_key"], charge_id, provider_charge_id, username)

    plan = info["plan"]
    if ok:
        text = (
            f"🎉 **Payment received - Premium activated!**\n\n"
            f"**Plan:** {plan['days']} days\n"
            f"**Paid:** {plan['stars']} ⭐\n\n"
            f"Enjoy your premium features. Use /premium to see your status."
        )
    elif reason == "duplicate":
        text = "✅ This payment was already applied - your premium is active."
    else:
        text = ("⚠️ Payment received but activation failed. "
                "Please contact an admin with your payment id.")
        await log_action("premium_payment_error", by=user_id,
                         extra={"plan": info["plan_key"], "reason": reason,
                                "charge_id": charge_id})
    try:
        await message.reply_text(text)
    except Exception as e:
        print(f"⚠️ payment confirmation reply failed: {e}")
