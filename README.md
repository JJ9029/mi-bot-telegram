# 🤖 Bot de Suscripciones — Edición Completa

Bot de Telegram para gestionar el acceso pago a tu canal y grupo: suscripciones manuales en USDT,
ingreso controlado por **solicitud de unión** (sin links reutilizables), moderación automática
completa y panel de administración.

## ✨ Funciones incluidas

**Suscripciones**
- Activación manual por admin (`/activar`), sumando días si ya tenía (nunca se pisan)
- Resta de días (`/restar`), consulta de estado (`/estado`)
- Botón "Ya pagué" → avisa al admin automáticamente
- Aviso automático al usuario cuando le queda menos de 24h
- Expulsión automática (kick, no ban) al vencer, revisada cada 30 min
- Botón "Mi perfil" con días restantes

**Ingreso al canal/grupo (sin links reutilizables)**
- Al activar a alguien, el bot genera links de invitación en **modo solicitud de unión**
  y se los manda como botones ("Unirme al canal" / "Unirme al grupo")
- El bot aprueba automáticamente la solicitud solo si la persona tiene suscripción activa
- Si alguien reenvía el link, da igual: cada solicitud se valida individualmente

**Moderación de grupo**
- Filtro de palabras prohibidas (editable con comandos)
- Filtro de links (borra y advierte)
- Anti-flood y mensajes repetidos
- Filtro de exceso de mayúsculas
- Bloqueo total de archivos/fotos/videos/documentos/stickers/audio de usuarios normales
- Sistema de advertencias: 2 avisos, a la 3ra infracción mute de 1 día, luego se duplica (1,2,4,8...)
- Detección de cambio de nombre (avisa ID + nombre anterior/nuevo)
- Borra automáticamente los mensajes de "fulano se unió/salió" para mantener el grupo limpio

**Panel admin**
- Botón "🛠️ ADMIN" visible solo para ti, con estadísticas, pendientes, backup y lista de comandos
- Sistema de rangos: admin (protegido, no lo puede tocar nadie) / ayudante (modera, no maneja pagos) / miembro
- `/backup` para descargar la base de datos en cualquier momento
- `/stats`, `/aviso` (mensaje masivo a activos), `/revisar` (forzar chequeo de vencidos)

## ⚙️ Configuración (variables de entorno)

| Variable | Descripción |
|---|---|
| `BOT_TOKEN` | Token que te dio @BotFather |
| `ADMIN_ID` | Tu user_id de Telegram (usa @userinfobot para obtenerlo) |
| `CHANNEL_ID` | ID de tu canal (ej: `-1001234567890`) |
| `GROUP_ID` | ID de tu grupo |
| `LOG_CHAT_ID` | (Opcional) chat/canal privado donde el bot registra sus acciones |
| `PLAN_PRECIO_USDT` | Precio del plan mensual (default `10`) |
| `WALLET_INFO` | Texto con tus datos de pago (wallet, red, etc) |

## 🚀 Pasos para poner el bot a funcionar

1. **Crea el bot** en @BotFather (ya lo tienes) y copia el token.
2. **Agrega el bot como administrador** en tu canal y en tu grupo, con estos permisos:
   - Invitar usuarios mediante link
   - Eliminar mensajes
   - Restringir/silenciar miembros
   - Banear usuarios
   - Agregar nuevos administradores (no es necesario, pero no molesta)
3. **Activa "Aprobar nuevos miembros"** en la configuración de enlaces de invitación del
   canal y del grupo (Ajustes → Miembros/Enlaces de invitación → "Solicitudes de unión").
   Esto es lo que hace posible el flujo de aprobación automática.
4. Obtén los IDs del canal y grupo (reenvía un mensaje de cada uno a @userinfobot o @RawDataBot).
5. Sube esta carpeta a **Railway** (o cualquier host que soporte `worker` de Python):
   - Configura las variables de entorno de la tabla de arriba
   - Railway detectará el `Procfile` y correrá `python bot.py`
6. Escríbele `/start` al bot para probar el menú.

## 🗂️ Estructura del proyecto

```
bot.py                 → arranque y registro de handlers
config.py               → variables de entorno y constantes editables
database.py             → toda la capa de SQLite
keyboards.py            → teclados inline
moderation.py           → filtros de grupo (palabras, links, flood, media)
jobs.py                 → tareas programadas (avisos y vencimientos)
handlers_usuario.py     → /start, menú, planes, perfil
handlers_admin.py       → comandos de administración y moderación manual
handlers_join.py        → aprobación/rechazo de solicitudes de unión
requirements.txt
Procfile
data/bot.db             → se crea solo al arrancar (SQLite)
```

## 📋 Lista completa de comandos de admin

Disponible en cualquier momento con `/comandos` o desde el botón ADMIN → "Ver comandos".

## 🔒 Notas de seguridad

- El `ADMIN_ID` está protegido en el código: nadie puede banearlo, mutearlo ni expulsarlo,
  ni siquiera con los comandos de moderación.
- Los "ayudantes" pueden moderar (ban/mute/palabras) pero **no** pueden activar/restar
  suscripciones ni ver el panel ADMIN — eso queda reservado solo para ti.
- Haz backups periódicos con `/backup`; la base de datos vive en `data/bot.db` y en Railway
  el sistema de archivos no es 100% persistente entre redeploys si no usas un volumen.
  Se recomienda agregar un **Volume** en Railway apuntando a `/app/data` para no perder la DB.

## 💡 Ideas para seguir mejorando (no incluidas todavía)

- Migrar la base de datos a PostgreSQL si el volumen de usuarios crece mucho
- Exportar la lista de suscriptores activos a un archivo CSV
- Pasarela de pago automática (CryptoBot) si en algún momento quieres dejar de activar manualmente
- Captcha adicional al aprobar la solicitud (pregunta simple antes de dejar pasar)
