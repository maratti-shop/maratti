import os
import json
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

BOT_TOKEN = os.environ.get('BOT_TOKEN', '')
OWNER_ID = int(os.environ.get('OWNER_ID', '1258838821'))
WEBAPP_URL = os.environ.get('WEBAPP_URL', 'https://maratti-shop.github.io/maratti')
USERS_FILE = 'users.json'

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

def load_users():
    try:
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def save_users(users):
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, ensure_ascii=False, indent=2)

def add_user(user):
    users = load_users()
    uid = str(user.id)
    is_new = uid not in users
    if is_new:
        users[uid] = {
            'id': user.id,
            'first_name': user.first_name or '',
            'username': user.username or '',
            'joined': datetime.now().strftime('%d.%m.%Y %H:%M')
        }
        save_users(users)
    return is_new

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    is_new = add_user(user)
    name = user.first_name or 'друг'

    keyboard = [
        [InlineKeyboardButton("🛍 Открыть магазин", web_app=WebAppInfo(url=WEBAPP_URL))],
        [InlineKeyboardButton("📞 Связаться с нами", url="https://t.me/+79894762089")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if is_new:
        text = (
            f"👋 Привет, {name}!\n\n"
            f"Добро пожаловать в *MARATTI* — премиум обувь из натуральной кожи 👞\n\n"
            f"🔥 *Почему покупают у нас:*\n"
            f"✅ Цены до 50% ниже Wildberries\n"
            f"✅ Натуральная кожа и замша\n"
            f"✅ Производство с 2006 года\n"
            f"✅ Доставка по всей России\n"
            f"✅ Рейтинг 4.8 ⭐\n\n"
            f"🎁 *Специально для тебя:*\n"
            f"Промокод *ИНСТА* — скидка *500 ₽* на первый заказ\\!\n\n"
            f"🚚 Бесплатная доставка от 5 000 ₽\n\n"
            f"👇 Нажми кнопку и выбирай свою пару\\!"
        )
        try:
            users = load_users()
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text=f"👤 Новый пользователь: {name} (@{user.username or 'нет'})\nВсего: {len(users)}"
            )
        except Exception:
            pass
    else:
        text = (
            f"👋 С возвращением, {name}\\!\n\n"
            f"👞 *MARATTI* — премиум обувь из натуральной кожи\n\n"
            f"💰 Скидки до −59% на весь каталог\n"
            f"🎁 Промокод *ИНСТА* — скидка *500 ₽*\n"
            f"🚚 Бесплатная доставка от 5 000 ₽\n\n"
            f"👇 Открывай магазин и выбирай\\!"
        )

    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='MarkdownV2')

async def promo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [[InlineKeyboardButton("🛍 Открыть магазин", web_app=WebAppInfo(url=WEBAPP_URL))]]
    await update.message.reply_text(
        "🎁 *Ваш промокод:*\n\nВведите код *ИНСТА* при оформлении заказа и получите скидку *500 ₽* 🔥\n\n👇 Открывай и применяй\\!",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='MarkdownV2'
    )

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Нет доступа")
        return
    if not context.args:
        await update.message.reply_text("📢 Использование:\n/broadcast Текст сообщения")
        return
    msg_text = ' '.join(context.args)
    users = load_users()
    keyboard = [[InlineKeyboardButton("🛍 Открыть магазин", web_app=WebAppInfo(url=WEBAPP_URL))]]
    success, fail = 0, 0
    await update.message.reply_text(f"⏳ Отправляю {len(users)} пользователям...")
    for uid in users:
        try:
            await context.bot.send_message(chat_id=int(uid), text=msg_text, reply_markup=InlineKeyboardMarkup(keyboard))
            success += 1
        except Exception:
            fail += 1
    await update.message.reply_text(f"✅ Готово!\n📤 Отправлено: {success}\n❌ Не доставлено: {fail}")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Нет доступа")
        return
    users = load_users()
    await update.message.reply_text(f"📊 Статистика MARATTI\n\n👥 Пользователей: {len(users)}\n📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [[InlineKeyboardButton("🛍 Открыть магазин", web_app=WebAppInfo(url=WEBAPP_URL))]]
    await update.message.reply_text(
        "📋 Команды:\n\n/start — Главное меню\n/promo — Промокод\n/help — Помощь\n\n📞 +7 (989) 476-20-89",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [[InlineKeyboardButton("🛍 Открыть магазин", web_app=WebAppInfo(url=WEBAPP_URL))]]
    await update.message.reply_text(
        "👞 Используй кнопку ниже чтобы открыть каталог!\n\nИли /help для списка команд.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

def main() -> None:
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("promo", promo))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Bot started!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
