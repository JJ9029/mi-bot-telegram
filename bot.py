import os
import re
import sqlite3
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def now_utc():
    """Devuelve la hora actual en UTC (naive) sin usar datetime.utcnow(), que está deprecado."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

# ================= CONFIG (variables de entorno) =================
BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ["ADMIN_ID"])
CHANNEL_ID = int(os.environ["CHANNEL_ID"])
GROUP_ID = int(os.environ["GROUP_ID"])
PRICE_USDT = os.environ.get("PRICE_USDT", "10")
PAYMENT_WALLET = os.environ.get("PAYMENT_WALLET", "TU_DIRECCION_DE_WALLET_ACA")
PAYMENT_NETWORK = os.environ.get("PAYMENT_NETWORK", "TRC20 (Tron)")
DB_PATH = os.environ.get("DB_PATH", "bot.db")
INVITE_LINK_HOURS = 48  # los links de invitación expiran solos después de este tiempo

# ================= TEXTOS EDITABLES =================
INFO_TEXT = (
    "ℹ️ Acá va tu información personalizada.\n\n"
    "Editá la variable INFO_TEXT en bot.py con el texto que quieras mostrar "
    "(reglas del canal, qué incluye la suscripción, etc.)."
)

WELCOME = "👋 ¡Bienvenido/a!\n\nElegí una opción:"

ADMIN_COMMANDS_TEXT = (
    "🔐 *Panel de administración*\n\n"
    "*Suscripciones*\n"
    "/activar <user_id> <días> — activa o renueva (suma días si ya está activa)\n"
    "/restardias <user_id> <días> — resta días de la suscripción\n"
    "/desactivar <user_id> — cancela la suscripción y lo saca del canal/grupo\n"
    "/diasrestantes <user_id> — desde cuándo está suscripto y días restantes\n"
    "/listasuscriptores — lista todos los suscriptores activos\n"
    "/pendientes — avisos de 'Ya pagué' que faltan activar\n"
    "/revisarahora — fuerza la revisión de vencimientos ya mismo\n"
    "/estadisticas — resumen de suscriptores activos y por vencer\n"
    "/backup — te manda la base de datos por privado\n"
    "/avisar <texto> — mensaje a todos los suscriptores activos\n\n"
    "*Rangos*\n"
    "/addmod <user_id> — da rango de ayudante (solo admin principal)\n"
    "/removemod <user_id> — quita rango de ayudante (solo admin principal)\n\n"
    "*Moderación*\n"
    "/ban <user_id> — banea del canal y grupo\n"
    "/unban <user_id> — desbanea\n"
    "/kick <user_id> — saca sin banear (puede volver a entrar)\n"
    "/mute <user_id> <tiempo> — silencia en el grupo (ej: 30m, 1h, 2d)\n"
    "/unmute <user_id> — quita el silencio\n"
    "/resetavisos <user_id> — reinicia advertencias del filtro de palabras\n\n"
    "*Palabras prohibidas*\n"
    "/agregarpalabra <palabra>\n"
    "/quitarpalabra <palabra>\n"
    "/listapalabras"
)

# ================= BASE DE DATOS =================
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS subscribers (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        expires_at TEXT,
        started_at TEXT,
        reminded INTEGER DEFAULT 0
    )""")
    for col, coltype in (("started_at", "TEXT"), ("reminded", "INTEGER DEFAULT 0")):
        try:
            conn.execute(f"ALTER TABLE subscribers ADD COLUMN {col} {coltype}")
            conn.commit()
        except sqlite3.OperationalError:
            pass
    conn.execute("""CREATE TABLE IF NOT EXISTS moderators (
        user_id INTEGER PRIMARY KEY,
        added_at TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS contact_sessions (
        user_id INTEGER PRIMARY KEY,
        active INTEGER
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS known_names (
        user_id INTEGER PRIMARY KEY,
        name TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS banned_words (
        word TEXT PRIMARY KEY
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS warnings (
        user_id INTEGER PRIMARY KEY,
        count INTEGER
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS mute_history (
        user_id INTEGER PRIMARY KEY,
        times_muted INTEGER
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS payment_requests (
        user_id INTEGER PRIMARY KEY,
        requested_at TEXT,
        resolved INTEGER DEFAULT 0
    )""")
    return conn

