"""
Telegram Group Broadcaster Bot
Admin-only control panel for broadcasting messages via user-account userbots.
"""

import asyncio
import logging
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from config import Config
from account_manager import AccountManager
from broadcaster import Broadcaster
from db import Database

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

bot = Client(
    "broadcaster_bot",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    bot_token=Config.BOT_TOKEN,
)

db = Database()
account_manager = AccountManager(db)
broadcaster = Broadcaster(db, account_manager)


# ── Guards ────────────────────────────────────────────────────────────────────

def is_admin(uid: int) -> bool:
    return uid in Config.ADMIN_IDS

def admin_only(func):
    async def wrapper(client, message: Message):
        if not is_admin(message.from_user.id):
            await message.reply("⛔ Unauthorized.")
            return
        return await func(client, message)
    wrapper.__name__ = func.__name__
    return wrapper

def admin_cb(func):
    async def wrapper(client, cb: CallbackQuery):
        if not is_admin(cb.from_user.id):
            await cb.answer("⛔ Unauthorized", show_alert=True)
            return
        return await func(client, cb)
    wrapper.__name__ = func.__name__
    return wrapper


# ── /start ────────────────────────────────────────────────────────────────────

@bot.on_message(filters.command("start") & filters.private)
@admin_only
async def cmd_start(client, message: Message):
    await message.reply(
        "📣 <b>Telegram Group Broadcaster</b>\n\n"
        "<b>Account Management</b>\n"
        "• /addaccount — Add a userbot account\n"
        "• /listaccounts — View all accounts\n"
        "• /removeaccount — Remove an account\n\n"
        "<b>Broadcast</b>\n"
        "• /setmessage — Set default broadcast message\n"
        "• /setconfig — Set intervals & batch size\n"
        "• /preview — Preview config before sending\n"
        "• /broadcast — Start broadcasting\n"
        "• /stop — Stop ongoing broadcast\n\n"
        "<b>Logs & Status</b>\n"
        "• /setlogchannel — Set channel for live logs\n"
        "• /status — Current broadcast status",
        parse_mode="html",
    )


# ── /addaccount ───────────────────────────────────────────────────────────────

@bot.on_message(filters.command("addaccount") & filters.private)
@admin_only
async def cmd_add_account(client, message: Message):
    accounts = account_manager.list_accounts()
    text = f"📋 <b>Accounts ({len(accounts)}):</b>\n"
    for acc in accounts:
        icon = "🟢" if acc["active"] else "🔴"
        text += f"{icon} <code>{acc['phone']}</code> — {acc.get('label','—')} ({acc.get('group_count',0)} groups)\n"
    if not accounts:
        text += "<i>None yet.</i>\n"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("➕ Add New Account", callback_data="add_account_start")]])
    await message.reply(text, reply_markup=kb, parse_mode="html")


@bot.on_callback_query(filters.regex("^add_account_start$"))
@admin_cb
async def cb_add_account(client, cb: CallbackQuery):
    db.set_user_state(cb.from_user.id, "awaiting_account_details")
    await cb.message.edit_text(
        "📱 Send account details in this format:\n\n"
        "<code>PHONE | LABEL | CUSTOM_AD_MESSAGE(optional)</code>\n\n"
        "Examples:\n"
        "<code>+919876543210 | Shop Account | 🔥 Check our deals!</code>\n"
        "<code>+919876543210 | Shop Account</code>  ← uses default message",
        parse_mode="html",
    )


# ── /listaccounts ─────────────────────────────────────────────────────────────

@bot.on_message(filters.command("listaccounts") & filters.private)
@admin_only
async def cmd_list_accounts(client, message: Message):
    accounts = account_manager.list_accounts()
    if not accounts:
        await message.reply("📭 No accounts added yet. Use /addaccount.")
        return
    text = "📋 <b>All Accounts:</b>\n\n"
    for i, acc in enumerate(accounts, 1):
        icon = "🟢" if acc["active"] else "🔴"
        ad_preview = (acc.get("ad_message") or "— uses default")[:50]
        text += (
            f"{i}. {icon} <code>{acc['phone']}</code>\n"
            f"   Label: {acc.get('label','—')}\n"
            f"   Groups: {acc.get('group_count', '?')}\n"
            f"   Ad: <i>{ad_preview}</i>\n\n"
        )
    await message.reply(text, parse_mode="html")


