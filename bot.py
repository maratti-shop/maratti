import os
import json
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

# Настройки
BOT_TOKEN = os.environ.get('BOT_TOKEN', '')
OWNER_ID = int(os.environ.get('OWNER_ID', '1258838821'))
WEBAPP_URL = os.environ.get('WEBAPP_URL', 'https://maratti-shop.github.io/maratti')
USERS_FILE = 'users.json'

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── БАЗА ПОЛЬЗОВАТЕЛЕЙ ──
def load_users():
    try:
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except:
        pass
    return {}

def save_users(users):
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, ensure_ascii=False, indent=2)

def add_user(user):
    users = load_users()
    uid = str(user.id)
    if uid not in users:
        users[uid] = {
            'id': user.id,
            'first_name': user.first_name or '',
            'last_name': user.last_name or '',
            'username': user.username or '',
            'joined': datetime.now().strftime('%d.%m.%Y %H:%M'),
            'orders': 0
        }
        save_users(users)
        return True  # новый пользователь
    return False  # уже есть

# ── /start ──
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    is_new = add_user(user)
    name = user.first_name or 'друг'

    # Кнопки
    keyboard = [
        [InlineKeyboardButton("🛍 Открыть магазин", web_app=WebAppInfo(url=WEBAPP_URL))],
        [InlineKeyboardButton("📢 Акции и новинки", url="https://t.me/maratti_official")],
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
            f"✅ Рейтинг 4.8 ⭐ на WB\n\n"
            f"🎁 *Специально для тебя:*\n"
            f"Промокод *ИНСТА* — скидка *500 ₽* на первый заказ!\n\n"
            f"🚚 Бесплатная доставка от 5 000 ₽\n\n"
            f"👇 Нажми кнопку и выбирай свою пару!"
        )
        # Уведомляем владельца о новом пользователе
        await context.bot.send_message(
            chat_id=OWNER_ID,
            text=f"👤 Новый пользователь!\n{name} (@{user.username or 'нет'}) открыл бота\nВсего пользователей: {len(load_users())}"
        )
    else:
        text = (
            f"👋 С возвращением, {name}!\n\n"
            f"👞 *MARATTI* — премиум обувь из натуральной кожи\n\n"
            f"💰 Скидки до −59% на весь каталог\n"
            f"🎁 Промокод *ИНСТА* — скидка *500 ₽*\n"
            f"🚚 Бесплатная доставка от 5 000 ₽\n\n"
            f"👇 Открывай магазин и выбирай!"
        )

    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

# ── /broadcast — рассылка (только для владельца) ──
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Нет доступа")
        return

    if not context.args:
        await update.message.reply_text(
            "📢 Чтобы сделать рассылку:\n"
            "/broadcast Текст сообщения\n\n"
            "Например:\n"
            "/broadcast 🔥 Новая коллекция уже в магазине! Скидки до 50%"
        )
        return

    msg_text = ' '.join(context.args)
    users = load_users()
    total = len(users)
    success = 0
    fail = 0

    await update.message.reply_text(f"⏳ Отправляю рассылку {total} пользователям...")

    keyboard = [[InlineKeyboardButton("🛍 Открыть магазин", web_app=WebAppInfo(url=WEBAPP_URL))]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    for uid, user_data in users.items():
        try:
            await context.bot.send_message(
                chat_id=int(uid),
                text=msg_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            success += 1
        except Exception as e:
            fail += 1
            logger.error(f"Failed to send to {uid}: {e}")

    await update.message.reply_text(
        f"✅ Рассылка завершена!\n"
        f"📤 Отправлено: {success}\n"
        f"❌ Не доставлено: {fail}"
    )

# ── /stats — статистика ──
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Нет доступа")
        return

    users = load_users()
    await update.message.reply_text(
        f"📊 *Статистика MARATTI*\n\n"
        f"👥 Всего пользователей: {len(users)}\n"
        f"📅 Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}",
        parse_mode='Markdown'
    )

# ── /promo — промокод ──
async def promo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("🛍 Открыть магазин", web_app=WebAppInfo(url=WEBAPP_URL))]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🎁 *Ваш промокод:*\n\n"
        "Введите код *ИНСТА* при оформлении заказа\n"
        "и получите скидку *500 ₽* 🔥\n\n"
        "👇 Открывай магазин и применяй промокод!",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

# ── /help ──
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("🛍 Открыть магазин", web_app=WebAppInfo(url=WEBAPP_URL))]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "📋 *Команды бота:*\n\n"
        "/start — Главное меню\n"
        "/promo — Получить промокод\n"
        "/help — Помощь\n\n"
        "📞 Поддержка: +7 (989) 476-20-89\n"
        "📸 Instagram: @maratti.official",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

# ── Обработка обычных сообщений ──
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("🛍 Открыть магазин", web_app=WebAppInfo(url=WEBAPP_URL))]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "👞 Используй кнопку ниже чтобы открыть каталог MARATTI!\n\n"
        "Или напиши /help для списка команд.",
        reply_markup=reply_markup
    )

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("promo", promo))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Bot started!")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
