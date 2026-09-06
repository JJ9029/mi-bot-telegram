import logging

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ChatJoinRequestHandler, filters
)

from config import BOT_TOKEN
import database as db
import handlers_usuario as hu
import handlers_admin as ha
from handlers_join import manejar_solicitud_union
from moderation import filtrar_mensaje, detectar_cambio_nombre_y_avisar, borrar_mensajes_de_servicio
from jobs import avisar_por_vencer, job_revisar_vencimientos

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)


def main():
    if not BOT_TOKEN:
        raise SystemExit("Falta configurar BOT_TOKEN como variable de entorno.")

    db.init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    # ── Usuario ──
    app.add_handler(CommandHandler("start", hu.start))
    app.add_handler(CommandHandler("misdias", hu.misdias))
    app.add_handler(CommandHandler("setinfo", hu.setinfo))
    app.add_handler(CallbackQueryHandler(
        hu.menu_callback,
        pattern="^(menu_|ya_pague|plan_)"
    ))

    # ── Admin: suscripciones ──
    app.add_handler(CommandHandler("activar", ha.activar))
    app.add_handler(CommandHandler("restar", ha.restar))
    app.add_handler(CommandHandler("estado", ha.estado))
    app.add_handler(CommandHandler("pendientes", ha.pendientes))
    app.add_handler(CommandHandler("revisar", ha.revisar))
    app.add_handler(CommandHandler("aviso", ha.aviso))

    # ── Admin: moderación ──
    app.add_handler(CommandHandler("ban", ha.ban))
    app.add_handler(CommandHandler("unban", ha.unban))
    app.add_handler(CommandHandler("kick", ha.kick))
    app.add_handler(CommandHandler("mute", ha.mute))
    app.add_handler(CommandHandler("unmute", ha.unmute))
    app.add_handler(CommandHandler("resetwarns", ha.resetwarns))
    app.add_handler(CommandHandler("agregarpalabra", ha.agregarpalabra))
    app.add_handler(CommandHandler("quitarpalabra", ha.quitarpalabra))
    app.add_handler(CommandHandler("listapalabras", ha.listapalabras))

    # ── Admin: rangos y utilidades ──
    app.add_handler(CommandHandler("ayudante", ha.ayudante))
    app.add_handler(CommandHandler("quitarayudante", ha.quitarayudante))
    app.add_handler(CommandHandler("backup", ha.backup))
    app.add_handler(CommandHandler("stats", ha.stats))
    app.add_handler(CommandHandler("comandos", ha.comandos))
    app.add_handler(CallbackQueryHandler(ha.admin_callback, pattern="^admin_"))

    # ── Solicitudes de unión (canal y grupo) ──
    app.add_handler(ChatJoinRequestHandler(manejar_solicitud_union))

    # ── Moderación de grupo (mensajes normales) ──
    app.add_handler(MessageHandler(
        filters.ChatType.GROUPS & ~filters.COMMAND, filtrar_mensaje
    ), group=1)
    app.add_handler(MessageHandler(
        filters.ChatType.GROUPS & ~filters.COMMAND, detectar_cambio_nombre_y_avisar
    ), group=2)
    app.add_handler(MessageHandler(
        filters.StatusUpdate.NEW_CHAT_MEMBERS | filters.StatusUpdate.LEFT_CHAT_MEMBER,
        borrar_mensajes_de_servicio
    ), group=0)

    # ── Tareas programadas ──
    app.job_queue.run_repeating(avisar_por_vencer, interval=3600, first=60)         # cada hora
    app.job_queue.run_repeating(job_revisar_vencimientos, interval=1800, first=120)  # cada 30 min

    print("Bot corriendo...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