# ── /removeaccount ────────────────────────────────────────────────────────────

@bot.on_message(filters.command("removeaccount") & filters.private)
@admin_only
async def cmd_remove_account(client, message: Message):
    accounts = account_manager.list_accounts()
    if not accounts:
        await message.reply("📭 No accounts to remove.")
        return
    buttons = [
        [InlineKeyboardButton(f"🗑 {a['phone']} ({a.get('label','—')})", callback_data=f"remove_acc:{a['phone']}")]
        for a in accounts
    ]
    await message.reply("Select account to remove:", reply_markup=InlineKeyboardMarkup(buttons))


@bot.on_callback_query(filters.regex("^remove_acc:"))
@admin_cb
async def cb_remove_account(client, cb: CallbackQuery):
    phone = cb.data.split(":", 1)[1]
    await account_manager.remove_account(phone)
    await cb.message.edit_text(f"✅ Account <code>{phone}</code> removed.", parse_mode="html")


# ── /setmessage ───────────────────────────────────────────────────────────────

@bot.on_message(filters.command("setmessage") & filters.private)
@admin_only
async def cmd_set_message(client, message: Message):
    db.set_user_state(message.from_user.id, "awaiting_broadcast_message")
    await message.reply(
        "✏️ Send the <b>default broadcast message</b> now.\n\n"
        "Supports Telegram formatting: bold, italic, links, emoji.\n"
        "Accounts with a custom ad message will use theirs instead.",
        parse_mode="html",
    )


# ── /setconfig ────────────────────────────────────────────────────────────────

@bot.on_message(filters.command("setconfig") & filters.private)
@admin_only
async def cmd_set_config(client, message: Message):
    cfg = db.get_broadcast_config()
    db.set_user_state(message.from_user.id, "awaiting_config")
    await message.reply(
        f"⚙️ <b>Current Config</b>\n\n"
        f"• Group interval: <code>{cfg['group_interval']}s</code>\n"
        f"• Batch size: <code>{cfg['batch_size']}</code> groups\n"
        f"• Batch interval: <code>{cfg['batch_interval']}s</code>\n\n"
        f"Send new values as: <code>GROUP_INTERVAL | BATCH_SIZE | BATCH_INTERVAL</code>\n"
        f"Example: <code>5 | 10 | 60</code>",
        parse_mode="html",
    )


# ── /setlogchannel ────────────────────────────────────────────────────────────

@bot.on_message(filters.command("setlogchannel") & filters.private)
@admin_only
async def cmd_set_log_channel(client, message: Message):
    db.set_user_state(message.from_user.id, "awaiting_log_channel")
    await message.reply(
        "📢 Send the log channel username or ID.\n"
        "Example: <code>@mybotlogs</code> or <code>-100123456789</code>\n\n"
        "⚠️ Add this bot as <b>admin</b> in that channel first.",
        parse_mode="html",
    )


# ── /preview ─────────────────────────────────────────────────────────────────

@bot.on_message(filters.command("preview") & filters.private)
@admin_only
async def cmd_preview(client, message: Message):
    msg_text = db.get_global_config("broadcast_message")
    if not msg_text:
        await message.reply("⚠️ No message set. Use /setmessage first.")
        return
    accounts = account_manager.list_accounts()
    cfg = db.get_broadcast_config()
    log_ch = db.get_global_config("log_channel") or "Not set"
    total_groups = sum(a.get("group_count", 0) for a in accounts)
    await message.reply(
        f"📋 <b>Broadcast Preview</b>\n\n"
        f"<b>Message:</b>\n{msg_text}\n\n"
        f"<b>Accounts:</b> {len(accounts)}\n"
        f"<b>Total groups:</b> ~{total_groups}\n"
        f"<b>Group interval:</b> {cfg['group_interval']}s\n"
        f"<b>Batch:</b> {cfg['batch_size']} groups then {cfg['batch_interval']}s pause\n"
        f"<b>Log channel:</b> {log_ch}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 Start Broadcast", callback_data="confirm_broadcast")],
            [InlineKeyboardButton("✏️ Edit Message", callback_data="edit_message"),
             InlineKeyboardButton("⚙️ Edit Config", callback_data="edit_config")],
        ]),
        parse_mode="html",
    )


