import os, json, logging, asyncio, aiohttp, base64
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.constants import ParseMode

# ═══════════════════════════════════════════════════════════
#  КОНФИГУРАЦИЯ
# ═══════════════════════════════════════════════════════════
BOT_TOKEN  = os.environ.get('BOT_TOKEN', '')
OWNER_ID   = int(os.environ.get('OWNER_ID', '1258838821'))
WEBAPP_URL = os.environ.get('WEBAPP_URL', 'https://maratti-shop.github.io/maratti')
GH_TOKEN   = os.environ.get('GH_TOKEN', '')
GH_REPO    = os.environ.get('GH_REPO', 'maratti-shop/maratti')
GH_BRANCH  = os.environ.get('GH_BRANCH', 'main')
GH_RAW     = f'https://raw.githubusercontent.com/{GH_REPO}/{GH_BRANCH}/'
GH_API     = f'https://api.github.com/repos/{GH_REPO}/contents/'

USERS_FILE      = 'users.json'
ORDERS_FILE     = 'orders.json'
BROADCASTS_FILE = 'broadcasts.json'
STATS_FILE      = 'bot_stats.json'
FUNNEL_FILE     = 'funnel.json'

logging.basicConfig(format='%(asctime)s [%(levelname)s] %(name)s: %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Реферальные уровни скидок
REF_LEVELS = {5: 10, 10: 20, 20: 30}

# Статусы заказов
ORDER_STATUSES = {
    'new':       ('🆕', 'Новый'),
    'confirmed': ('✅', 'Подтверждён'),
    'packing':   ('📦', 'Собирается'),
    'shipped':   ('🚚', 'Отправлен'),
    'delivered': ('🎉', 'Доставлен'),
    'cancelled': ('❌', 'Отменён'),
}

# Автоворонка — дни и сообщения
FUNNEL_STEPS = [
    {'day': 1,  'key': 'day1',  'text': None},  # Приветствие — в /start
    {'day': 3,  'key': 'day3',  'text': '🎁 Специально для тебя промокод *СКИДКА3* на −300 ₽\\!\n\nДействует 48 часов\\. Открывай магазин и применяй при оформлении\\!'},
    {'day': 7,  'key': 'day7',  'text': '👞 Новинки уже в каталоге\\!\n\nПосмотри свежие поступления MARATTI — натуральная кожа, стильные модели\\.'},
    {'day': 30, 'key': 'day30', 'text': '👋 Мы скучаем\\! Давно тебя не было в магазине\\.\n\n🎁 Держи промокод *ВЕРНИСЬ* на −500 ₽ — только для тебя\\.'},
]

# ═══════════════════════════════════════════════════════════
#  УТИЛИТЫ
# ═══════════════════════════════════════════════════════════
def load_json(path, default=None):
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f'load_json {path}: {e}')
    return default if default is not None else {}

def save_json(path, data):
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f'save_json {path}: {e}')
        return False

def now_str():
    return datetime.now().strftime('%d.%m.%Y %H:%M')

def escape_md(text: str) -> str:
    for c in r'\_*[]()~`>#+-=|{}.!':
        text = text.replace(c, f'\\{c}')
    return text

# ═══════════════════════════════════════════════════════════
#  GITHUB — чтение и запись через API
# ═══════════════════════════════════════════════════════════
async def gh_get_raw(filename):
    url = GH_RAW + filename + '?t=' + str(int(datetime.now().timestamp()))
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=8)) as r:
                if r.status == 200:
                    return await r.json(content_type=None)
    except Exception as e:
        logger.warning(f'gh_get_raw {filename}: {e}')
    return None

