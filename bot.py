import os
import re
import sqlite3
import logging
from datetime import datetime, timedelta

import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ================= CONFIG (variables de entorno) =================
BOT_TOKEN = os.environ["BOT_TOKEN"]                 # Token de BotFather
ADMIN_ID = int(os.environ["ADMIN_ID"])               # Tu ID numérico de Telegram (protegido, nunca lo saca el bot)
CHANNEL_ID = int(os.environ["CHANNEL_ID"])           # ID del canal, ej: -1001234567890
GROUP_ID = int(os.environ["GROUP_ID"])               # ID del grupo, ej: -1009876543210
CRYPTOPAY_TOKEN = os.environ["CRYPTOPAY_TOKEN"]      # Token de la app CryptoBot (Crypto Pay)
PRICE_USDT = os.environ.get("PRICE_USDT", "10")      # Precio del plan mensual
DB_PATH = os.environ.get("DB_PATH", "subs.db")
CRYPTOPAY_API = "https://pay.crypt.bot/api"

# ================= BASE DE DATOS =================
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS subscribers (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        expires_at TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS moderators (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        added_at TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS contact_sessions (
        user_id INTEGER PRIMARY KEY,
        active INTEGER
    )""")
    return conn

def set_subscriber(user_id, username, expires_at):
    conn = db()
    conn.execute(
        "INSERT INTO subscribers (user_id, username, expires_at) VALUES (?, ?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, expires_at=excluded.expires_at",
        (user_id, username, expires_at)
    )
    conn.commit()
    conn.close()

def all_expired(now_iso):
    conn = db()
    rows = conn.execute("SELECT user_id FROM subscribers WHERE expires_at < ?", (now_iso,)).fetchall()
    conn.close()
    return [r[0] for r in rows]

def remove_subscriber(user_id):
    conn = db()
    conn.execute("DELETE FROM subscribers WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def add_moderator(user_id):
    conn = db()
    conn.execute("INSERT OR REPLACE INTO moderators (user_id, username, added_at) VALUES (?, ?, ?)",
                 (user_id, str(user_id), datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()

def remove_moderator(user_id):
    conn = db()
    conn.execute("DELETE FROM moderators WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def is_moderator(user_id):
    conn = db()
    row = conn.execute("SELECT 1 FROM moderators WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row is not None

def set_contact_active(user_id, active):
    conn = db()
    conn.execute("INSERT OR REPLACE INTO contact_sessions (user_id, active) VALUES (?, ?)",
                 (user_id, 1 if active else 0))
    conn.commit()
    conn.close()

def is_contact_active(user_id):
    conn = db()
    row = conn.execute("SELECT active FROM contact_sessions WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return bool(row and row[0])

# ================= CRYPTOBOT (Crypto Pay API) =================
async def create_invoice(amount, user_id):
    headers = {"Crypto-Pay-API-Token": CRYPTOPAY_TOKEN}
    payload = {
        "asset": "USDT",
        "amount": str(amount),
        "description": f"Suscripcion mensual - usuario {user_id}",
        "payload": str(user_id),
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{CRYPTOPAY_API}/createInvoice", json=payload, headers=headers) as resp:
            data = await resp.json()
            if data.get("ok"):
                return data["result"]
            logger.error("Error creando factura: %s", data)
            return None

async def check_invoice(invoice_id):
    headers = {"Crypto-Pay-API-Token": CRYPTOPAY_TOKEN}
    params = {"invoice_ids": invoice_id}
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{CRYPTOPAY_API}/getInvoices", params=params, headers=headers) as resp:
            data = await resp.json()
            if data.get("ok") and data["result"]["items"]:
                return data["result"]["items"][0]
            return None

# ================= MENSAJES Y MENÚ =================
WELCOME = (
    "👋 ¡Bienvenido/a!\n\n"
    "Acá podés suscribirte a nuestro contenido (canal + grupo) o escribirnos "
    "si tenés dudas.\n\nElegí una opción:"
)

def main_menu():
    kb = [
        [InlineKeyboardButton(f"💳 Suscribirme ({PRICE_USDT} USDT/mes)", callback_data="subscribe")],
        [InlineKeyboardButton("✉️ Contactarme", callback_data="contact_start")],
    ]
    return InlineKeyboardMarkup(kb)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME, reply_markup=main_menu())

# ================= BOTONES =================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = query.from_user

    if data == "subscribe":
        invoice = await create_invoice(PRICE_USDT, user.id)
        if not invoice:
            await query.edit_message_text("⚠️ No se pudo generar el pago. Probá de nuevo en unos minutos.")
            return
        kb = [
            [InlineKeyboardButton("💳 Pagar ahora", url=invoice["pay_url"])],
            [InlineKeyboardButton("✅ Ya pagué / Verificar", callback_data=f"verify:{invoice['invoice_id']}")],
            [InlineKeyboardButton("⬅️ Volver", callback_data="back_menu")],
        ]
        await query.edit_message_text(
            f"Suscripción mensual: *{PRICE_USDT} USDT*\n\n"
            "1️⃣ Tocá 'Pagar ahora'\n2️⃣ Completá el pago en CryptoBot\n"
            "3️⃣ Volvé acá y tocá 'Ya pagué / Verificar'",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data.startswith("verify:"):
        invoice_id = data.split(":", 1)[1]
        invoice = await check_invoice(invoice_id)
        if invoice and invoice["status"] == "paid":
            expires = datetime.utcnow() + timedelta(days=30)
            set_subscriber(user.id, user.username or user.first_name, expires.isoformat())
            ch_link = await context.bot.create_chat_invite_link(CHANNEL_ID, member_limit=1)
            gr_link = await context.bot.create_chat_invite_link(GROUP_ID, member_limit=1)
            await query.edit_message_text(
                "✅ ¡Pago confirmado! Bienvenido/a 🎉\n\n"
                f"📢 Canal: {ch_link.invite_link}\n👥 Grupo: {gr_link.invite_link}\n\n"
                f"Tu suscripción vence el {expires.strftime('%d/%m/%Y')}."
            )
        else:
            kb = [[InlineKeyboardButton("✅ Ya pagué / Verificar", callback_data=f"verify:{invoice_id}")]]
            await query.edit_message_text(
                "⏳ Todavía no detectamos el pago. Si ya pagaste, esperá un minuto y volvé a verificar.",
                reply_markup=InlineKeyboardMarkup(kb),
            )

    elif data == "back_menu":
        await query.edit_message_text(WELCOME, reply_markup=main_menu())

    elif data == "contact_start":
        set_contact_active(user.id, True)
        kb = [[InlineKeyboardButton("❌ Cerrar conversación", callback_data="contact_close")]]
        await query.edit_message_text(
            "✍️ Escribime tu mensaje y le va a llegar directo a un administrador.",
            reply_markup=InlineKeyboardMarkup(kb),
        )

    elif data == "contact_close":
        set_contact_active(user.id, False)
        await query.edit_message_text("Conversación cerrada. Si necesitás algo más, usá /start.")

    elif data.startswith("admin_close:"):
        target_id = int(data.split(":", 1)[1])
        set_contact_active(target_id, False)
        await query.edit_message_text(f"Conversación con {target_id} cerrada.")
        try:
            await context.bot.send_message(
                target_id, "❌ El administrador cerró la conversación. Usá /start si necesitás algo más."
            )
        except Exception:
            pass

# ================= RELAY DE MENSAJES DE CONTACTO =================
async def relay_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = msg.from_user

    # El administrador responde citando (reply) el mensaje reenviado por el bot
    if user.id == ADMIN_ID and msg.reply_to_message and msg.reply_to_message.text:
        match = re.search(r"user_id:(\d+)", msg.reply_to_message.text)
        if match:
            target_id = int(match.group(1))
            if is_contact_active(target_id):
                await context.bot.send_message(target_id, f"👤 Administrador:\n{msg.text}")
                await msg.reply_text("✅ Enviado.")
            else:
                await msg.reply_text("⚠️ Esa conversación ya está cerrada.")
            return

    # Un usuario con conversación de contacto activa escribe
    if is_contact_active(user.id) and update.effective_chat.type == "private":
        kb = [[InlineKeyboardButton("❌ Cerrar conversación", callback_data=f"admin_close:{user.id}")]]
        await context.bot.send_message(
            ADMIN_ID,
            f"📩 Mensaje de contacto\nuser_id:{user.id} (@{user.username or 'sin_usuario'})\n\n{msg.text}",
            reply_markup=InlineKeyboardMarkup(kb),
        )
        await msg.reply_text("✅ Mensaje enviado. Te vamos a responder por acá.")

# ================= COMANDOS DE ADMINISTRACIÓN =================
async def addmod(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Solo el administrador principal puede usar este comando.")
        return
    if not context.args:
        await update.message.reply_text("Uso: /addmod <user_id>")
        return
    target_id = int(context.args[0])
    add_moderator(target_id)
    perms = dict(
        can_delete_messages=True, can_restrict_members=True,
        can_invite_users=True, can_pin_messages=True,
        can_promote_members=False, can_change_info=False,
    )
    try:
        await context.bot.promote_chat_member(CHANNEL_ID, target_id, **perms)
        await context.bot.promote_chat_member(GROUP_ID, target_id, **perms)
    except Exception as e:
        logger.warning("No se pudo promover en Telegram: %s", e)
    await update.message.reply_text(f"✅ {target_id} agregado como ayudante (rango limitado, no puede sacarte a vos).")

async def removemod(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Solo el administrador principal puede usar este comando.")
        return
    if not context.args:
        await update.message.reply_text("Uso: /removemod <user_id>")
        return
    target_id = int(context.args[0])
    remove_moderator(target_id)
    try:
        await context.bot.promote_chat_member(CHANNEL_ID, target_id, is_anonymous=False)
        await context.bot.promote_chat_member(GROUP_ID, target_id, is_anonymous=False)
    except Exception:
        pass
    await update.message.reply_text(f"✅ {target_id} ya no es ayudante.")

# ================= JOB DIARIO: VENCIMIENTOS =================
async def check_expired(context: ContextTypes.DEFAULT_TYPE):
    now_iso = datetime.utcnow().isoformat()
    for user_id in all_expired(now_iso):
        if user_id == ADMIN_ID:
            continue  # el admin nunca se saca
        for chat_id in (CHANNEL_ID, GROUP_ID):
            try:
                await context.bot.ban_chat_member(chat_id, user_id)
                await context.bot.unban_chat_member(chat_id, user_id, only_if_banned=True)
            except Exception as e:
                logger.warning("No se pudo sacar a %s de %s: %s", user_id, chat_id, e)
        remove_subscriber(user_id)
        try:
            await context.bot.send_message(
                user_id,
                "⚠️ Tu suscripción venció y fuiste removido del canal/grupo.\n"
                "Podés renovar cuando quieras con /start."
            )
        except Exception:
            pass

# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addmod", addmod))
    app.add_handler(CommandHandler("removemod", removemod))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, relay_message))

    app.job_queue.run_repeating(check_expired, interval=3600, first=60)

    app.run_polling()

if __name__ == "__main__":
    main()