# ---- Suscriptores ----
def set_subscriber(user_id, username, expires_at, reset_reminder=True):
    conn = db()
    existing = conn.execute("SELECT started_at FROM subscribers WHERE user_id=?", (user_id,)).fetchone()
    started_at = existing[0] if existing and existing[0] else now_utc().isoformat()
    reminded = 0 if reset_reminder else None
    if reminded is None:
        conn.execute(
            "INSERT INTO subscribers (user_id, username, expires_at, started_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, expires_at=excluded.expires_at, "
            "started_at=excluded.started_at",
            (user_id, username, expires_at, started_at)
        )
    else:
        conn.execute(
            "INSERT INTO subscribers (user_id, username, expires_at, started_at, reminded) VALUES (?, ?, ?, ?, 0) "
            "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, expires_at=excluded.expires_at, "
            "started_at=excluded.started_at, reminded=0",
            (user_id, username, expires_at, started_at)
        )
    conn.commit()
    conn.close()

def get_subscriber(user_id):
    conn = db()
    row = conn.execute(
        "SELECT user_id, username, expires_at, started_at FROM subscribers WHERE user_id=?", (user_id,)
    ).fetchone()
    conn.close()
    return row

def all_active_subscribers():
    conn = db()
    rows = conn.execute("SELECT user_id, expires_at FROM subscribers ORDER BY expires_at ASC").fetchall()
    conn.close()
    return rows

def all_expired(now_iso):
    conn = db()
    rows = conn.execute("SELECT user_id FROM subscribers WHERE expires_at < ?", (now_iso,)).fetchall()
    conn.close()
    return [r[0] for r in rows]

def all_expiring_soon_unreminded(now_iso, soon_iso):
    conn = db()
    rows = conn.execute(
        "SELECT user_id, expires_at FROM subscribers WHERE expires_at >= ? AND expires_at < ? AND reminded=0",
        (now_iso, soon_iso)
    ).fetchall()
    conn.close()
    return rows