async def gh_get_file(filename):
    """Получает файл с SHA для последующего обновления"""
    if not GH_TOKEN:
        return None, None
    headers = {
        'Authorization': f'Bearer {GH_TOKEN}',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
    }
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(GH_API + filename, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    fd = await r.json()
                    content = json.loads(base64.b64decode(fd['content'].replace('\n', '')).decode('utf-8'))
                    return content, fd['sha']
                elif r.status == 404:
                    return None, None
    except Exception as e:
        logger.error(f'gh_get_file {filename}: {e}')
    return None, None

async def gh_put_file(filename, data, sha, message='update'):
    """Сохраняет файл на GitHub"""
    if not GH_TOKEN:
        return False
    headers = {
        'Authorization': f'Bearer {GH_TOKEN}',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'Content-Type': 'application/json',
    }
    json_str = json.dumps(data, ensure_ascii=False, indent=2)
    encoded = base64.b64encode(json_str.encode('utf-8')).decode('utf-8')
    body = {'message': message, 'content': encoded}
    if sha:
        body['sha'] = sha
    try:
        async with aiohttp.ClientSession() as s:
            async with s.put(GH_API + filename, headers=headers,
                             json=body, timeout=aiohttp.ClientTimeout(total=15)) as r:
                return r.status in (200, 201)
    except Exception as e:
        logger.error(f'gh_put_file {filename}: {e}')
        return False

# ═══════════════════════════════════════════════════════════
#  ПОЛЬЗОВАТЕЛИ
# ═══════════════════════════════════════════════════════════
def load_users():  return load_json(USERS_FILE, {})
def save_users(u): return save_json(USERS_FILE, u)

def add_user(user, ref_code=None):
    users = load_users()
    uid = str(user.id)
    is_new = uid not in users
    if is_new:
        users[uid] = {
            'id': user.id,
            'first_name': user.first_name or '',
            'last_name': user.last_name or '',
            'username': user.username or '',
            'joined': now_str(),
            'joined_iso': datetime.now().isoformat(),
            'last_seen': now_str(),
            'orders': 0,
            'total_spent': 0,
            'blocked': False,
            'ref_by': ref_code or '',
            'ref_count': 0,
            'source': 'referral' if ref_code else 'organic',
            'funnel': {},
            'city': '',
        }
        if ref_code and ref_code in users:
            users[ref_code]['ref_count'] = users[ref_code].get('ref_count', 0) + 1
            _check_ref_level(users, ref_code)
        save_users(users)
    else:
        users[uid]['last_seen'] = now_str()
        save_users(users)
    return is_new

def _check_ref_level(users, uid):
    """Проверяем достиг ли пользователь нового реферального уровня"""
    count = users[uid].get('ref_count', 0)
    for level_count, discount in sorted(REF_LEVELS.items()):
        if count == level_count:
            users[uid][f'ref_discount_{level_count}'] = discount
            return discount
    return 0

def get_user(uid): return load_users().get(str(uid))

def get_ref_discount(uid):
    """Текущая скидка пользователя по рефералам"""
    user = get_user(uid)
    if not user:
        return 0
    refs = user.get('ref_count', 0)
    discount = 0
    for level_count, disc in sorted(REF_LEVELS.items()):
        if refs >= level_count:
            discount = disc
    return discount

# ═══════════════════════════════════════════════════════════
#  ЗАКАЗЫ
# ═══════════════════════════════════════════════════════════
def load_orders(): return load_json(ORDERS_FILE, [])
def save_orders(o): return save_json(ORDERS_FILE, o)

def get_order(order_id):
    orders = load_orders()
    for o in orders:
        num = str(o.get('num', o.get('id', ''))).replace('#', '')
        if num == str(order_id).replace('#', ''):
            return o
    return None

def update_order_status(order_id, new_status):
    orders = load_orders()
    for o in orders:
        num = str(o.get('num', o.get('id', ''))).replace('#', '')
        if num == str(order_id).replace('#', ''):
            o['status'] = new_status
            o['status_updated'] = now_str()
            save_orders(orders)
            return o
    return None

# ═══════════════════════════════════════════════════════════
#  СТАТИСТИКА
# ═══════════════════════════════════════════════════════════
def load_stats(): return load_json(STATS_FILE, {})
def save_stats(s): save_json(STATS_FILE, s)

def bump_stat(key, n=1):
    s = load_stats()
    s[key] = s.get(key, 0) + n
    today = datetime.now().strftime('%Y-%m-%d')
    s.setdefault('daily', {}).setdefault(today, {})
    s['daily'][today][key] = s['daily'][today].get(key, 0) + n
    save_stats(s)

def cohort_stats():
    """Когортный анализ по месяцам"""
    users = load_users()
    cohorts = {}
    for u in users.values():
        joined = u.get('joined_iso', '')
        if not joined:
            continue
        try:
            dt = datetime.fromisoformat(joined)
            month = dt.strftime('%Y-%m')
            cohorts.setdefault(month, {'users': 0, 'orders': 0, 'spent': 0})
            cohorts[month]['users'] += 1
            cohorts[month]['orders'] += u.get('orders', 0)
            cohorts[month]['spent'] += u.get('total_spent', 0)
        except Exception:
            continue
    return cohorts

# ═══════════════════════════════════════════════════════════
#  КЛАВИАТУРЫ
# ═══════════════════════════════════════════════════════════
def kb_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛍 Открыть магазин MARATTI", web_app=WebAppInfo(url=WEBAPP_URL))],
        [InlineKeyboardButton("📦 Мои заказы", callback_data="cb_orders"),
         InlineKeyboardButton("🎁 Промокод", callback_data="cb_promo")],
        [InlineKeyboardButton("👥 Пригласить друга", callback_data="cb_ref")],
    ])

def kb_back():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("« Назад", callback_data="cb_start")],
        [InlineKeyboardButton("🛍 Открыть магазин", web_app=WebAppInfo(url=WEBAPP_URL))],
    ])

def kb_shop():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛍 Открыть магазин MARATTI", web_app=WebAppInfo(url=WEBAPP_URL))]
    ])

def kb_order_status(order_num):
    statuses = [
        ('✅ Подтвердить',  f'status_{order_num}_confirmed'),
        ('📦 Собирается',   f'status_{order_num}_packing'),
        ('🚚 Отправить',    f'status_{order_num}_shipped'),
        ('🎉 Доставлен',    f'status_{order_num}_delivered'),
        ('❌ Отменить',     f'status_{order_num}_cancelled'),
    ]
    rows = [[InlineKeyboardButton(t, callback_data=d)] for t, d in statuses]
    return InlineKeyboardMarkup(rows)

