from telegram import Update
from telegram.ext import ContextTypes

import database as db
from config import CHANNEL_ID, GROUP_ID
from moderation import log


async def manejar_solicitud_union(update: Update, context: ContextTypes.DEFAULT_TYPE):
    solicitud = update.chat_join_request
    user = solicitud.from_user
    chat = solicitud.chat

    dias = db.dias_restantes(user.id)
    row = db.get_usuario(user.id)
    activo = bool(row and row["activo"] and dias > 0)

    if activo:
        await solicitud.approve()
        if chat.id == CHANNEL_ID:
            db.marcar_membresia(user.id, canal=True)
        elif chat.id == GROUP_ID:
            db.marcar_membresia(user.id, grupo=True)
        await log(context, f"✅ Solicitud de {user.id} (@{user.username}) aprobada en {chat.title}")
        try:
            await context.bot.send_message(
                user.id, f"✅ Tu solicitud para unirte a *{chat.title}* fue aprobada.", parse_mode="Markdown"
            )
        except Exception:
            pass
    else:
        await solicitud.decline()
        await log(context, f"❌ Solicitud de {user.id} (@{user.username}) rechazada en {chat.title} (sin suscripción activa)")
        try:
            await context.bot.send_message(
                user.id,
                f"❌ No pude aprobar tu solicitud a *{chat.title}* porque no tienes una suscripción activa. "
                "Usa /start para ver los planes.",
                parse_mode="Markdown"
            )
        except Exception:
            pass
