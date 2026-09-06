from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from config import PLAN_PRECIO_USDT, ADMIN_ID


def menu_principal(user_id):
    filas = [
        [InlineKeyboardButton("💳 Planes", callback_data="menu_planes")],
        [InlineKeyboardButton("👤 Mi perfil", callback_data="menu_perfil")],
        [InlineKeyboardButton("ℹ️ Información", callback_data="menu_info")],
        [InlineKeyboardButton("✉️ Contactarme", callback_data="menu_contacto")],
    ]
    if user_id == ADMIN_ID:
        filas.append([InlineKeyboardButton("🛠️ ADMIN", callback_data="menu_admin")])
    return InlineKeyboardMarkup(filas)


def menu_planes():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Plan mensual — {PLAN_PRECIO_USDT} USDT", callback_data="plan_mensual")],
        [InlineKeyboardButton("✅ Ya pagué", callback_data="ya_pague")],
        [InlineKeyboardButton("⬅️ Volver", callback_data="menu_volver")],
    ])


def volver():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Volver", callback_data="menu_volver")]])


def botones_unirse(link_canal, link_grupo):
    filas = []
    if link_canal:
        filas.append([InlineKeyboardButton("📢 Unirme al canal", url=link_canal)])
    if link_grupo:
        filas.append([InlineKeyboardButton("👥 Unirme al grupo", url=link_grupo)])
    return InlineKeyboardMarkup(filas) if filas else None


def menu_admin():
    filas = [
        [InlineKeyboardButton("📊 Estadísticas", callback_data="admin_stats")],
        [InlineKeyboardButton("💰 Pagos pendientes", callback_data="admin_pendientes")],
        [InlineKeyboardButton("⏰ Revisar vencimientos ahora", callback_data="admin_revisar")],
        [InlineKeyboardButton("📖 Ver comandos", callback_data="admin_comandos")],
        [InlineKeyboardButton("💾 Backup base de datos", callback_data="admin_backup")],
        [InlineKeyboardButton("⬅️ Volver", callback_data="menu_volver")],
    ]
    return InlineKeyboardMarkup(filas)