def kb_review(order_num):
    stars = [InlineKeyboardButton(f'{"⭐"*i}', callback_data=f'review_{order_num}_{i}') for i in range(1, 6)]
    return InlineKeyboardMarkup([stars])

# ═══════════════════════════════════════════════════════════
#  ХЭНДЛЕРЫ — /start
# ═══════════════════════════════════════════════════════════
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = ctx.args
    ref_code = args[0].replace('ref_', '') if args and args[0].startswith('ref_') else None

    is_new = add_user(user, ref_code)
    bump_stat('starts')
    name = escape_md(user.first_name or 'друг')
    disc = get_ref_discount(user.id)
    disc_text = f'\n\n🎖 Твоя реферальная скидка: *{disc}%* на все заказы\\!' if disc > 0 else ''

    if is_new:
        text = (
            f'👋 Привет, {name}\\!\n\n'
            f'Добро пожаловать в *MARATTI* — обувь из натуральной кожи 👞\n\n'
            f'✅ Цены до 50% ниже Wildberries\n'
            f'✅ Натуральная кожа и замша\n'
            f'✅ Производство с 2006 года\n'
            f'✅ Рейтинг 4\\.8 ⭐ на WB\n\n'
            f'🎁 Промокод *ИНСТА* — скидка *500 ₽* на первый заказ\\!'
            f'{disc_text}\n\n'
            f'👇 Нажми и выбирай свою пару\\!'
        )
        bump_stat('new_users')
        # Уведомляем владельца
        try:
            users = load_users()
            uname = f'@{user.username}' if user.username else '(нет username)'
            src = f' · реферал от {ref_code}' if ref_code else ''
            await ctx.bot.send_message(
                OWNER_ID,
                f'👤 *Новый подписчик*\n{user.first_name} {uname}{src}\nВсего: {len(users)} чел\\.',
                parse_mode=ParseMode.MARKDOWN_V2
            )
        except Exception:
            pass
        # Запускаем автоворонку
        funnel = load_json(FUNNEL_FILE, {})
        funnel[str(user.id)] = {
            'joined': datetime.now().isoformat(),
            'steps_done': [],
        }
        save_json(FUNNEL_FILE, funnel)
    else:
        text = (
            f'👋 С возвращением, {name}\\!\n\n'
            f'*MARATTI* — премиум обувь из натуральной кожи 👞\n\n'
            f'Промокод *ИНСТА* — скидка *500 ₽*'
            f'{disc_text}\n\n'
            f'👇 Открывай и выбирай\\!'
        )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=kb_main())

# ═══════════════════════════════════════════════════════════
#  ХЭНДЛЕРЫ — команды пользователя
# ═══════════════════════════════════════════════════════════
async def promo_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    bump_stat('promo_requests')
    uid = update.effective_user.id
    disc = get_ref_discount(uid)
    disc_text = f'\n\n🎖 *Ваша реферальная скидка:* {disc}% на все заказы\\!' if disc else ''
    text = (
        f'🎁 *Промокоды MARATTI:*\n\n'
        f'*ИНСТА* — скидка *500 ₽* на любой заказ\n'
        f'Вводи при оформлении в корзине\\.'
        f'{disc_text}'
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=kb_shop())

async def ref_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = get_user(uid) or {}
    refs = user.get('ref_count', 0)
    link = f'https://t.me/maratti_shop_bot?start=ref_{uid}'

    # Определяем текущий и следующий уровень
    current_disc = get_ref_discount(uid)
    next_level = None
    for lvl_count, lvl_disc in sorted(REF_LEVELS.items()):
        if refs < lvl_count:
            next_level = (lvl_count, lvl_disc)
            break

    levels_text = '\n'.join(
        f'{"✅" if refs >= cnt else "⬜"} {cnt} друзей → скидка *{disc}%*'
        for cnt, disc in sorted(REF_LEVELS.items())
    )
    next_text = (
        f'\n\nДо следующего уровня: *{next_level[0] - refs}* чел\\.'
        f' → скидка *{next_level[1]}%*'
    ) if next_level else '\n\n🏆 Максимальный уровень достигнут\\!'

    text = (
        f'👥 *Реферальная программа MARATTI*\n\n'
        f'Приглашай друзей — получай скидку на все заказы:\n\n'
        f'{levels_text}'
        f'{next_text}\n\n'
        f'Ты пригласил: *{refs}* чел\\.\n'
        f'Твоя скидка: *{current_disc}%*\n\n'
        f'🔗 Твоя ссылка:\n`{escape_md(link)}`'
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=kb_back())

