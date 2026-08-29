import telebot
import os
import random
import logging
import requests
import json
import re
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# ========== CONFIGURACIÓN ==========
TOKEN = "8763097493:AAFE44w626cXlPTVDuF2b4NYUCSRhr92w6o"  # REEMPLAZA CON TU TOKEN

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========== BASE DE DATOS DE BINS COMUNES (PARA DEMOSTRACIÓN) ==========
BINS_DB = {
    "405988": {"banco": "Visa", "pais": "EE.UU.", "tipo": "Crédito", "nivel": "Clásica"},
    "411111": {"banco": "Visa", "pais": "EE.UU.", "tipo": "Crédito", "nivel": "Gold"},
    "422222": {"banco": "Visa", "pais": "Brasil", "tipo": "Crédito", "nivel": "Platinum"},
    "444444": {"banco": "Mastercard", "pais": "EE.UU.", "tipo": "Crédito", "nivel": "Gold"},
    "450000": {"banco": "Mastercard", "pais": "México", "tipo": "Débito", "nivel": "Standard"},
    "510000": {"banco": "Mastercard", "pais": "Brasil", "tipo": "Crédito", "nivel": "Gold"},
    "530000": {"banco": "Mastercard", "pais": "Colombia", "tipo": "Crédito", "nivel": "Platinum"},
    "550000": {"banco": "Mastercard", "pais": "Argentina", "tipo": "Crédito", "nivel": "Black"},
    "601100": {"banco": "Discover", "pais": "EE.UU.", "tipo": "Crédito", "nivel": "Classic"},
    "340000": {"banco": "American Express", "pais": "EE.UU.", "tipo": "Crédito", "nivel": "Gold"},
    "370000": {"banco": "American Express", "pais": "EE.UU.", "tipo": "Crédito", "nivel": "Platinum"},
    "301000": {"banco": "Diners Club", "pais": "Internacional", "tipo": "Crédito", "nivel": "Classic"},
    "654000": {"banco": "Hipercard", "pais": "Brasil", "tipo": "Crédito", "nivel": "Standard"},
    "606282": {"banco": "Elo", "pais": "Brasil", "tipo": "Débito", "nivel": "Standard"},
}

# ========== ALGORITMO LUHN ==========
def luhn_generate(partial):
    """Genera dígito de control Luhn"""
    total = 0
    for i, digit in enumerate(reversed(partial)):
        n = int(digit)
        if i % 2 == 0:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    check_digit = (10 - (total % 10)) % 10
    return str(check_digit)

def luhn_validate(number):
    """Valida número completo con Luhn"""
    try:
        return luhn_generate(number[:-1]) == number[-1] and len(number) >= 15
    except:
        return False

def generate_card(bin_prefix, length=16):
    """Genera tarjeta sintética válida"""
    if len(bin_prefix) > 6:
        bin_prefix = bin_prefix[:6]
    
    # Generar números aleatorios hasta el penúltimo dígito
    while len(bin_prefix) < length - 1:
        bin_prefix += str(random.randint(0, 9))
    
    # Agregar dígito de control
    check = luhn_generate(bin_prefix)
    number = bin_prefix + check
    
    # Fecha de expiración (1-4 años futuro)
    now = datetime.now()
    month = random.randint(1, 12)
    year = now.year + random.randint(1, 4)
    
    # CVV
    cvv = f"{random.randint(100, 999)}"
    
    return {
        "number": number,
        "month": str(month).zfill(2),
        "year": str(year),
        "cvv": cvv
    }

def get_bin_info(bin_prefix):
    """Obtiene información del BIN (local + API)"""
    bin_prefix = bin_prefix[:6]
    
    # Buscar en DB local primero
    if bin_prefix in BINS_DB:
        return BINS_DB[bin_prefix]
    
    # Intentar API externa
    try:
        url = f"https://lookup.binlist.net/{bin_prefix}"
        response = requests.get(url, timeout=3)
        if response.status_code == 200:
            data = response.json()
            return {
                "banco": data.get("bank", {}).get("name", "Desconocido"),
                "pais": data.get("country", {}).get("name", "Desconocido"),
                "tipo": data.get("type", "Desconocido"),
                "nivel": data.get("scheme", "Desconocido")
            }
    except:
        pass
    
    return {"banco": "Desconocido", "pais": "Desconocido", "tipo": "Desconocido", "nivel": "Desconocido"}

