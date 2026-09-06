from telegram import Update
from telegram.ext import ContextTypes

import database as db
import keyboards as kb
from config import (
    TEXTO_BIENVENIDA, TEXTO_INFORMACION, PLAN_PRECIO_USDT, PLAN_DIAS,
    PAYMENT_WALLET, PAYMENT_NETWORK, ADMIN_ID
)
from moderation import log


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.upsert_usuario_basico(user.id, user.username, user.first_name)
    texto = TEXTO_BIENVENIDA.format(nombre=user.first_name)
    await update.message.reply_text(texto, reply_markup=kb.menu_principal(user.id))


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    await query.answer()
    data = query.data

    if data == "menu_volver":
        await query.edit_message_text(
            TEXTO_BIENVENIDA.format(nombre=user.first_name),
            reply_markup=kb.menu_principal(user.id)
        )

    elif data == "menu_planes":
        if PAYMENT_WALLET:
            datos_pago = (
                f"Red: {PAYMENT_NETWORK or 'no especificada'}\n"
                f"Wallet (toca para copiar):\n<code>{PAYMENT_WALLET}</code>"
            )
        else:
            datos_pago = "Contacta al admin para los datos de pago"
        texto = (
            f"💳 <b>Plan disponible</b>\n\n"
            f"• Mensual — {PLAN_PRECIO_USDT} USDT ({PLAN_DIAS} días)\n\n"
            f"Datos de pago:\n{datos_pago}\n\n"
            f"Cuando hayas pagado, presiona <b>Ya pagué</b> y el admin activará tu acceso."
        )
        await query.edit_message_text(texto, reply_markup=kb.menu_planes(), parse_mode="HTML")

    elif data == "ya_pague":
        db.agregar_pago_pendiente(user.id, user.username or "")
        await query.edit_message_text(
            "✅ Listo, avisamos al admin. En cuanto confirme tu pago vas a recibir los "
            "botones para unirte al canal y al grupo.",
            reply_markup=kb.volver()
        )
        if ADMIN_ID:
            await context.bot.send_message(
                ADMIN_ID,
                f"💰 Nuevo aviso de pago\nUsuario: @{user.username or 'sin usuario'} (ID: {user.id})\n"
                f"Usa /activar {user.id} <dias> para activarlo."
            )

    elif data == "menu_perfil":
        dias = db.dias_restantes(user.id)
        row = db.get_usuario(user.id)
        if row and row["activo"] and dias > 0:
            texto = f"👤 *Tu perfil*\n\nSuscripción activa ✅\nTe quedan *{dias}* día(s)."
        else:
            texto = "👤 *Tu perfil*\n\nNo tienes una suscripción activa por el momento."
        await query.edit_message_text(texto, reply_markup=kb.volver(), parse_mode="Markdown")

    elif data == "menu_info":
        texto = db.get_texto("informacion", TEXTO_INFORMACION)
        await query.edit_message_text(texto, reply_markup=kb.volver())

    elif data == "menu_contacto":
        await query.edit_message_text(
            f"✉️ Puedes escribirle directamente al admin: tg://user?id={ADMIN_ID}\n\n"
            "(si el link no abre, busca su usuario de Telegram manualmente)",
            reply_markup=kb.volver()
        )

    elif data == "menu_admin":
        if user.id != ADMIN_ID:
            await query.answer("No tienes acceso a esto.", show_alert=True)
            return
        await query.edit_message_text("🛠️ Panel de administración:", reply_markup=kb.menu_admin())


async def setinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    texto = update.message.text.partition(" ")[2]
    if not texto:
        await update.message.reply_text("Uso: /setinfo <texto que verán los usuarios>")
        return
    db.set_texto("informacion", texto)
    await update.message.reply_text("✅ Texto de información actualizado.")


async def misdias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dias = db.dias_restantes(update.effective_user.id)
    if dias > 0:
        await update.message.reply_text(f"Te quedan {dias} día(s) de suscripción.")
    else:
        await update.message.reply_text("No tienes una suscripción activa.")