async def order_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /order — список заказов
    /order 123456 — статус конкретного заказа
    """
    uid = str(update.effective_user.id)
    args = ctx.args

    if args:
        order_num = args[0].replace('#', '')
        order = get_order(order_num)
        if not order:
            await update.message.reply_text('❌ Заказ не найден\\.', parse_mode=ParseMode.MARKDOWN_V2)
            return
        # Проверяем что заказ принадлежит этому пользователю (или это владелец)
        if str(order.get('tgId', '')) != uid and update.effective_user.id != OWNER_ID:
            await update.message.reply_text('❌ Это не ваш заказ\\.', parse_mode=ParseMode.MARKDOWN_V2)
            return
        await _send_order_status(update.message, order)
        return

    # Список всех заказов пользователя
    orders = load_orders()
    my_orders = [o for o in orders if str(o.get('tgId', '')) == uid]
    if not my_orders:
        await update.message.reply_text(
            '📦 У вас пока нет заказов\\.\n\nОткрывай магазин и делай первый заказ\\!',
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=kb_shop()
        )
        return

    lines = ['📦 *Ваши заказы MARATTI:*\n']
    for o in sorted(my_orders, key=lambda x: x.get('id', 0), reverse=True)[:5]:
        num = str(o.get('num', o.get('id', ''))).replace('#', '')
        status_key = o.get('status', 'new')
        emoji, status_name = ORDER_STATUSES.get(status_key, ('❓', status_key))
        total = o.get('total', 0)
        date = o.get('date', '')
        lines.append(f'{emoji} Заказ \\#{escape_md(num)} — {status_name}\n   {escape_md(date)} · {escape_md(str(total))} ₽')

    lines.append(f'\n💬 Подробнее: `/order НОМЕР`')
    await update.message.reply_text('\n'.join(lines), parse_mode=ParseMode.MARKDOWN_V2, reply_markup=kb_shop())

async def _send_order_status(message, order):
    num = str(order.get('num', order.get('id', ''))).replace('#', '')
    status_key = order.get('status', 'new')
    emoji, status_name = ORDER_STATUSES.get(status_key, ('❓', status_key))
    items = order.get('items', [])
    items_text = '\n'.join(f'  • {escape_md(i.get("name",""))} р\\.{i.get("size","")} — {i.get("price",0)} ₽' for i in items)
    track = order.get('track', '')
    track_text = f'\n\n🚚 Трек\\-номер: `{escape_md(track)}`' if track else ''
    text = (
        f'📦 *Заказ \\#{escape_md(num)}*\n\n'
        f'Статус: {emoji} *{status_name}*\n'
        f'Дата: {escape_md(order.get("date", ""))}\n\n'
        f'Товары:\n{items_text}\n\n'
        f'💳 Итого: {order.get("total", 0)} ₽'
        f'{track_text}'
    )
    await message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=kb_shop())

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        '📋 *Команды MARATTI:*\n\n'
        '/start — Главное меню\n'
        '/order — Мои заказы\n'
        '/order 123456 — Статус заказа\n'
        '/promo — Промокод\n'
        '/ref — Реферальная ссылка\n'
        '/help — Помощь\n\n'
        '📞 Поддержка: \\+7 \\(989\\) 476\\-20\\-89'
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=kb_shop())

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    bump_stat('messages')
    await update.message.reply_text(
        'Используй кнопку ниже чтобы открыть магазин 👇\nИли /help — список команд\\.',
        parse_mode=ParseMode.MARKDOWN_V2, reply_markup=kb_shop()
    )

# ═══════════════════════════════════════════════════════════
#  CALLBACK QUERY
# ═══════════════════════════════════════════════════════════
async def callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data
    uid = q.from_user.id
    await q.answer()

    # Смена статуса заказа (только владелец)
    if data.startswith('status_') and uid == OWNER_ID:
        parts = data.split('_')
        order_num = parts[1]
        new_status = parts[2]
        order = update_order_status(order_num, new_status)
        if order:
            emoji, status_name = ORDER_STATUSES.get(new_status, ('❓', new_status))
            track = order.get('track', '')
            await q.edit_message_text(
                f'✅ Статус заказа \\#{escape_md(order_num)} изменён на {emoji} *{escape_md(status_name)}*',
                parse_mode=ParseMode.MARKDOWN_V2
            )
            # Уведомляем покупателя
            tg_id = order.get('tgId')
            if tg_id:
                track_text = f'\n\n🚚 Трек\\-номер: `{escape_md(track)}`' if track else ''
                try:
                    await ctx.bot.send_message(
                        chat_id=int(tg_id),
                        text=(
                            f'📦 *MARATTI* — статус заказа \\#{escape_md(order_num)}\n\n'
                            f'{emoji} *{escape_md(status_name)}*'
                            f'{track_text}\n\n'
                            f'Вопросы? Пиши нам 📞'
                        ),
                        parse_mode=ParseMode.MARKDOWN_V2,
                        reply_markup=kb_shop()
                    )
                except Exception as e:
                    logger.warning(f'Не удалось уведомить покупателя {tg_id}: {e}')
        return

    # Оценка после заказа
    if data.startswith('review_') and '_' in data:
        parts = data.split('_')
        if len(parts) == 3:
            order_num, rating = parts[1], parts[2]
            await q.edit_message_text(
                f'⭐ Спасибо за оценку {"⭐"*int(rating)}\\!\n\nВаш отзыв поможет нам стать лучше\\.', 
                parse_mode=ParseMode.MARKDOWN_V2
            )
            try:
                await ctx.bot.send_message(
                    OWNER_ID,
                    f'⭐ Новый отзыв от {escape_md(q.from_user.first_name or "покупателя")}\\!\n'
                    f'Заказ \\#{escape_md(order_num)}: {"⭐"*int(rating)}',
                    parse_mode=ParseMode.MARKDOWN_V2
                )
            except Exception:
                pass
        return

    # Навигация
    if data == 'cb_start':
        name = escape_md(q.from_user.first_name or 'друг')
        disc = get_ref_discount(uid)
        disc_text = f'\n\n🎖 Реферальная скидка: *{disc}%* на все заказы\\!' if disc else ''
        await q.edit_message_text(
            f'👋 С возвращением, {name}\\!{disc_text}\n\n👇 Выбери действие:',
            parse_mode=ParseMode.MARKDOWN_V2, reply_markup=kb_main()
        )
    elif data == 'cb_promo':
        await q.edit_message_text(
            '🎁 *Промокоды MARATTI:*\n\n*ИНСТА* — скидка *500 ₽* на любой заказ\\.',
            parse_mode=ParseMode.MARKDOWN_V2, reply_markup=kb_back()
        )
    elif data == 'cb_ref':
        link = f'https://t.me/maratti_shop_bot?start=ref_{uid}'
        user = get_user(uid) or {}
        refs = user.get('ref_count', 0)
        disc = get_ref_discount(uid)
        levels_text = '\n'.join(
            f'{"✅" if refs >= c else "⬜"} {c} друзей → *{d}%*'
            for c, d in sorted(REF_LEVELS.items())
        )
        await q.edit_message_text(
            f'👥 *Реферальная программа*\n\n{levels_text}\n\n'
            f'Ты пригласил: *{refs}* чел\\.\nТвоя скидка: *{disc}%*\n\n'
            f'🔗 Ссылка:\n`{escape_md(link)}`',
            parse_mode=ParseMode.MARKDOWN_V2, reply_markup=kb_back()
        )
    elif data == 'cb_orders':
        uid_str = str(q.from_user.id)
        orders = load_orders()
        my = [o for o in orders if str(o.get('tgId', '')) == uid_str]
        if not my:
            await q.edit_message_text(
                '📦 У вас пока нет заказов\\.',
                parse_mode=ParseMode.MARKDOWN_V2, reply_markup=kb_back()
            )
            return
        lines = ['📦 *Ваши заказы:*\n']
        for o in sorted(my, key=lambda x: x.get('id', 0), reverse=True)[:5]:
            num = str(o.get('num', o.get('id', ''))).replace('#', '')
            e, sn = ORDER_STATUSES.get(o.get('status', 'new'), ('❓', '?'))
            lines.append(f'{e} \\#{escape_md(num)} — {escape_md(sn)} · {o.get("total", 0)} ₽')
        await q.edit_message_text(
            '\n'.join(lines), parse_mode=ParseMode.MARKDOWN_V2, reply_markup=kb_back()
        )

# ═══════════════════════════════════════════════════════════
#  КОМАНДЫ ВЛАДЕЛЬЦА
# ═══════════════════════════════════════════════════════════
def owner_only(func):
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != OWNER_ID:
            await update.message.reply_text('❌ Нет доступа')
            return
        return await func(update, ctx)
    wrapper.__name__ = func.__name__
    return wrapper

@owner_only
async def stats_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    stats = load_stats()
    orders = load_orders()
    today = datetime.now().strftime('%Y-%m-%d')
    d_today = stats.get('daily', {}).get(today, {})
    total = len(users)
    active_30 = sum(1 for u in users.values()
                    if not u.get('blocked') and
                    u.get('last_seen', '') > (datetime.now()-timedelta(days=30)).strftime('%d.%m.%Y'))
    total_revenue = sum(o.get('total', 0) for o in orders if o.get('status') not in ('cancelled',))
    orders_count = len([o for o in orders if o.get('status') not in ('cancelled', 'new')])
    refs_total = sum(u.get('ref_count', 0) for u in users.values())

    text = (
        f'📊 *Статистика MARATTI*\n_{now_str()}_\n\n'
        f'👥 *Подписчики*\n'
        f'Всего: {total}\nАктивных \\(30д\\): {active_30}\n\n'
        f'📦 *Заказы*\n'
        f'Оформлено: {orders_count}\nВыручка: {escape_md(f"{total_revenue:,}".replace(",", " "))} ₽\n\n'
        f'👥 *Рефералы*\nПриведено друзей: {refs_total}\n\n'
        f'📅 *Сегодня*\n'
        f'Новых: {d_today.get("new_users", 0)}\nСтартов: {d_today.get("starts", 0)}'
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)

@owner_only
async def cohort_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cohorts = cohort_stats()
    if not cohorts:
        await update.message.reply_text('Нет данных\\.', parse_mode=ParseMode.MARKDOWN_V2)
        return
    lines = ['📊 *Когортный анализ по месяцам:*\n']
    for month in sorted(cohorts.keys(), reverse=True)[:6]:
        c = cohorts[month]
        conv = round(c['orders'] / c['users'] * 100) if c['users'] else 0
        avg = round(c['spent'] / c['orders']) if c['orders'] else 0
        lines.append(
            f'📅 *{escape_md(month)}*\n'
            f'  Новых: {c["users"]} · Заказов: {c["orders"]} · Конверсия: {conv}%\n'
            f'  Средний чек: {escape_md(str(avg))} ₽'
        )
    await update.message.reply_text('\n'.join(lines), parse_mode=ParseMode.MARKDOWN_V2)

@owner_only
async def segment_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /segment bought — купили хоть раз
    /segment notbought — ни разу не купили
    /segment inactive — не заходили 30+ дней
    /segment city Москва — по городу
    """
    if not ctx.args:
        await update.message.reply_text(
            '📋 *Сегменты:*\n\n'
            '`/segment bought` — купили хоть раз\n'
            '`/segment notbought` — не купили\n'
            '`/segment inactive` — не заходили 30\\+ дней\n'
            '`/segment city Москва` — по городу\n'
            '`/segment referral` — пришли по рефералу',
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    seg = ctx.args[0].lower()
    users = load_users()
    cutoff = (datetime.now() - timedelta(days=30)).strftime('%d.%m.%Y')

    if seg == 'bought':
        result = [u for u in users.values() if u.get('orders', 0) > 0 and not u.get('blocked')]
        label = 'Купили хоть раз'
    elif seg == 'notbought':
        result = [u for u in users.values() if u.get('orders', 0) == 0 and not u.get('blocked')]
        label = 'Ещё не купили'
    elif seg == 'inactive':
        result = [u for u in users.values()
                  if u.get('last_seen', '01.01.2020') < cutoff and not u.get('blocked')]
        label = 'Неактивные 30+ дней'
    elif seg == 'city' and len(ctx.args) > 1:
        city = ' '.join(ctx.args[1:]).lower()
        result = [u for u in users.values()
                  if city in u.get('city', '').lower() and not u.get('blocked')]
        label = f'Город: {" ".join(ctx.args[1:])}'
    elif seg == 'referral':
        result = [u for u in users.values()
                  if u.get('source') == 'referral' and not u.get('blocked')]
        label = 'Пришли по рефералу'
    else:
        await update.message.reply_text('Неизвестный сегмент\\.', parse_mode=ParseMode.MARKDOWN_V2)
        return

    count = len(result)
    uids = [str(u['id']) for u in result]
    # Сохраняем сегмент для рассылки
    ctx.user_data['last_segment'] = uids
    await update.message.reply_text(
        f'✅ *Сегмент \\"{escape_md(label)}\\"*\n\n'
        f'Найдено: *{count}* пользователей\n\n'
        f'Чтобы отправить рассылку этому сегменту:\n'
        f'`/broadcast_segment текст сообщения`',
        parse_mode=ParseMode.MARKDOWN_V2
    )

@owner_only
async def broadcast_segment_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Рассылка по последнему выбранному сегменту"""
    uids = ctx.user_data.get('last_segment')
    if not uids:
        await update.message.reply_text(
            'Сначала выбери сегмент через /segment\\.', parse_mode=ParseMode.MARKDOWN_V2
        )
        return
    if not ctx.args:
        await update.message.reply_text('Укажи текст: `/broadcast_segment текст`', parse_mode=ParseMode.MARKDOWN_V2)
        return
    text = ' '.join(ctx.args)
    prog = await update.message.reply_text(f'⏳ Рассылка {len(uids)} пользователям\\.\\.\\.',
                                           parse_mode=ParseMode.MARKDOWN_V2)
    ok = fail = 0
    for uid in uids:
        try:
            await ctx.bot.send_message(int(uid), text, reply_markup=kb_shop(), parse_mode=ParseMode.MARKDOWN_V2)
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)
    await prog.edit_text(f'✅ Сегмент: {ok}/{len(uids)} доставлено', parse_mode=ParseMode.MARKDOWN_V2)

@owner_only
async def broadcast_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text(
            '📢 Использование: `/broadcast Текст`', parse_mode=ParseMode.MARKDOWN_V2
        )
        return
    text = ' '.join(ctx.args)
    users = load_users()
    targets = [uid for uid, u in users.items() if not u.get('blocked')]
    prog = await update.message.reply_text(f'⏳ Рассылка {len(targets)} пользователям\\.\\.\\.', parse_mode=ParseMode.MARKDOWN_V2)
    ok = fail = 0
    for i, uid in enumerate(targets, 1):
        try:
            await ctx.bot.send_message(int(uid), text, reply_markup=kb_shop(), parse_mode=ParseMode.MARKDOWN_V2)
            ok += 1
        except Exception:
            fail += 1
        if i % 30 == 0:
            try:
                await prog.edit_text(f'⏳ {i}/{len(targets)}...', parse_mode=ParseMode.MARKDOWN_V2)
            except Exception:
                pass
        await asyncio.sleep(0.05)
    _log_broadcast(text, len(targets), ok, fail)
    await prog.edit_text(f'✅ *Готово\\!* {ok}/{len(targets)} доставлено', parse_mode=ParseMode.MARKDOWN_V2)

@owner_only
async def settrack_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /settrack 123456 RM123456789RU
    Устанавливает трек-номер и отправляет покупателю
    """
    if len(ctx.args) < 2:
        await update.message.reply_text('Использование: `/settrack НОМЕР_ЗАКАЗА ТРЕК`', parse_mode=ParseMode.MARKDOWN_V2)
        return
    order_num = ctx.args[0]
    track = ctx.args[1]
    orders = load_orders()
    found = None
    for o in orders:
        num = str(o.get('num', o.get('id', ''))).replace('#', '')
        if num == order_num.replace('#', ''):
            o['track'] = track
            o['status'] = 'shipped'
            o['status_updated'] = now_str()
            found = o
            break
    if not found:
        await update.message.reply_text('❌ Заказ не найден\\.', parse_mode=ParseMode.MARKDOWN_V2)
        return
    save_orders(orders)
    await update.message.reply_text(f'✅ Трек для заказа \\#{escape_md(order_num)} установлен\\.', parse_mode=ParseMode.MARKDOWN_V2)
    tg_id = found.get('tgId')
    if tg_id:
        try:
            await ctx.bot.send_message(
                int(tg_id),
                f'🚚 *Ваш заказ MARATTI \\#{escape_md(order_num)} отправлен\\!*\n\n'
                f'Трек\\-номер: `{escape_md(track)}`\n\n'
                f'Отслеживайте на сайте СДЭК или OZON\\.', 
                parse_mode=ParseMode.MARKDOWN_V2, reply_markup=kb_shop()
            )
        except Exception as e:
            logger.warning(f'settrack notify: {e}')

@owner_only
async def export_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    lines = ['id,first_name,username,joined,last_seen,orders,spent,blocked,source,ref_count,city']
    for u in users.values():
        lines.append(','.join(str(x) for x in [
            u['id'], u.get('first_name',''), u.get('username',''),
            u.get('joined',''), u.get('last_seen',''), u.get('orders',0),
            u.get('total_spent',0), u.get('blocked',False),
            u.get('source',''), u.get('ref_count',0), u.get('city','')
        ]))
    fname = f'maratti_users_{datetime.now().strftime("%Y%m%d")}.csv'
    with open(fname, 'w', encoding='utf-8-sig') as f:
        f.write('\n'.join(lines))
    await update.message.reply_document(document=open(fname,'rb'), filename=fname,
                                        caption=f'📊 {len(users)} пользователей')

@owner_only
async def admin_help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        '🔑 *Команды владельца:*\n\n'
        '📊 *Аналитика*\n'
        '/stats — общая статистика\n'
        '/cohort — когортный анализ\n'
        '/export — выгрузить базу CSV\n\n'
        '📢 *Рассылки*\n'
        '/broadcast текст — всем\n'
        '/segment тип — выбрать сегмент\n'
        '/broadcast\\_segment текст — сегменту\n\n'
        '📦 *Заказы*\n'
        '/settrack номер трек — трек\\-номер\n\n'
        '/admin — эта справка'
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)