# ========== COMANDOS PRINCIPALES ==========

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mensaje de bienvenida profesional estilo carding"""
    welcome = """
╔══════════════════════════════════════╗
║         💳  LUHN VALIDATION BOT     ║
╠══════════════════════════════════════╣
║  [ SISTEMA DE VALIDACIÓN AVANZADO ] ║
╚══════════════════════════════════════╝

🔹 *Sistema de generación y validación de tarjetas*
🔹 *Algoritmo Luhn + Base de datos BIN* 
🔹 *Uso exclusivamente educativo*

📌 *COMANDOS DISPONIBLES:*

┌─────────────────────────────────────┐
│  /gen [BIN]   → Generar tarjetas   │
│  /bin [BIN]   → Info del banco     │
│  /check [NUM] → Validar tarjeta    │
│  /help        → Ayuda detallada    │
│  /about       → Sobre este bot     │
└─────────────────────────────────────┘

⚠️ *ADVERTENCIA:* 
Este bot es para fines académicos. 
El uso de tarjetas robadas es DELITO.
    """
    await update.message.reply_text(welcome, parse_mode='Markdown')

async def generate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Genera tarjetas sintéticas con formato profesional"""
    if not context.args:
        await update.message.reply_text(
            "❌ *Uso correcto:* `/gen 405988`\n"
            "📌 Ejemplo: `/gen 411111`",
            parse_mode='Markdown'
        )
        return
    
    bin_input = context.args[0][:6]
    if not bin_input.isdigit():
        await update.message.reply_text("❌ *Error:* El BIN debe contener solo números.", parse_mode='Markdown')
        return
    
    # Consultar info del BIN
    bin_info = get_bin_info(bin_input)
    
    # Generar 5 tarjetas
    cards = []
    for i in range(5):
        card = generate_card(bin_input)
        cards.append(card)
    
    # Mensaje con formato profesional
    response = f"""
╔══════════════════════════════════════╗
║     💳  TARJETAS GENERADAS          ║
╠══════════════════════════════════════╣
║  📌 BIN: `{bin_input}`               ║
║  🏦 Banco: {bin_info['banco']}       ║
║  🌍 País: {bin_info['pais']}         ║
║  📊 Tipo: {bin_info['tipo']}         ║
║  🔱 Nivel: {bin_info['nivel']}       ║
╚══════════════════════════════════════╝

"""
    for i, card in enumerate(cards, 1):
        response += f"""
┌─────────────────────────────────────┐
│  💳 *Card {i}*                       │
│  📱 `{card['number']}`              │
│  📅 {card['month']}/{card['year']}  │
│  🔒 CVV: {card['cvv']}             │
└─────────────────────────────────────┘
"""
    
    response += """
╔══════════════════════════════════════╗
║  ⚠️  VALIDACIÓN SINTÁCTICA          ║
║  ✅ Pasa algoritmo Luhn              ║
║  ❌ NO son tarjetas reales           ║
╚══════════════════════════════════════╝
"""
    
    await update.message.reply_text(response, parse_mode='Markdown')

async def bin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Consulta información detallada de un BIN"""
    if not context.args:
        await update.message.reply_text(
            "❌ *Uso correcto:* `/bin 405988`",
            parse_mode='Markdown'
        )
        return
    
    bin_input = context.args[0][:6]
    if not bin_input.isdigit():
        await update.message.reply_text("❌ *Error:* El BIN debe contener solo números.", parse_mode='Markdown')
        return
    
    info = get_bin_info(bin_input)
    
    response = f"""
╔══════════════════════════════════════╗
║     🔍  CONSULTA DE BIN             ║
╠══════════════════════════════════════╣
║  📌 BIN: `{bin_input}`               ║
║  🏦 Banco: {info['banco']}           ║
║  🌍 País: {info['pais']}             ║
║  💳 Tipo: {info['tipo']}             ║
║  ⭐ Nivel: {info['nivel']}           ║
╚══════════════════════════════════════╝

💡 *¿Qué es un BIN?*
Los primeros 6 dígitos identifican al banco emisor.

📊 *Usos legítimos:*
- Pruebas de sistemas de pago
- Investigación de seguridad
- Desarrollo de e-commerce