# ── /broadcast ────────────────────────────────────────────────────────────────

@bot.on_message(filters.command("broadcast") & filters.private)
@admin_only
async def cmd_broadcast(client, message: Message):
    if broadcaster.get_status()["running"]:
        await message.reply("⚠️ A broadcast is already running. Use /stop to cancel it first.")
        return
    msg_text = db.get_global_config("broadcast_message")
    if not msg_text:
        await message.reply("⚠️ No message set. Use /setmessage first.")
        return
    accounts = account_manager.list_accounts()
    if not accounts:
        await message.reply("⚠️ No accounts added. Use /addaccount first.")
        return
    total_groups = sum(a.get("group_count", 0) for a in accounts)
    await message.reply(
        f"🚀 Ready to broadcast to ~<b>{total_groups} groups</b> via <b>{len(accounts)} account(s)</b>.\n\nConfirm?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Confirm", callback_data="confirm_broadcast"),
             InlineKeyboardButton("❌ Cancel", callback_data="cancel")],
        ]),
        parse_mode="html",
    )


@bot.on_callback_query(filters.regex("^confirm_broadcast$"))
@admin_cb
async def cb_confirm_broadcast(client, cb: CallbackQuery):
    if broadcaster.get_status()["running"]:
        await cb.answer("Already running!", show_alert=True)
        return
    status_msg = await cb.message.edit_text("⏳ Initializing broadcast…")
    asyncio.create_task(broadcaster.run(bot, cb.from_user.id, status_msg))


@bot.on_callback_query(filters.regex("^edit_message$"))
@admin_cb
async def cb_edit_message(client, cb: CallbackQuery):
    db.set_user_state(cb.from_user.id, "awaiting_broadcast_message")
    await cb.message.edit_text("✏️ Send the new broadcast message:")


@bot.on_callback_query(filters.regex("^edit_config$"))
@admin_cb
async def cb_edit_config(client, cb: CallbackQuery):
    db.set_user_state(cb.from_user.id, "awaiting_config")
    cfg = db.get_broadcast_config()
    await cb.message.edit_text(
        f"⚙️ Current: <code>{cfg['group_interval']} | {cfg['batch_size']} | {cfg['batch_interval']}</code>\n\n"
        f"Send: <code>GROUP_INTERVAL | BATCH_SIZE | BATCH_INTERVAL</code>",
        parse_mode="html",
    )


@bot.on_callback_query(filters.regex("^cancel$"))
@admin_cb
async def cb_cancel(client, cb: CallbackQuery):
    await cb.message.edit_text("❌ Cancelled.")


# ── /stop ─────────────────────────────────────────────────────────────────────

@bot.on_message(filters.command("stop") & filters.private)
@admin_only
async def cmd_stop(client, message: Message):
    if not broadcaster.get_status()["running"]:
        await message.reply("ℹ️ No broadcast is currently running.")
        return
    broadcaster.stop_flag = True
    await message.reply("🛑 Stop signal sent. Will halt after current group.")


# ── /status ───────────────────────────────────────────────────────────────────

@bot.on_message(filters.command("status") & filters.private)
@admin_only
async def cmd_status(client, message: Message):
    s = broadcaster.get_status()
    await message.reply(
        f"📊 <b>Broadcast Status</b>\n\n"
        f"Running: {'✅ Yes' if s['running'] else '❌ No'}\n"
        f"✅ Sent: {s['sent']}\n"
        f"❌ Failed: {s['failed']}\n"
        f"⏳ Flood waits: {s['flood_waits']}\n"
        f"👤 Account: <code>{s.get('current_account','—')}</code>\n"
        f"📈 Progress: {s['progress']}",
        parse_mode="html",
    )


# ── Universal text handler (state machine) ────────────────────────────────────