# ═══════════════════════════════════════════════════════════
#  ФОНОВЫЕ ЗАДАЧИ
# ═══════════════════════════════════════════════════════════
def _log_broadcast(text, total, ok, fail, btype='manual'):
    lst = load_json(BROADCASTS_FILE, [])
    lst.insert(0, {'date': now_str(), 'type': btype, 'text': text[:100], 'total': total, 'ok': ok, 'fail': fail})
    save_json(BROADCASTS_FILE, lst[:50])

async def run_funnel(ctx: ContextTypes.DEFAULT_TYPE):
    """Автоворонка — каждые 6 часов проверяет у кого какой шаг"""
    funnel = load_json(FUNNEL_FILE, {})
    now = datetime.now()
    updated = False
    for uid, data in list(funnel.items()):
        try:
            joined = datetime.fromisoformat(data['joined'])
        except Exception:
            continue
        days_passed = (now - joined).days
        steps_done = data.get('steps_done', [])
        user = get_user(uid)
        if not user or user.get('blocked'):
            continue
        for step in FUNNEL_STEPS:
            if step['key'] in steps_done:
                continue
            if step['text'] is None:
                funnel[uid]['steps_done'] = list(set(steps_done + [step['key']]))
                updated = True
                continue
            if days_passed >= step['day']:
                try:
                    await ctx.bot.send_message(
                        int(uid), step['text'],
                        parse_mode=ParseMode.MARKDOWN_V2, reply_markup=kb_shop()
                    )
                    funnel[uid]['steps_done'] = list(set(steps_done + [step['key']]))
                    updated = True
                    logger.info(f'Funnel {step["key"]} → {uid}')
                    bump_stat(f'funnel_{step["key"]}')
                except Exception as e:
                    logger.warning(f'Funnel send failed {uid}: {e}')
                break  # один шаг за раз
    if updated:
        save_json(FUNNEL_FILE, funnel)