⚠️ *Usos ilegales (DELITO):*
- Carding
- Fraude financiero
- Compra de datos robados
"""
    await update.message.reply_text(response, parse_mode='Markdown')

async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Valida una tarjeta completa"""
    if not context.args:
        await update.message.reply_text(
            "❌ *Uso correcto:* `/check 4111111111111111`",
            parse_mode='Markdown'
        )
        return
    
    number = context.args[0].strip()
    if not number.isdigit() or len(number) < 15:
        await update.message.reply_text(
            "❌ *Error:* Número inválido. Mínimo 15 dígitos.",
            parse_mode='Markdown'
        )
        return
    
    is_valid = luhn_validate(number)
    
    # Obtener BIN del número
    bin_info = get_bin_info(number[:6])
    
    status = "✅ PASÓ" if is_valid else "❌ NO PASÓ"
    icon = "✅" if is_valid else "❌"
    
    response = f"""
╔══════════════════════════════════════╗
║     🔎  VALIDACIÓN DE TARJETA       ║
╠══════════════════════════════════════╣
║  💳 Número: `{number}`              ║
║  📊 Status: {icon} {status}         ║
║  🏦 Banco: {bin_info['banco']}      ║
║  🌍 País: {bin_info['pais']}        ║
╚══════════════════════════════════════╝

📌 *Algoritmo de Luhn:*
{icon} El número {'PASA' if is_valid else 'NO PASA'} el checksum.
"""
    await update.message.reply_text(response, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ayuda detallada"""
    help_text = """
╔══════════════════════════════════════╗
║        📖  GUÍA DE COMANDOS         ║
╠══════════════════════════════════════╣
║                                      ║
║  /gen [6 dígitos]                   ║
║  → Genera 5 tarjetas con ese BIN    ║
║  Ej: /gen 405988                    ║
║                                      ║
║  /bin [6 dígitos]                   ║
║  → Muestra info del banco           ║
║  Ej: /bin 405988                    ║
║                                      ║
║  /check [15-16 dígitos]             ║
║  → Valida número con Luhn           ║
║  Ej: /check 4111111111111111        ║
║                                      ║
║  /help                              ║
║  → Muestra esta ayuda               ║
║                                      ║
║  /about                             ║
║  → Información del bot              ║
╚══════════════════════════════════════╝

🔬 *¿Cómo funciona?*
Usa el algoritmo de Luhn, un checksum matemático que detecta errores en números de tarjetas. No crea tarjetas reales, solo números sintácticamente válidos.

⚖️ *MARCO LEGAL:*
Este bot es para investigación y educación. El carding es un DELITO grave con penas de prisión.
"""
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Información del bot"""
    about = """
╔══════════════════════════════════════╗
║        ℹ️  SOBRE ESTE BOT            ║
╠══════════════════════════════════════╣
║                                      ║
║  🤖 Bot: @luhn_validation_bot      ║
║  📚 Versión: 2.0                    ║
║  🎯 Propósito: Educativo            ║
║  🔐 Seguridad: Demostración         ║
║                                      ║
║  *Desarrollado para:*               ║
║  Tarea de Seguridad Informática     ║
║                                      ║
║  *Tecnologías usadas:*              ║
║  - Python 3.10                      ║
║  - Algoritmo Luhn                   ║
║  - Base de datos BIN                ║
║  - API pública (binlist.net)        ║
║                                      ║
║  *NO APOYAMOS EL CARDING*           ║
║  ⚠️ Es un delito en todo el mundo   ║
╚══════════════════════════════════════╝
"""
    await update.message.reply_text(about, parse_mode='Markdown')

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja comandos no reconocidos"""
    await update.message.reply_text(
        "❌ *Comando no reconocido*\n"
        "Escribe `/help` para ver los comandos disponibles.",
        parse_mode='Markdown'
    )

# ========== MAIN ==========
def main():
    print("╔══════════════════════════════════════╗")
    print("║     💳 LUHN VALIDATION BOT          ║")
    print("║     🚀 Iniciando sistema...         ║")
    print("╚══════════════════════════════════════╝")
    
    app = Application.builder().token(TOKEN).build()
    
    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("gen", generate_command))
    app.add_handler(CommandHandler("bin", bin_command))
    app.add_handler(CommandHandler("check", check_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("about", about_command))
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command))
    
    print("✅ Bot en ejecución...")
    app.run_polling()

if __name__ == "__main__":
    main()
