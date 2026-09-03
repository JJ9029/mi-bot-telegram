# Bot de suscripciones (USDT vía CryptoBot)

## Qué hace
- `/start` → mensaje de bienvenida con menú: **Suscribirme (10 USDT/mes)** y **Contactarme**.
- Al pagar (CryptoBot), agrega automáticamente al canal y grupo con un link de invitación de un solo uso.
- Cada hora revisa vencimientos y expulsa automáticamente a quien no renovó (el admin nunca es expulsado).
- **Contactarme**: el usuario escribe, el mensaje te llega a vos por el bot; respondés citando (reply) ese mensaje y le llega al usuario. Ambos tienen botón "Cerrar conversación".
- `/addmod <user_id>`: solo vos podés darle rango de ayudante (permisos limitados, no puede sacarte ni dar más rangos).
- `/removemod <user_id>`: le quita el rango.

## 1. Obtené los datos necesarios

| Dato | Cómo conseguirlo |
|---|---|
| `BOT_TOKEN` | Ya lo tenés de BotFather |
| `ADMIN_ID` | Hablale a @userinfobot, te da tu ID numérico |
| `CHANNEL_ID` | Agregá @userinfobot como admin temporal a tu canal, o reenviá un mensaje del canal a @getidsbot |
| `GROUP_ID` | Igual que arriba pero con el grupo |
| `CRYPTOPAY_TOKEN` | Abrí @CryptoBot → menú → **Crypto Pay** → **Create App** → te da el API Token |

Asegurate de que tu bot sea **administrador** en el canal y en el grupo, con permisos de:
- Invitar usuarios (para generar los links)
- Restringir/expulsar usuarios (para sacarlos al vencer)
- Promover miembros (para poder usar `/addmod`)

## 2. Subir a Railway

1. Creá cuenta en https://railway.app (gratis para empezar).
2. "New Project" → "Deploy from GitHub repo" (subí estos archivos a un repo), o "Empty Project" y arrastrá los archivos.
3. En **Variables**, cargá todas las de `.env.example` con tus valores reales.
4. Railway va a detectar `requirements.txt` y correr `python bot.py` automáticamente. Si no, configurá el **Start Command** como:
   ```
   python bot.py
   ```
5. Listo — el bot queda corriendo 24/7.

## 3. Probarlo
- Hablale a tu bot con `/start`.
- Tocá "Suscribirme", pagá con un usuario de prueba, y verificá que te agregue al canal/grupo.
- Esperá a que expire (o cambiá manualmente la fecha en la base para probar) y confirmá que lo expulsa.

## Notas importantes
- El campo `expires_at` se guarda en `subs.db` (SQLite). Railway borra el sistema de archivos en cada redeploy — si querés persistencia real a largo plazo, después podemos migrar a una base externa (ej. Railway Postgres, gratis también).
- Los pagos se verifican cuando el usuario toca "Ya pagué / Verificar" (no hace falta configurar webhooks).
- Si querés cambiar el precio, solo editá la variable `PRICE_USDT` en Railway (no hace falta tocar el código).