async def review_requests(ctx: ContextTypes.DEFAULT_TYPE):
    """Через 3 дня после доставки просим оставить отзыв"""
    orders = load_orders()
    now = datetime.now()
    for o in orders:
        if o.get('status') != 'delivered':
            continue
        if o.get('review_requested'):
            continue
        updated_str = o.get('status_updated', '')
        if not updated_str:
            continue
        try:
            updated = datetime.strptime(updated_str, '%d.%m.%Y %H:%M')
        except Exception:
            continue
        if (now - updated).days < 3:
            continue
        tg_id = o.get('tgId')
        if not tg_id:
            continue
        num = str(o.get('num', o.get('id', ''))).replace('#', '')
        try:
            await ctx.bot.send_message(
                int(tg_id),
                f'👋 Надеемся, вам понравилась покупка\\!\n\n'
                f'Оцените заказ \\#{escape_md(num)} — это займёт 5 секунд:\n'
                f'Нажмите на звёзды ниже 👇',
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=kb_review(num)
            )
            o['review_requested'] = True
            bump_stat('review_requests')
        except Exception as e:
            logger.warning(f'review_request {tg_id}: {e}')
    save_orders(orders)

async def abandoned_carts(ctx: ContextTypes.DEFAULT_TYPE):
    """Брошенная корзина — напоминание через 24ч"""
    carts_data = load_json('carts.json', {})
    now = datetime.now()
    updated = False
    for uid, cart in list(carts_data.items()):
        if cart.get('reminded'):
            continue
        try:
            saved = datetime.fromisoformat(cart['saved_at'])
        except Exception:
            continue
        if (now - saved) < timedelta(hours=24):
            continue
        user = get_user(uid)
        if not user or user.get('blocked'):
            continue
        items = cart.get('items', [])
        if not items:
            continue
        names = escape_md(', '.join(i.get('name', 'товар') for i in items[:2]))
        try:
            await ctx.bot.send_message(
                int(uid),
                f'👋 Ты оставил в корзине: _{names}_\n\n'
                f'🎁 Промокод *БРОШЕНА* — скидка *300 ₽*\\!\nДействует 48 часов\\.',
                parse_mode=ParseMode.MARKDOWN_V2, reply_markup=kb_shop()
            )
            carts_data[uid]['reminded'] = True
            updated = True
            bump_stat('abandoned_cart_reminders')
        except Exception as e:
            logger.warning(f'abandoned_cart {uid}: {e}')
    if updated:
        save_json('carts.json', carts_data)

