import os

# ── Credenciales y IDs (se configuran como variables de entorno en Railway) ──
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))          # tu user_id de Telegram (dueño, protegido siempre)
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "0"))       # id del canal (ej: -1001234567890)
GROUP_ID = int(os.environ.get("GROUP_ID", "0"))           # id del grupo
LOG_CHAT_ID = int(os.environ.get("LOG_CHAT_ID", "0"))     # chat/canal privado donde el bot registra sus acciones (opcional, 0 = desactivado)

# ── Suscripción ──
PLAN_PRECIO_USDT = os.environ.get("PLAN_PRECIO_USDT", "10")
PLAN_DIAS = 30
WALLET_INFO = os.environ.get("WALLET_INFO", "Contacta al admin para los datos de pago")
AVISO_VENCIMIENTO_HORAS = 24  # avisar al usuario cuando le queden <= 24h

# ── Moderación ──
ADVERTENCIAS_ANTES_DE_MUTE = 2      # a la 3ra infracción ya se aplica mute
MUTE_BASE_DIAS = 1                   # 1er mute = 1 día, luego se duplica (1,2,4,8...)
FLOOD_MAX_MENSAJES = 6                # más de N mensajes...
FLOOD_VENTANA_SEGUNDOS = 8            # ...en N segundos = flood
BLOQUEAR_MEDIA_NO_ADMIN = True        # borra fotos/videos/documentos/audios/stickers/GIF de no-admins
PERMITIR_MEDIA_DE_AYUDANTE = True     # el ayudante sí puede mandar media

# ── Base de datos ──
DB_PATH = os.environ.get("DB_PATH", "data/bot.db")

# ── Textos ──
TEXTO_BIENVENIDA = (
    "👋 ¡Hola {nombre}!\n\n"
    "Este es el bot de suscripciones. Desde aquí puedes:\n"
    "• Ver los planes disponibles\n"
    "• Consultar tu suscripción\n"
    "• Contactar al admin\n\n"
    "Elige una opción:"
)

TEXTO_INFORMACION = (
    "ℹ️ Escribe aquí la información que quieras mostrarle a tus usuarios "
    "(reglas, beneficios, contenido del canal, etc). Puedes cambiar este texto "
    "con el comando /setinfo."
)
