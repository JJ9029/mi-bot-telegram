from telegram.ext import ContextTypes

import database as db
from config import CHANNEL_ID, GROUP_ID, AVISO_VENCIMIENTO_HORAS
from moderation import log


async def avisar_por_vencer(context: ContextTypes.DEFAULT_TYPE):
    for u in db.usuarios_por_vencer(AVISO_VENCIMIENTO_HORAS):
        try:
            await context.bot.send_message(
                u["user_id"],
                f"⏰ Tu suscripción vence en menos de {AVISO_VENCIMIENTO_HORAS} horas. "
                "Renueva desde /start para no perder el acceso."
            )
            db.marcar_aviso_enviado(u["user_id"])
        except Exception:
            pass


async def revisar_vencimientos(context: ContextTypes.DEFAULT_TYPE) -> int:
    vencidos = db.usuarios_vencidos()
    procesados = 0
    for u in vencidos:
        user_id = u["user_id"]
        for chat_id in (GROUP_ID, CHANNEL_ID):
            if chat_id:
                try:
                    await context.bot.ban_chat_member(chat_id, user_id)
                    await context.bot.unban_chat_member(chat_id, user_id)  # kick, no ban permanente
                except Exception:
                    pass
        db.marcar_inactivo(user_id)
        try:
            await context.bot.send_message(
                user_id, "⌛ Tu suscripción venció y fuiste removido del canal/grupo. "
                         "Usa /start para renovar cuando quieras."
            )
        except Exception:
            pass
        await log(context, f"⌛ Vencimiento procesado: {user_id}")
        procesados += 1
    return procesados


async def job_revisar_vencimientos(context: ContextTypes.DEFAULT_TYPE):
    await revisar_vencimientos(context)