@bot.on_message(filters.private & filters.text & ~filters.command(["start","addaccount","listaccounts",
    "removeaccount","setmessage","setconfig","setlogchannel","preview","broadcast","stop","status"]))
@admin_only
async def handle_states(client, message: Message):
    uid = message.from_user.id
    state = db.get_user_state(uid)
    if not state:
        return

    # ── Account details ──
    if state == "awaiting_account_details":
        parts = [p.strip() for p in message.text.split("|")]
        if len(parts) < 2:
            await message.reply("❌ Format: <code>PHONE | LABEL</code> or <code>PHONE | LABEL | AD_MESSAGE</code>", parse_mode="html")
            return
        phone, label = parts[0], parts[1]
        ad_msg = parts[2] if len(parts) > 2 else None
        db.set_user_state(uid, None)
        msg = await message.reply(f"🔐 Sending OTP to <code>{phone}</code>…", parse_mode="html")
        result = await account_manager.start_login(phone, label, ad_msg)
        if result["status"] == "otp_sent":
            db.set_user_state(uid, f"awaiting_otp:{phone}")
            await msg.edit_text(f"✅ OTP sent to <code>{phone}</code>.\n\nSend the code you received:", parse_mode="html")
        else:
            await msg.edit_text(f"❌ {result.get('error','Unknown error')}")

    # ── OTP ──
    elif state and state.startswith("awaiting_otp:"):
        phone = state.split(":", 1)[1]
        db.set_user_state(uid, None)
        msg = await message.reply("🔄 Verifying OTP…")
        result = await account_manager.complete_login(phone, message.text.strip())
        if result["status"] == "2fa_required":
            db.set_user_state(uid, f"awaiting_2fa:{phone}")
            await msg.edit_text("🔒 2FA enabled. Send your cloud password:")
        elif result["status"] == "success":
            acc = db.get_account(phone)
            await msg.edit_text(f"✅ Account <code>{phone}</code> added! Found {acc.get('group_count',0)} groups.", parse_mode="html")
        else:
            await msg.edit_text(f"❌ {result.get('error')}")

    # ── 2FA ──
    elif state and state.startswith("awaiting_2fa:"):
        phone = state.split(":", 1)[1]
        db.set_user_state(uid, None)
        msg = await message.reply("🔄 Checking password…")
        result = await account_manager.complete_2fa(phone, message.text.strip())
        if result["status"] == "success":
            acc = db.get_account(phone)
            await msg.edit_text(f"✅ Account <code>{phone}</code> added! Found {acc.get('group_count',0)} groups.", parse_mode="html")
        else:
            await msg.edit_text(f"❌ {result.get('error')}")

    # ── Broadcast message ──
    elif state == "awaiting_broadcast_message":
        db.set_user_state(uid, None)
        db.set_global_config("broadcast_message", message.text)
        await message.reply("✅ Broadcast message saved! Use /preview to review.", parse_mode="html")

    # ── Config ──
    elif state == "awaiting_config":
        parts = [p.strip() for p in message.text.split("|")]
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            await message.reply("❌ Format: <code>GROUP_INTERVAL | BATCH_SIZE | BATCH_INTERVAL</code>\nExample: <code>5 | 10 | 60</code>", parse_mode="html")
            return
        db.set_global_config("group_interval", parts[0])
        db.set_global_config("batch_size", parts[1])
        db.set_global_config("batch_interval", parts[2])
        db.set_user_state(uid, None)
        await message.reply(
            f"✅ Config updated!\n"
            f"• Group interval: <code>{parts[0]}s</code>\n"
            f"• Batch size: <code>{parts[1]}</code> groups\n"
            f"• Batch interval: <code>{parts[2]}s</code>",
            parse_mode="html",
        )

    # ── Log channel ──
    elif state == "awaiting_log_channel":
        db.set_user_state(uid, None)
        channel = message.text.strip()
        db.set_global_config("log_channel", channel)
        await message.reply(f"✅ Log channel set to <code>{channel}</code>\n\nMake sure the bot is admin there.", parse_mode="html")


# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("Starting Broadcaster Bot…")
    bot.run()
