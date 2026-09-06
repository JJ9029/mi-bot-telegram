import re
import time
from datetime import datetime, timedelta
from collections import defaultdict

from telegram import ChatPermissions
from telegram.ext import ContextTypes

import database as db
from config import (
    ADMIN_ID, ADVERTENCIAS_ANTES_DE_MUTE, MUTE_BASE_DIAS,
    FLOOD_MAX_MENSAJES, FLOOD_VENTANA_SEGUNDOS,
    BLOQUEAR_MEDIA_NO_ADMIN, PERMITIR_MEDIA_DE_AYUDANTE, LOG_CHAT_ID
)

URL_REGEX = re.compile(r"(https?://|t\.me/|www\.)\S+", re.IGNORECASE)

# historial en memoria para detectar flood y mensajes repetidos
_historial_mensajes = defaultdict(list)   # user_id -> [(timestamp, texto)]
_nombres_conocidos = {}                    # user_id -> último nombre visto


async def log(context: ContextTypes.DEFAULT_TYPE, texto: str):
    if LOG_CHAT_ID:
        try:
            await context.bot.send_message(LOG_CHAT_ID, texto)
        except Exception:
            pass


def es_admin_o_ayudante(user_id):
    rango = db.get_rango(user_id, ADMIN_ID)
    return rango in ("admin", "ayudante")


async def aplicar_advertencia(update, context, motivo):
    user = update.effective_user
    chat = update.effective_chat
    warns = db.agregar_warn(user.id)

    if warns <= ADVERTENCIAS_ANTES_DE_MUTE:
        await context.bot.send_message(
            chat.id,
            f"⚠️ {user.mention_html()}, advertencia {warns}/{ADVERTENCIAS_ANTES_DE_MUTE + 1} — {motivo}",
            parse_mode="HTML"
        )
    else:
        nivel = db.subir_nivel_mute(user.id)
        dias_mute = MUTE_BASE_DIAS * (2 ** (nivel - 1))
        hasta = datetime.utcnow() + timedelta(days=dias_mute)
        try:
            await context.bot.restrict_chat_member(
                chat.id, user.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=hasta
            )
            await context.bot.send_message(
                chat.id,
                f"🔇 {user.mention_html()} fue silenciado por {dias_mute} día(s) — {motivo}",
                parse_mode="HTML"
            )
            await log(context, f"🔇 Mute a {user.id} (@{user.username}) por {dias_mute}d — {motivo}")
        except Exception as e:
            await log(context, f"Error aplicando mute a {user.id}: {e}")


async def filtrar_mensaje(update, context: ContextTypes.DEFAULT_TYPE):
    """Handler principal de moderación de grupo. Debe registrarse con group=1 (después de otros handlers)."""
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat

    if not msg or not user or user.is_bot:
        return
    if es_admin_o_ayudante(user.id):
        _detectar_cambio_nombre(user)
        return

    texto = (msg.text or msg.caption or "")

    # 1) Control de multimedia / archivos / documentos
    if BLOQUEAR_MEDIA_NO_ADMIN:
        es_media = any([msg.photo, msg.video, msg.document, msg.audio,
                        msg.voice, msg.video_note, msg.sticker, msg.animation])
        if es_media:
            try:
                await msg.delete()
            except Exception:
                pass
            aviso = await context.bot.send_message(
                chat.id,
                f"🗑️ {user.mention_html()}, no se permite enviar archivos/multimedia en este grupo.",
                parse_mode="HTML"
            )
            context.job_queue.run_once(
                lambda c: c.bot.delete_message(chat.id, aviso.message_id), 8
            )
            return

    # 2) Filtro de palabras prohibidas
    palabras = db.listar_palabras()
    texto_l = texto.lower()
    if palabras and any(p in texto_l for p in palabras):
        try:
            await msg.delete()
        except Exception:
            pass
        await aplicar_advertencia(update, context, "lenguaje no permitido")
        return

    # 3) Filtro de links
    if URL_REGEX.search(texto):
        try:
            await msg.delete()
        except Exception:
            pass
        await aplicar_advertencia(update, context, "no se permiten links")
        return

    # 4) Anti-flood / mensajes repetidos / exceso de mayúsculas
    ahora = time.time()
    historial = _historial_mensajes[user.id]
    historial.append((ahora, texto))
    _historial_mensajes[user.id] = [h for h in historial if ahora - h[0] <= FLOOD_VENTANA_SEGUNDOS]

    if len(_historial_mensajes[user.id]) > FLOOD_MAX_MENSAJES:
        await aplicar_advertencia(update, context, "flood (demasiados mensajes seguidos)")
        _historial_mensajes[user.id] = []
        return

    ultimos_textos = [h[1] for h in _historial_mensajes[user.id][-3:]]
    if len(ultimos_textos) == 3 and len(set(ultimos_textos)) == 1 and texto.strip():
        await aplicar_advertencia(update, context, "mensajes repetidos")
        return

    if len(texto) >= 10:
        mayus = sum(1 for c in texto if c.isupper())
        if mayus / len(texto) > 0.7:
            await aplicar_advertencia(update, context, "exceso de mayúsculas")
            return

    _detectar_cambio_nombre(user)


def _detectar_cambio_nombre(user):
    """Guarda el nombre visto; la comparación/aviso se hace en detectar_cambio_nombre_y_avisar."""
    pass


async def detectar_cambio_nombre_y_avisar(update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return
    nombre_actual = f"{user.first_name or ''} {user.last_name or ''}".strip()
    anterior = _nombres_conocidos.get(user.id)
    if anterior is not None and anterior != nombre_actual:
        await context.bot.send_message(
            update.effective_chat.id,
            f"✏️ Cambio de nombre detectado\nID: <code>{user.id}</code>\n"
            f"Antes: {anterior}\nAhora: {nombre_actual}",
            parse_mode="HTML"
        )
        await log(context, f"Cambio de nombre: {user.id} '{anterior}' → '{nombre_actual}'")
    _nombres_conocidos[user.id] = nombre_actual


async def borrar_mensajes_de_servicio(update, context: ContextTypes.DEFAULT_TYPE):
    """Borra los avisos automáticos de 'X se unió al grupo' para mantenerlo limpio."""
    msg = update.effective_message
    if msg and (msg.new_chat_members or msg.left_chat_member):
        try:
            await msg.delete()
        except Exception:
            pass
