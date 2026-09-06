from datetime import datetime, timedelta

from telegram import Update, ChatPermissions
from telegram.ext import ContextTypes

import database as db
import keyboards as kb
from config import ADMIN_ID, CHANNEL_ID, GROUP_ID
from moderation import log

COMANDOS_ADMIN = """🛠️ *Comandos de administración*

*Suscripciones*
/activar <user_id> <dias> — activa o suma días (genera y envía los links de unión)
/restar <user_id> <dias> — resta días a una suscripción
/estado <user_id> — ver días restantes y desde cuándo
/pendientes — lista de "ya pagué" sin activar
/revisar — fuerza la revisión de vencimientos ahora mismo
/aviso <mensaje> — envía un mensaje a todos los suscriptores activos

*Moderación*
/ban <user_id> — banea (expulsa permanentemente)
/unban <user_id> — quita el ban
/kick <user_id> — expulsa sin banear (puede volver a entrar)
/mute <user_id> <minutos> — silencia por tiempo definido
/unmute <user_id> — quita el silencio
/resetwarns <user_id> — resetea advertencias y nivel de mute

*Palabras prohibidas*
/agregarpalabra <palabra>
/quitarpalabra <palabra>
/listapalabras

*Rangos*
/ayudante <user_id> — asigna rango ayudante (modera, no maneja pagos)
/quitarayudante <user_id>

*Otros*
/setinfo <texto> — cambia el texto del botón "Información"
/backup — envía el archivo de la base de datos
/stats — estadísticas generales
"""