def mark_reminded(user_id):
    conn = db()
    conn.execute("UPDATE subscribers SET reminded=1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def remove_subscriber(user_id):
    conn = db()
    conn.execute("DELETE FROM subscribers WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

# ---- Moderadores ----
def add_moderator(user_id):
    conn = db()
    conn.execute("INSERT OR REPLACE INTO moderators (user_id, added_at) VALUES (?, ?)",
                 (user_id, now_utc().isoformat()))
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

def is_admin_or_mod(user_id):
    return user_id == ADMIN_ID or is_moderator(user_id)

# ---- Contacto ----
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

# ---- Nombres conocidos ----
def get_known_name(user_id):
    conn = db()
    row = conn.execute("SELECT name FROM known_names WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row[0] if row else None

def set_known_name(user_id, name):
    conn = db()
    conn.execute("INSERT OR REPLACE INTO known_names (user_id, name) VALUES (?, ?)", (user_id, name))
    conn.commit()
    conn.close()

# ---- Palabras prohibidas ----
DEFAULT_BAD_WORDS = [
    "puta", "puto", "mierda", "pendejo", "cabron", "cabrón", "verga",
    "pinche", "chinga", "gilipollas", "coño", "hijueputa", "hp",
]

def init_banned_words():
    conn = db()
    for w in DEFAULT_BAD_WORDS:
        conn.execute("INSERT OR IGNORE INTO banned_words (word) VALUES (?)", (w,))
    conn.commit()
    conn.close()

def get_banned_words():
    conn = db()
    rows = conn.execute("SELECT word FROM banned_words").fetchall()
    conn.close()
    return [r[0] for r in rows]

def add_banned_word(word):
    conn = db()
    conn.execute("INSERT OR IGNORE INTO banned_words (word) VALUES (?)", (word.lower(),))
    conn.commit()
    conn.close()

def remove_banned_word(word):
    conn = db()
    conn.execute("DELETE FROM banned_words WHERE word=?", (word.lower(),))
    conn.commit()
    conn.close()

# ---- Advertencias y muteos progresivos ----
def get_warnings(user_id):
    conn = db()
    row = conn.execute("SELECT count FROM warnings WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row[0] if row else 0

def set_warnings(user_id, count):
    conn = db()
    conn.execute("INSERT OR REPLACE INTO warnings (user_id, count) VALUES (?, ?)", (user_id, count))
    conn.commit()
    conn.close()

def get_times_muted(user_id):
    conn = db()
    row = conn.execute("SELECT times_muted FROM mute_history WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row[0] if row else 0

def increment_times_muted(user_id):
    times = get_times_muted(user_id) + 1
    conn = db()
    conn.execute("INSERT OR REPLACE INTO mute_history (user_id, times_muted) VALUES (?, ?)", (user_id, times))
    conn.commit()
    conn.close()
    return times

# ---- Pedidos de pago pendientes ----
def add_payment_request(user_id):
    conn = db()
    conn.execute(
        "INSERT OR REPLACE INTO payment_requests (user_id, requested_at, resolved) VALUES (?, ?, 0)",
        (user_id, now_utc().isoformat())
    )
    conn.commit()
    conn.close()

def resolve_payment_request(user_id):
    conn = db()
    conn.execute("UPDATE payment_requests SET resolved=1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def get_pending_payments():
    conn = db()
    rows = conn.execute(
        "SELECT user_id, requested_at FROM payment_requests WHERE resolved=0 ORDER BY requested_at ASC"
    ).fetchall()
    conn.close()
    return rows

# ================= MENÚ PRINCIPAL =================
def main_menu(user_id):
    kb = [
        [InlineKeyboardButton("💳 Cómo pagar", callback_data="payment_info")],
        [InlineKeyboardButton("📋 Mi perfil", callback_data="my_profile")],
        [InlineKeyboardButton("ℹ️ Información", callback_data="show_info")],
        [InlineKeyboardButton("✉️ Contactarme", callback_data="contact_start")],
    ]
    if user_id == ADMIN_ID:
        kb.append([InlineKeyboardButton("🔐 ADMIN", callback_data="admin_panel")])
    return InlineKeyboardMarkup(kb)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME, reply_markup=main_menu(update.effective_user.id))

# ================= BOTONES =================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = query.from_user

    if data == "payment_info":
        kb = [
            [InlineKeyboardButton("✅ Ya pagué", callback_data="notify_payment")],
            [InlineKeyboardButton("⬅️ Volver", callback_data="back_menu")],
        ]
        await query.edit_message_text(
            f"💳 *Suscripción mensual: {PRICE_USDT} USDT*\n\n"
            f"Red: *{PAYMENT_NETWORK}*\n"
            f"Wallet:\n`{PAYMENT_WALLET}`\n\n"
            "1️⃣ Enviá el monto exacto a esa dirección, usando la red indicada.\n"
            "2️⃣ Tocá 'Ya pagué' y mandame el hash (ID) de la transacción.\n"
            "3️⃣ En cuanto lo confirme, activo tu acceso.",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data == "notify_payment":
        set_contact_active(user.id, True)
        add_payment_request(user.id)
        kb = [[InlineKeyboardButton("❌ Cerrar conversación", callback_data="contact_close")]]
        await query.edit_message_text(
            "✍️ Mandame el hash (ID) de la transacción o cualquier comprobante y lo reviso.",
            reply_markup=InlineKeyboardMarkup(kb),
        )

    elif data == "my_profile":
        kb = [[InlineKeyboardButton("⬅️ Volver", callback_data="back_menu")]]
        sub = get_subscriber(user.id)
        if sub:
            expires_at = datetime.fromisoformat(sub[2])
            dias_restantes = (expires_at - now_utc()).days
            if dias_restantes >= 0:
                texto = (
                    f"📋 *Tu perfil*\n\nID: `{user.id}`\nSuscripción activa ✅\n"
                    f"Vence el: {expires_at.strftime('%d/%m/%Y')}\nDías restantes: *{dias_restantes}*"
                )
            else:
                texto = (
                    f"📋 *Tu perfil*\n\nID: `{user.id}`\nTu suscripción venció ❌\n"
                    "Usá 'Cómo pagar' para renovar."
                )
        else:
            texto = f"📋 *Tu perfil*\n\nID: `{user.id}`\nNo tenés una suscripción activa."
        await query.edit_message_text(texto, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)

    elif data == "show_info":
        kb = [[InlineKeyboardButton("⬅️ Volver", callback_data="back_menu")]]
        await query.edit_message_text(INFO_TEXT, reply_markup=InlineKeyboardMarkup(kb))

    elif data == "admin_panel":
        if user.id != ADMIN_ID:
            await query.answer("⛔ No tenés acceso a esto.", show_alert=True)
            return
        kb = [[InlineKeyboardButton("⬅️ Volver", callback_data="back_menu")]]
        await query.edit_message_text(ADMIN_COMMANDS_TEXT, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)

    elif data == "back_menu":
        await query.edit_message_text(WELCOME, reply_markup=main_menu(user.id))

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

# ================= RELAY DE MENSAJES PRIVADOS =================
async def relay_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = msg.from_user

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

    if is_contact_active(user.id) and update.effective_chat.type == "private":
        kb = [[InlineKeyboardButton("❌ Cerrar conversación", callback_data=f"admin_close:{user.id}")]]
        await context.bot.send_message(
            ADMIN_ID,
            f"📩 Mensaje\nuser_id:{user.id} (@{user.username or 'sin_usuario'})\n\n{msg.text}\n\n"
            f"Si es un pago confirmado, activá con:\n/activar {user.id} <días>",
            reply_markup=InlineKeyboardMarkup(kb),
        )
        await msg.reply_text("✅ Mensaje enviado. Te vamos a responder por acá.")

# ================= CREAR LINKS DE INVITACIÓN =================
async def crear_links_invitacion(context):
    expire_at = datetime.now(timezone.utc) + timedelta(hours=INVITE_LINK_HOURS)
    ch_link = await context.bot.create_chat_invite_link(CHANNEL_ID, member_limit=1, expire_date=expire_at)
    gr_link = await context.bot.create_chat_invite_link(GROUP_ID, member_limit=1, expire_date=expire_at)
    return ch_link.invite_link, gr_link.invite_link

# ================= ACTIVAR / RESTAR / DESACTIVAR =================
async def activar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_or_mod(update.effective_user.id):
        await update.message.reply_text("⛔ No tenés permiso para usar este comando.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Uso: /activar <user_id> <días>")
        return
    try:
        target_id = int(context.args[0])
        days = int(context.args[1])
    except ValueError:
        await update.message.reply_text("El user_id y los días deben ser números.")
        return

    now = now_utc()
    existing = get_subscriber(target_id)
    was_active = existing and datetime.fromisoformat(existing[2]) > now

    if was_active:
        base = datetime.fromisoformat(existing[2])
        expires = base + timedelta(days=days)
    else:
        expires = now + timedelta(days=days)

    set_subscriber(target_id, str(target_id), expires.isoformat())
    resolve_payment_request(target_id)
    dias_restantes = (expires - now).days

    if was_active:
        try:
            await context.bot.send_message(
                target_id,
                f"✅ ¡Tu suscripción fue renovada! 🎉\n\n"
                f"Se sumaron {days} día(s) a los que te quedaban.\n"
                f"Ahora vence el {expires.strftime('%d/%m/%Y')} ({dias_restantes} días restantes en total)."
            )
        except Exception as e:
            await update.message.reply_text(
                f"⚠️ Se renovó, pero no pude avisarle (probablemente nunca dio /start). Error: {e}"
            )
            return
        await update.message.reply_text(
            f"✅ {target_id} renovado: +{days} días. Vence el {expires.strftime('%d/%m/%Y')} ({dias_restantes} días en total)."
        )
    else:
        try:
            ch_link, gr_link = await crear_links_invitacion(context)
            await context.bot.send_message(
                target_id,
                "✅ ¡Tu acceso fue activado! 🎉\n\n"
                f"📢 Canal: {ch_link}\n👥 Grupo: {gr_link}\n\n"
                f"Estos links expiran en {INVITE_LINK_HOURS}hs si no los usás.\n"
                f"Vence el {expires.strftime('%d/%m/%Y')} ({dias_restantes} días)."
            )
        except Exception as e:
            await update.message.reply_text(
                f"⚠️ Se activó en la base de datos, pero NO pude mandarle los links "
                f"(probablemente nunca dio /start). Pedile que le escriba /start y volvé a correr "
                f"este comando. Error: {e}"
            )
            return
        await update.message.reply_text(
            f"✅ {target_id} activado por {days} días. Vence el {expires.strftime('%d/%m/%Y')}."
        )

async def restardias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_or_mod(update.effective_user.id):
        await update.message.reply_text("⛔ No tenés permiso para usar este comando.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Uso: /restardias <user_id> <días>")
        return
    try:
        target_id = int(context.args[0])
        days = int(context.args[1])
    except ValueError:
        await update.message.reply_text("El user_id y los días deben ser números.")
        return
    sub = get_subscriber(target_id)
    if not sub:
        await update.message.reply_text(f"{target_id} no tiene suscripción registrada.")
        return
    expires = datetime.fromisoformat(sub[2]) - timedelta(days=days)
    now = now_utc()
    set_subscriber(target_id, str(target_id), expires.isoformat(), reset_reminder=False)
    if expires <= now:
        # Le restamos suficiente como para dejarlo vencido: lo sacamos ya mismo
        for chat_id in (CHANNEL_ID, GROUP_ID):
            try:
                await context.bot.ban_chat_member(chat_id, target_id)
                await context.bot.unban_chat_member(chat_id, target_id, only_if_banned=True)
            except Exception as e:
                logger.warning("No se pudo sacar a %s de %s: %s", target_id, chat_id, e)
        remove_subscriber(target_id)
        await update.message.reply_text(f"✅ {target_id} quedó sin días restantes y fue removido del canal/grupo.")
        try:
            await context.bot.send_message(target_id, "⚠️ Tu suscripción fue ajustada y ya no tenés acceso. Escribime con /start si querés renovar.")
        except Exception:
            pass
    else:
        dias_restantes = (expires - now).days
        await update.message.reply_text(
            f"✅ Se restaron {days} días a {target_id}. Vence el {expires.strftime('%d/%m/%Y')} ({dias_restantes} días restantes)."
        )

async def desactivar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_or_mod(update.effective_user.id):
        await update.message.reply_text("⛔ No tenés permiso para usar este comando.")
        return
    if not context.args:
        await update.message.reply_text("Uso: /desactivar <user_id>")
        return
    target_id = int(context.args[0])
    if target_id == ADMIN_ID:
        await update.message.reply_text("⛔ No podés desactivar al administrador principal.")
        return
    for chat_id in (CHANNEL_ID, GROUP_ID):
        try:
            await context.bot.ban_chat_member(chat_id, target_id)
            await context.bot.unban_chat_member(chat_id, target_id, only_if_banned=True)
        except Exception as e:
            logger.warning("No se pudo sacar a %s de %s: %s", target_id, chat_id, e)
    remove_subscriber(target_id)
    await update.message.reply_text(f"✅ {target_id} fue removido y su suscripción cancelada.")

async def diasrestantes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_or_mod(update.effective_user.id):
        await update.message.reply_text("⛔ No tenés permiso para usar este comando.")
        return
    if not context.args:
        await update.message.reply_text("Uso: /diasrestantes <user_id>")
        return
    target_id = int(context.args[0])
    sub = get_subscriber(target_id)
    if not sub:
        await update.message.reply_text(f"{target_id} no tiene ninguna suscripción registrada.")
        return
    expires_at = datetime.fromisoformat(sub[2])
    started_at = datetime.fromisoformat(sub[3]) if sub[3] else None
    dias_restantes = (expires_at - now_utc()).days
    texto = f"📋 Usuario: {target_id}\n"
    if started_at:
        texto += f"Suscripto desde: {started_at.strftime('%d/%m/%Y')}\n"
    texto += f"Vence el: {expires_at.strftime('%d/%m/%Y')}\n"
    texto += f"Días restantes: {dias_restantes}" if dias_restantes >= 0 else "Estado: VENCIDA ❌"
    await update.message.reply_text(texto)

async def listasuscriptores(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_or_mod(update.effective_user.id):
        await update.message.reply_text("⛔ No tenés permiso para usar este comando.")
        return
    subs = all_active_subscribers()
    if not subs:
        await update.message.reply_text("No hay suscriptores registrados.")
        return
    now = now_utc()
    lineas = ["📋 *Suscriptores*\n"]
    for user_id, expires_at in subs:
        exp = datetime.fromisoformat(expires_at)
        dias = (exp - now).days
        estado = f"{dias}d restantes" if dias >= 0 else "VENCIDA"
        lineas.append(f"`{user_id}` — vence {exp.strftime('%d/%m/%Y')} ({estado})")
    await update.message.reply_text("\n".join(lineas), parse_mode=ParseMode.MARKDOWN)

async def pendientes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_or_mod(update.effective_user.id):
        await update.message.reply_text("⛔ No tenés permiso para usar este comando.")
        return
    pend = get_pending_payments()
    if not pend:
        await update.message.reply_text("No hay pagos pendientes de activar. ✅")
        return
    lineas = ["🕐 *Pagos pendientes de activar*\n"]
    for user_id, requested_at in pend:
        fecha = datetime.fromisoformat(requested_at)
        lineas.append(f"`{user_id}` — avisó el {fecha.strftime('%d/%m/%Y %H:%M')} UTC")
    await update.message.reply_text("\n".join(lineas), parse_mode=ParseMode.MARKDOWN)

async def estadisticas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_or_mod(update.effective_user.id):
        await update.message.reply_text("⛔ No tenés permiso para usar este comando.")
        return
    now = now_utc()
    en_7_dias = now + timedelta(days=7)
    subs = all_active_subscribers()
    activos = [s for s in subs if datetime.fromisoformat(s[1]) > now]
    por_vencer = [s for s in activos if datetime.fromisoformat(s[1]) <= en_7_dias]
    pend = get_pending_payments()
    texto = (
        f"📊 *Estadísticas*\n\n"
        f"Suscriptores activos: {len(activos)}\n"
        f"Vencen en los próximos 7 días: {len(por_vencer)}\n"
        f"Pagos pendientes de activar: {len(pend)}"
    )
    await update.message.reply_text(texto, parse_mode=ParseMode.MARKDOWN)

async def backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Solo el administrador principal puede usar este comando.")
        return
    try:
        await update.message.reply_document(document=open(DB_PATH, "rb"), filename="backup_bot.db")
    except Exception as e:
        await update.message.reply_text(f"⚠️ No se pudo generar el backup: {e}")

async def avisar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_or_mod(update.effective_user.id):
        await update.message.reply_text("⛔ No tenés permiso para usar este comando.")
        return
    if not context.args:
        await update.message.reply_text("Uso: /avisar <texto>")
        return
    texto = " ".join(context.args)
    now = now_utc()
    subs = [s for s in all_active_subscribers() if datetime.fromisoformat(s[1]) > now]
    enviados, fallidos = 0, 0
    for user_id, _ in subs:
        try:
            await context.bot.send_message(user_id, f"📢 Aviso:\n\n{texto}")
            enviados += 1
        except Exception:
            fallidos += 1
        await asyncio.sleep(0.05)
    await update.message.reply_text(f"✅ Aviso enviado a {enviados} suscriptores. Fallaron: {fallidos}.")

async def revisarahora(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_or_mod(update.effective_user.id):
        await update.message.reply_text("⛔ No tenés permiso para usar este comando.")
        return
    removidos = await _revisar_vencimientos(context)
    await update.message.reply_text(f"✅ Revisión manual completa. Removidos: {removidos}.")

# ================= ADMIN / MODERADORES =================
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

# ================= BAN / UNBAN / KICK / MUTE / UNMUTE =================
def parse_duration(text):
    match = re.match(r"^(\d+)([mhd])$", text.lower().strip())
    if not match:
        return None
    value, unit = int(match.group(1)), match.group(2)
    if unit == "m":
        return timedelta(minutes=value)
    if unit == "h":
        return timedelta(hours=value)
    if unit == "d":
        return timedelta(days=value)
    return None

async def ban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_or_mod(update.effective_user.id):
        await update.message.reply_text("⛔ No tenés permiso para usar este comando.")
        return
    if not context.args:
        await update.message.reply_text("Uso: /ban <user_id>")
        return
    target_id = int(context.args[0])
    if target_id == ADMIN_ID:
        await update.message.reply_text("⛔ No podés banear al administrador principal.")
        return
    for chat_id in (CHANNEL_ID, GROUP_ID):
        try:
            await context.bot.ban_chat_member(chat_id, target_id)
        except Exception as e:
            logger.warning("Error baneando en %s: %s", chat_id, e)
    remove_subscriber(target_id)
    await update.message.reply_text(f"🚫 {target_id} fue baneado del canal y grupo.")

async def unban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_or_mod(update.effective_user.id):
        await update.message.reply_text("⛔ No tenés permiso para usar este comando.")
        return
    if not context.args:
        await update.message.reply_text("Uso: /unban <user_id>")
        return
    target_id = int(context.args[0])
    for chat_id in (CHANNEL_ID, GROUP_ID):
        try:
            await context.bot.unban_chat_member(chat_id, target_id)
        except Exception as e:
            logger.warning("Error desbaneando en %s: %s", chat_id, e)
    await update.message.reply_text(f"✅ {target_id} fue desbaneado.")

async def kick_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_or_mod(update.effective_user.id):
        await update.message.reply_text("⛔ No tenés permiso para usar este comando.")
        return
    if not context.args:
        await update.message.reply_text("Uso: /kick <user_id>")
        return
    target_id = int(context.args[0])
    if target_id == ADMIN_ID:
        await update.message.reply_text("⛔ No podés sacar al administrador principal.")
        return
    for chat_id in (CHANNEL_ID, GROUP_ID):
        try:
            await context.bot.ban_chat_member(chat_id, target_id)
            await context.bot.unban_chat_member(chat_id, target_id, only_if_banned=True)
        except Exception as e:
            logger.warning("Error sacando a %s de %s: %s", target_id, chat_id, e)
    await update.message.reply_text(f"👢 {target_id} fue sacado del canal/grupo (sin banear, puede volver a entrar).")

async def mute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_or_mod(update.effective_user.id):
        await update.message.reply_text("⛔ No tenés permiso para usar este comando.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Uso: /mute <user_id> <tiempo>  (ej: 1h, 2d, 30m)")
        return
    target_id = int(context.args[0])
    if target_id == ADMIN_ID:
        await update.message.reply_text("⛔ No podés mutear al administrador principal.")
        return
    duration = parse_duration(context.args[1])
    if not duration:
        await update.message.reply_text("Formato de tiempo inválido. Usá algo como 30m, 1h o 2d.")
        return
    until = datetime.now(timezone.utc) + duration
    try:
        await context.bot.restrict_chat_member(
            GROUP_ID, target_id, permissions=ChatPermissions(can_send_messages=False), until_date=until,
        )
        await update.message.reply_text(f"🔇 {target_id} muteado hasta {until.strftime('%d/%m/%Y %H:%M')} UTC.")
    except Exception as e:
        await update.message.reply_text(f"⚠️ No se pudo mutear: {e}")

async def unmute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_or_mod(update.effective_user.id):
        await update.message.reply_text("⛔ No tenés permiso para usar este comando.")
        return
    if not context.args:
        await update.message.reply_text("Uso: /unmute <user_id>")
        return
    target_id = int(context.args[0])
    try:
        await context.bot.restrict_chat_member(
            GROUP_ID, target_id,
            permissions=ChatPermissions(
                can_send_messages=True, can_send_audios=True, can_send_documents=True,
                can_send_photos=True, can_send_videos=True, can_send_video_notes=True,
                can_send_voice_notes=True, can_send_polls=True, can_send_other_messages=True,
                can_add_web_page_previews=True,
            ),
        )
        await update.message.reply_text(f"🔊 {target_id} ya puede volver a escribir.")
    except Exception as e:
        await update.message.reply_text(f"⚠️ No se pudo desmutear: {e}")

async def resetavisos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_or_mod(update.effective_user.id):
        await update.message.reply_text("⛔ No tenés permiso para usar este comando.")
        return
    if not context.args:
        await update.message.reply_text("Uso: /resetavisos <user_id>")
        return
    target_id = int(context.args[0])
    set_warnings(target_id, 0)
    await update.message.reply_text(f"✅ Advertencias de {target_id} reiniciadas a 0.")

# ================= LISTA DE PALABRAS PROHIBIDAS =================
async def agregarpalabra(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_or_mod(update.effective_user.id):
        await update.message.reply_text("⛔ No tenés permiso para usar este comando.")
        return
    if not context.args:
        await update.message.reply_text("Uso: /agregarpalabra <palabra>")
        return
    word = " ".join(context.args)
    add_banned_word(word)
    await update.message.reply_text(f"✅ '{word}' agregada a la lista de palabras prohibidas.")

async def quitarpalabra(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_or_mod(update.effective_user.id):
        await update.message.reply_text("⛔ No tenés permiso para usar este comando.")
        return
    if not context.args:
        await update.message.reply_text("Uso: /quitarpalabra <palabra>")
        return
    word = " ".join(context.args)
    remove_banned_word(word)
    await update.message.reply_text(f"✅ '{word}' quitada de la lista de palabras prohibidas.")

async def listapalabras(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin_or_mod(update.effective_user.id):
        await update.message.reply_text("⛔ No tenés permiso para usar este comando.")
        return
    words = get_banned_words()
    await update.message.reply_text("Palabras prohibidas:\n" + ", ".join(words) if words else "No hay palabras cargadas.")

# ================= MENSAJES DEL GRUPO =================
async def group_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.from_user:
        return
    user = msg.from_user

    current_name = user.full_name
    known_name = get_known_name(user.id)
    if known_name is None:
        set_known_name(user.id, current_name)
    elif known_name != current_name:
        set_known_name(user.id, current_name)
        try:
            await context.bot.send_message(
                GROUP_ID,
                f"✏️ Cambio de nombre detectado\nID: {user.id}\n"
                f"Nombre anterior: {known_name}\nNombre nuevo: {current_name}"
            )
        except Exception as e:
            logger.warning("No se pudo avisar cambio de nombre: %s", e)

    if is_admin_or_mod(user.id):
        return

    text = (msg.text or msg.caption or "").lower()
    if not text:
        return
    bad_words = get_banned_words()
    if any(w in text for w in bad_words):
        try:
            await msg.delete()
        except Exception:
            pass

        warnings = get_warnings(user.id) + 1
        set_warnings(user.id, warnings)

        if warnings <= 2:
            try:
                await context.bot.send_message(
                    GROUP_ID,
                    f"⚠️ {user.mention_html()}, tu mensaje fue eliminado por contener lenguaje prohibido. "
                    f"Advertencia {warnings}/2.",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass
        else:
            times = increment_times_muted(user.id)
            mute_days = 2 ** (times - 1)
            until = datetime.now(timezone.utc) + timedelta(days=mute_days)
            set_warnings(user.id, 0)
            try:
                await context.bot.restrict_chat_member(
                    GROUP_ID, user.id, permissions=ChatPermissions(can_send_messages=False), until_date=until,
                )
                await context.bot.send_message(
                    GROUP_ID,
                    f"🔇 {user.mention_html()} fue muteado por {mute_days} día(s) por reincidir con lenguaje prohibido.",
                    parse_mode=ParseMode.HTML,
                )
            except Exception as e:
                logger.warning("No se pudo mutear tras infracciones: %s", e)

# ================= JOBS AUTOMÁTICOS =================
async def _revisar_vencimientos(context):
    now_iso = now_utc().isoformat()
    removidos = 0
    for user_id in all_expired(now_iso):
        if user_id == ADMIN_ID:
            continue
        for chat_id in (CHANNEL_ID, GROUP_ID):
            try:
                await context.bot.ban_chat_member(chat_id, user_id)
                await context.bot.unban_chat_member(chat_id, user_id, only_if_banned=True)
            except Exception as e:
                logger.warning("No se pudo sacar a %s de %s: %s", user_id, chat_id, e)
        remove_subscriber(user_id)
        removidos += 1
        try:
            await context.bot.send_message(
                user_id,
                "⚠️ Tu suscripción venció y fuiste removido del canal/grupo.\n"
                "Escribime con /start si querés renovar."
            )
        except Exception:
            pass
    return removidos

async def check_expired(context: ContextTypes.DEFAULT_TYPE):
    await _revisar_vencimientos(context)

async def check_expiring_soon(context: ContextTypes.DEFAULT_TYPE):
    now = now_utc()
    soon = now + timedelta(days=1)
    for user_id, expires_at in all_expiring_soon_unreminded(now.isoformat(), soon.isoformat()):
        if user_id == ADMIN_ID:
            continue
        exp = datetime.fromisoformat(expires_at)
        try:
            await context.bot.send_message(
                user_id,
                f"⏰ Tu suscripción vence el {exp.strftime('%d/%m/%Y')} (menos de 24hs). "
                "Si querés renovar antes de que te saquemos del canal/grupo, avisanos con 'Contactarme' en /start."
            )
            mark_reminded(user_id)
        except Exception as e:
            logger.warning("No se pudo avisar vencimiento próximo a %s: %s", user_id, e)

# ================= MAIN =================
def main():
    init_banned_words()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("activar", activar))
    app.add_handler(CommandHandler("restardias", restardias))
    app.add_handler(CommandHandler("desactivar", desactivar))
    app.add_handler(CommandHandler("diasrestantes", diasrestantes))
    app.add_handler(CommandHandler("listasuscriptores", listasuscriptores))
    app.add_handler(CommandHandler("pendientes", pendientes))
    app.add_handler(CommandHandler("estadisticas", estadisticas))
    app.add_handler(CommandHandler("backup", backup))
    app.add_handler(CommandHandler("avisar", avisar))
    app.add_handler(CommandHandler("revisarahora", revisarahora))
    app.add_handler(CommandHandler("addmod", addmod))
    app.add_handler(CommandHandler("removemod", removemod))
    app.add_handler(CommandHandler("ban", ban_cmd))
    app.add_handler(CommandHandler("unban", unban_cmd))
    app.add_handler(CommandHandler("kick", kick_cmd))
    app.add_handler(CommandHandler("mute", mute_cmd))
    app.add_handler(CommandHandler("unmute", unmute_cmd))
    app.add_handler(CommandHandler("resetavisos", resetavisos))
    app.add_handler(CommandHandler("agregarpalabra", agregarpalabra))
    app.add_handler(CommandHandler("quitarpalabra", quitarpalabra))
    app.add_handler(CommandHandler("listapalabras", listapalabras))

    app.add_handler(CallbackQueryHandler(button_handler))

    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, relay_message
    ))
    app.add_handler(MessageHandler(
        (filters.TEXT | filters.CAPTION) & ~filters.COMMAND & filters.ChatType.GROUPS, group_message_handler
    ))

    app.job_queue.run_repeating(check_expired, interval=3600, first=60)
    app.job_queue.run_repeating(check_expiring_soon, interval=3600 * 6, first=120)

    app.run_polling()

if __name__ == "__main__":
    main()