async def daily_report(ctx: ContextTypes.DEFAULT_TYPE):
    """Ежедневный отчёт владельцу"""
    stats = load_stats()
    users = load_users()
    orders = load_orders()
    yesterday = (datetime.now()-timedelta(days=1)).strftime('%Y-%m-%d')
    d = stats.get('daily', {}).get(yesterday, {})
    new_orders = [o for o in orders
                  if o.get('date', '').startswith((datetime.now()-timedelta(days=1)).strftime('%d.%m.%Y'))]
    revenue = sum(o.get('total', 0) for o in new_orders if o.get('status') != 'cancelled')
    text = (
        f'📊 *Ежедневный отчёт MARATTI*\n'
        f'_{(datetime.now()-timedelta(days=1)).strftime("%d.%m.%Y")}_\n\n'
        f'👥 Всего подписчиков: {len(users)}\n'
        f'🆕 Новых вчера: {d.get("new_users", 0)}\n'
        f'📱 Стартов: {d.get("starts", 0)}\n'
        f'📦 Заказов вчера: {len(new_orders)}\n'
        f'💰 Выручка вчера: {escape_md(str(revenue))} ₽\n'
        f'🎁 Запросов промокода: {d.get("promo_requests", 0)}\n'
        f'🛒 Напоминаний корзины: {d.get("abandoned_cart_reminders", 0)}'
    )
    try:
        await ctx.bot.send_message(OWNER_ID, text, parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as e:
        logger.error(f'daily_report: {e}')

# ═══════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════
async def post_init(app: Application):
    await app.bot.set_my_commands([
        BotCommand('start',  'Главное меню'),
        BotCommand('order',  'Мои заказы'),
        BotCommand('promo',  'Промокод'),
        BotCommand('ref',    'Реферальная ссылка'),
        BotCommand('help',   'Помощь'),
    ])
    logger.info('Bot ready!')

def main():
    if not BOT_TOKEN:
        logger.error('BOT_TOKEN не задан!')
        return
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # Пользовательские команды
    app.add_handler(CommandHandler('start',   start))
    app.add_handler(CommandHandler('order',   order_cmd))
    app.add_handler(CommandHandler('promo',   promo_cmd))
    app.add_handler(CommandHandler('ref',     ref_cmd))
    app.add_handler(CommandHandler('help',    help_cmd))

    # Команды владельца
    app.add_handler(CommandHandler('stats',              stats_cmd))
    app.add_handler(CommandHandler('cohort',             cohort_cmd))
    app.add_handler(CommandHandler('segment',            segment_cmd))
    app.add_handler(CommandHandler('broadcast',          broadcast_cmd))
    app.add_handler(CommandHandler('broadcast_segment',  broadcast_segment_cmd))
    app.add_handler(CommandHandler('settrack',           settrack_cmd))
    app.add_handler(CommandHandler('export',             export_cmd))
    app.add_handler(CommandHandler('admin',              admin_help_cmd))

    # Кнопки
    app.add_handler(CallbackQueryHandler(callback))

    # Текст
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Фоновые задачи
    jq = app.job_queue
    jq.run_repeating(run_funnel,        interval=21600,  first=30)
    jq.run_repeating(abandoned_carts,   interval=21600,  first=60)
    jq.run_repeating(review_requests,   interval=43200,  first=120)
    jq.run_repeating(daily_report,      interval=86400,  first=10)

    logger.info('🚀 MARATTI bot started!')
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == '__main__':
    main()