def solo_admin(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != ADMIN_ID:
            return
        return await func(update, context)
    return wrapper


def admin_o_ayudante(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        rango = db.get_rango(update.effective_user.id, ADMIN_ID)
        if rango not in ("admin", "ayudante"):
            return
        return await func(update, context)
    return wrapper


def _parse_args(text, n):
    partes = text.split()
    return partes[1:1 + n]


# ───────────────────────── SUSCRIPCIONES (solo admin, maneja dinero) ─────────────────────────

@solo_admin
async def activar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = _parse_args(update.message.text, 2)
    if len(args) < 2:
        await update.message.reply_text("Uso: /activar <user_id> <dias>")
        return
    user_id, dias = int(args[0]), int(args[1])
    nueva_fin = db.activar_dias(user_id, dias)

    link_canal = link_grupo = None
    try:
        if CHANNEL_ID:
            inv = await context.bot.create_chat_invite_link(CHANNEL_ID, creates_join_request=True)
            link_canal = inv.invite_link
        if GROUP_ID:
            inv = await context.bot.create_chat_invite_link(GROUP_ID, creates_join_request=True)
            link_grupo = inv.invite_link
    except Exception as e:
        await update.message.reply_text(f"⚠️ No pude generar los links automáticamente: {e}")

    await update.message.reply_text(
        f"✅ Usuario {user_id} activado hasta {nueva_fin.strftime('%Y-%m-%d %H:%M UTC')}."
    )

    try:
        texto_usuario = (
            "🎉 ¡Tu suscripción fue activada!\n\n"
            "Toca los botones para solicitar unirte. Tu ingreso se aprobará automáticamente."
        )
        await context.bot.send_message(
            user_id, texto_usuario, reply_markup=kb.botones_unirse(link_canal, link_grupo)
        )
    except Exception as e:
        await update.message.reply_text(f"⚠️ No pude enviarle el mensaje al usuario (¿bloqueó el bot?): {e}")

    await log(context, f"✅ {user_id} activado por {dias} día(s) — vence {nueva_fin.isoformat()}")


@solo_admin
async def restar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = _parse_args(update.message.text, 2)
    if len(args) < 2:
        await update.message.reply_text("Uso: /restar <user_id> <dias>")
        return
    user_id, dias = int(args[0]), int(args[1])
    nueva_fin = db.restar_dias(user_id, dias)
    if nueva_fin is None:
        await update.message.reply_text("Ese usuario no tiene suscripción registrada.")
        return
    await update.message.reply_text(f"✅ Ahora vence el {nueva_fin.strftime('%Y-%m-%d %H:%M UTC')}.")
    await log(context, f"➖ Se restaron {dias} día(s) a {user_id}")


@solo_admin
async def estado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = _parse_args(update.message.text, 1)
    if not args:
        await update.message.reply_text("Uso: /estado <user_id>")
        return
    user_id = int(args[0])
    row = db.get_usuario(user_id)
    if not row:
        await update.message.reply_text("Usuario no encontrado.")
        return
    dias = db.dias_restantes(user_id)
    desde = row["sub_inicio"] or "—"
    await update.message.reply_text(
        f"Usuario {user_id} (@{row['username']})\n"
        f"Activo: {'sí' if row['activo'] else 'no'}\n"
        f"Días restantes: {dias}\n"
        f"Suscrito desde: {desde}"
    )


@solo_admin
async def pendientes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    filas = db.listar_pagos_pendientes()
    if not filas:
        await update.message.reply_text("No hay pagos pendientes de activar.")
        return
    texto = "💰 *Pagos pendientes*\n\n" + "\n".join(
        f"• {r['user_id']} (@{r['username']}) — {r['solicitado'][:16]}" for r in filas
    )
    await update.message.reply_text(texto, parse_mode="Markdown")


@solo_admin
async def revisar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from jobs import revisar_vencimientos
    n = await revisar_vencimientos(context)
    await update.message.reply_text(f"✅ Revisión forzada completa. {n} usuario(s) procesados.")


@solo_admin
async def aviso(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mensaje = update.message.text.partition(" ")[2]
    if not mensaje:
        await update.message.reply_text("Uso: /aviso <mensaje>")
        return
    enviados = 0
    for u in db.usuarios_activos():
        try:
            await context.bot.send_message(u["user_id"], f"📢 {mensaje}")
            enviados += 1
        except Exception:
            pass
    await update.message.reply_text(f"✅ Enviado a {enviados} suscriptor(es) activo(s).")


# ───────────────────────── MODERACIÓN (admin o ayudante) ─────────────────────────

@admin_o_ayudante
async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = _parse_args(update.message.text, 1)
    if not args:
        await update.message.reply_text("Uso: /ban <user_id>")
        return
    user_id = int(args[0])
    if user_id == ADMIN_ID:
        await update.message.reply_text("No puedes banear al admin principal.")
        return
    for chat_id in (GROUP_ID, CHANNEL_ID):
        if chat_id:
            try:
                await context.bot.ban_chat_member(chat_id, user_id)
            except Exception:
                pass
    db.marcar_inactivo(user_id)
    await update.message.reply_text(f"🚫 Usuario {user_id} baneado.")
    await log(context, f"🚫 Ban a {user_id} por {update.effective_user.id}")


@admin_o_ayudante
async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = _parse_args(update.message.text, 1)
    if not args:
        await update.message.reply_text("Uso: /unban <user_id>")
        return
    user_id = int(args[0])
    for chat_id in (GROUP_ID, CHANNEL_ID):
        if chat_id:
            try:
                await context.bot.unban_chat_member(chat_id, user_id, only_if_banned=True)
            except Exception:
                pass
    await update.message.reply_text(f"✅ Usuario {user_id} desbaneado.")
    await log(context, f"✅ Unban a {user_id} por {update.effective_user.id}")


@admin_o_ayudante
async def kick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = _parse_args(update.message.text, 1)
    if not args:
        await update.message.reply_text("Uso: /kick <user_id>")
        return
    user_id = int(args[0])
    if user_id == ADMIN_ID:
        await update.message.reply_text("No puedes expulsar al admin principal.")
        return
    for chat_id in (GROUP_ID, CHANNEL_ID):
        if chat_id:
            try:
                await context.bot.ban_chat_member(chat_id, user_id)
                await context.bot.unban_chat_member(chat_id, user_id)
            except Exception:
                pass
    await update.message.reply_text(f"👢 Usuario {user_id} expulsado (puede volver a solicitar unirse).")
    await log(context, f"👢 Kick a {user_id} por {update.effective_user.id}")


@admin_o_ayudante
async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = _parse_args(update.message.text, 2)
    if len(args) < 2:
        await update.message.reply_text("Uso: /mute <user_id> <minutos>")
        return
    user_id, minutos = int(args[0]), int(args[1])
    if user_id == ADMIN_ID:
        await update.message.reply_text("No puedes mutear al admin principal.")
        return
    hasta = datetime.utcnow() + timedelta(minutes=minutos)
    try:
        await context.bot.restrict_chat_member(
            GROUP_ID, user_id, permissions=ChatPermissions(can_send_messages=False), until_date=hasta
        )
        await update.message.reply_text(f"🔇 Usuario {user_id} silenciado por {minutos} minuto(s).")
        await log(context, f"🔇 Mute manual a {user_id} por {minutos}min ({update.effective_user.id})")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


@admin_o_ayudante
async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = _parse_args(update.message.text, 1)
    if not args:
        await update.message.reply_text("Uso: /unmute <user_id>")
        return
    user_id = int(args[0])
    try:
        await context.bot.restrict_chat_member(
            GROUP_ID, user_id,
            permissions=ChatPermissions(
                can_send_messages=True, can_send_photos=True, can_send_videos=True,
                can_send_other_messages=True, can_add_web_page_previews=True
            )
        )
        await update.message.reply_text(f"🔊 Usuario {user_id} ya puede escribir de nuevo.")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


@admin_o_ayudante
async def resetwarns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = _parse_args(update.message.text, 1)
    if not args:
        await update.message.reply_text("Uso: /resetwarns <user_id>")
        return
    db.reset_warns(int(args[0]))
    await update.message.reply_text("✅ Advertencias y nivel de mute reseteados.")


# ───────────────────────── PALABRAS PROHIBIDAS ─────────────────────────

@admin_o_ayudante
async def agregarpalabra(update: Update, context: ContextTypes.DEFAULT_TYPE):
    palabra = update.message.text.partition(" ")[2].strip()
    if not palabra:
        await update.message.reply_text("Uso: /agregarpalabra <palabra>")
        return
    db.agregar_palabra(palabra)
    await update.message.reply_text(f"✅ '{palabra}' agregada al filtro.")


@admin_o_ayudante
async def quitarpalabra(update: Update, context: ContextTypes.DEFAULT_TYPE):
    palabra = update.message.text.partition(" ")[2].strip()
    if not palabra:
        await update.message.reply_text("Uso: /quitarpalabra <palabra>")
        return
    db.quitar_palabra(palabra)
    await update.message.reply_text(f"✅ '{palabra}' quitada del filtro.")


@admin_o_ayudante
async def listapalabras(update: Update, context: ContextTypes.DEFAULT_TYPE):
    palabras = db.listar_palabras()
    await update.message.reply_text(
        "Palabras filtradas:\n" + ", ".join(palabras) if palabras else "No hay palabras cargadas."
    )


# ───────────────────────── RANGOS ─────────────────────────

@solo_admin
async def ayudante(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = _parse_args(update.message.text, 1)
    if not args:
        await update.message.reply_text("Uso: /ayudante <user_id>")
        return
    db.set_rango(int(args[0]), "ayudante")
    await update.message.reply_text(f"✅ {args[0]} ahora es ayudante.")


@solo_admin
async def quitarayudante(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = _parse_args(update.message.text, 1)
    if not args:
        await update.message.reply_text("Uso: /quitarayudante <user_id>")
        return
    db.set_rango(int(args[0]), "miembro")
    await update.message.reply_text(f"✅ {args[0]} ya no es ayudante.")


# ───────────────────────── OTROS ─────────────────────────

@solo_admin
async def backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from config import DB_PATH
    try:
        await update.message.reply_document(open(DB_PATH, "rb"), filename="backup_bot.db")
    except Exception as e:
        await update.message.reply_text(f"Error al generar backup: {e}")


@solo_admin
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = db.estadisticas()
    await update.message.reply_text(
        f"📊 *Estadísticas*\n\n"
        f"Usuarios totales: {s['total']}\n"
        f"Activos: {s['activos']}\n"
        f"Vencidos: {s['vencidos']}\n"
        f"Pagos pendientes: {s['pendientes']}",
        parse_mode="Markdown"
    )


@solo_admin
async def comandos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(COMANDOS_ADMIN, parse_mode="Markdown")


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Botones del panel ADMIN (menu_admin)."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("No tienes acceso.", show_alert=True)
        return
    await query.answer()
    data = query.data

    if data == "admin_stats":
        s = db.estadisticas()
        await query.edit_message_text(
            f"📊 Totales: {s['total']} | Activos: {s['activos']} | "
            f"Vencidos: {s['vencidos']} | Pendientes: {s['pendientes']}",
            reply_markup=kb.menu_admin()
        )
    elif data == "admin_pendientes":
        filas = db.listar_pagos_pendientes()
        texto = "\n".join(f"• {r['user_id']} (@{r['username']})" for r in filas) or "Sin pendientes."
        await query.edit_message_text(f"💰 Pagos pendientes:\n{texto}", reply_markup=kb.menu_admin())
    elif data == "admin_revisar":
        from jobs import revisar_vencimientos
        n = await revisar_vencimientos(context)
        await query.edit_message_text(f"✅ Revisión completa ({n} procesados).", reply_markup=kb.menu_admin())
    elif data == "admin_comandos":
        await query.edit_message_text(COMANDOS_ADMIN, reply_markup=kb.menu_admin(), parse_mode="Markdown")
    elif data == "admin_backup":
        from config import DB_PATH
        await context.bot.send_document(ADMIN_ID, open(DB_PATH, "rb"), filename="backup_bot.db")
        await query.answer("Backup enviado por chat.")
