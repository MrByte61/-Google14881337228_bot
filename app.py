import logging
from collections import defaultdict, deque
from html import escape
from typing import Final

from fastapi import FastAPI, Request
from google import genai
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# =========================
# CONFIG
# =========================
TELEGRAM_BOT_TOKEN: Final[str] = "8647789219:AAEYh2gamKCbGAd_p1C_YmSyGlRK0LnX-TQ"
GEMINI_API_KEY: Final[str] = "AIzaSyB9cW2ZGrx_VC4UZWHx_jsuhOaArsJAHBo"
GEMINI_MODEL: Final[str] = "gemini-2.5-flash"

# Сюда потом вставишь свой Telegram ID, чтобы бот пересылал тебе сообщения пользователей
ADMIN_CHAT_ID: Final[int] = -5124062220

# Render URL вставишь позже после деплоя
RENDER_EXTERNAL_URL: Final[str] = "https://telegram-gemini-bot-jvvg.onrender.com/"

WEBHOOK_SECRET_PATH: Final[str] = f"/webhook/{TELEGRAM_BOT_TOKEN}"
WEBHOOK_URL: Final[str] = f"{RENDER_EXTERNAL_URL}{WEBHOOK_SECRET_PATH}"

logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

genai_client = genai.Client(api_key=GEMINI_API_KEY)

# Память переписки на пользователя
user_histories: dict[int, deque[dict]] = defaultdict(lambda: deque(maxlen=14))

SYSTEM_PROMPT = """
Ты дружелюбный, живой и умный Telegram-бот.
Отвечай естественно, не слишком сухо.
Если вопрос простой — отвечай коротко и понятно.
Если вопрос сложный — объясняй по шагам.
Если пользователь отвечает на предыдущее сообщение, учитывай этот контекст.
Пиши на языке пользователя.
Не будь бездушным, но и не перегибай.
Иногда можно использовать уместные эмодзи, но умеренно.
Если уместно, делай ответ красиво структурированным.
Если не уверен в фактах — честно скажи об этом.
""".strip()

app = FastAPI()
telegram_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
bot = Bot(token=TELEGRAM_BOT_TOKEN)


def get_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🧹 Очистить память", callback_data="clear_memory"),
                InlineKeyboardButton("ℹ️ Помощь", callback_data="show_help"),
            ]
        ]
    )


def save_to_history(user_id: int, role: str, text: str) -> None:
    user_histories[user_id].append({"role": role, "text": text})


def clear_history(user_id: int) -> None:
    user_histories[user_id].clear()


def build_prompt(user_id: int, user_text: str, reply_context: str | None = None) -> str:
    history = list(user_histories[user_id])

    parts = [SYSTEM_PROMPT, "\n\nИстория диалога:\n"]

    if history:
        for item in history:
            speaker = "Пользователь" if item["role"] == "user" else "Бот"
            parts.append(f"{speaker}: {item['text']}\n")
    else:
        parts.append("История пока пустая.\n")

    if reply_context:
        parts.append(f"\nПользователь отвечает на это сообщение бота:\n{reply_context}\n")

    parts.append(f"\nНовое сообщение пользователя:\n{user_text}\n")
    parts.append(
        "\nОтветь живо, естественно и по делу. "
        "Если нужно, разбей ответ на короткие абзацы или пункты."
    )

    return "".join(parts)


def ask_gemini(user_id: int, user_text: str, reply_context: str | None = None) -> str:
    prompt = build_prompt(user_id=user_id, user_text=user_text, reply_context=reply_context)

    response = genai_client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
    )

    text = getattr(response, "text", None)
    if text and text.strip():
        return text.strip()

    return "Не получилось получить ответ. Попробуй ещё раз."


async def send_admin_log(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    username: str | None,
    first_name: str | None,
    text: str,
) -> None:
    if not ADMIN_CHAT_ID:
        return

    username_text = f"@{username}" if username else "нет username"
    first_name_text = first_name or "без имени"

    log_text = (
        "📩 Новое сообщение боту\n\n"
        f"ID: {user_id}\n"
        f"Username: {username_text}\n"
        f"Имя: {first_name_text}\n"
        f"Текст: {text}"
    )

    try:
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=log_text)
    except Exception as e:
        logger.exception("Не удалось отправить лог админу: %s", e)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    text = (
        "<b>Привет 👋</b>\n\n"
        "Я умный Telegram-бот на Gemini.\n"
        "Могу помнить недавний контекст беседы, учитывать ответы на мои сообщения "
        "и отвечать более живо, а не сухо.\n\n"
        "<b>Команды:</b>\n"
        "/start — запуск\n"
        "/help — помощь\n"
        "/clear — очистить память диалога\n"
        "/myid — показать твой Telegram ID\n\n"
        "Просто напиши мне что-нибудь 🙂"
    )

    await update.message.reply_text(
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_keyboard(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    text = (
        "<b>Как пользоваться ботом</b>\n\n"
        "• Просто пиши вопрос обычным сообщением\n"
        "• Можешь ответить на моё сообщение — я учту этот контекст\n"
        "• /clear — очистить память текущего диалога\n"
        "• /myid — узнать свой Telegram ID\n\n"
        "<b>Примеры:</b>\n"
        "• Объясни, что такое VPN простыми словами\n"
        "• А теперь короче\n"
        "• Сравни iPhone 15 и 16\n"
    )

    await update.message.reply_text(
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_keyboard(),
    )


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None:
        return

    clear_history(update.effective_user.id)

    if update.message:
        await update.message.reply_text(
            "Память этого диалога очищена 🧹",
            reply_markup=get_main_keyboard(),
        )


async def myid_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return

    await update.message.reply_text(f"Твой Telegram ID: {update.effective_user.id}")


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or update.effective_user is None:
        return

    await query.answer()

    if query.data == "clear_memory":
        clear_history(update.effective_user.id)
        await query.message.reply_text("Память очищена 🧹", reply_markup=get_main_keyboard())

    elif query.data == "show_help":
        await query.message.reply_text(
            "Напиши вопрос текстом или ответь на одно из моих сообщений.\n"
            "Команда /clear очищает контекст диалога.",
            reply_markup=get_main_keyboard(),
        )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.message.text is None or update.effective_user is None:
        return

    user_text = update.message.text.strip()
    if not user_text:
        await update.message.reply_text("Напиши вопрос текстом.")
        return

    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name

    logger.info(
        "ID: %s | Username: %s | Имя: %s | Сообщение: %s",
        user_id,
        f"@{username}" if username else "нет",
        first_name if first_name else "без имени",
        user_text,
    )

    await send_admin_log(
        context=context,
        user_id=user_id,
        username=username,
        first_name=first_name,
        text=user_text,
    )

    reply_context = None
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        replied_user = update.message.reply_to_message.from_user
        replied_text = update.message.reply_to_message.text or update.message.reply_to_message.caption

        if replied_user.is_bot and replied_text:
            reply_context = replied_text

    save_to_history(user_id, "user", user_text)

    try:
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action=ChatAction.TYPING,
        )

        answer = ask_gemini(
            user_id=user_id,
            user_text=user_text,
            reply_context=reply_context,
        )

        save_to_history(user_id, "assistant", answer)

        max_len = 4000
        if len(answer) <= max_len:
            await update.message.reply_text(
                answer,
                reply_markup=get_main_keyboard(),
            )
        else:
            for i in range(0, len(answer), max_len):
                await update.message.reply_text(
                    answer[i:i + max_len],
                    reply_markup=get_main_keyboard() if i == 0 else None,
                )

    except Exception as e:
        logger.exception("Ошибка при обработке сообщения: %s", e)
        safe_error = escape(str(e))
        await update.message.reply_text(
            f"<b>Ошибка:</b>\n<code>{safe_error}</code>",
            parse_mode=ParseMode.HTML,
        )


async def on_startup() -> None:
    await telegram_app.initialize()
    await bot.set_webhook(url=WEBHOOK_URL)
    logger.info("Webhook установлен: %s", WEBHOOK_URL)


@app.on_event("startup")
async def startup_event() -> None:
    await on_startup()


@app.get("/")
async def root() -> dict:
    return {"ok": True, "message": "Bot is running"}


@app.post(WEBHOOK_SECRET_PATH)
async def telegram_webhook(request: Request) -> dict:
    data = await request.json()
    update = Update.de_json(data, bot)

    await telegram_app.process_update(update)
    return {"ok": True}


telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CommandHandler("help", help_command))
telegram_app.add_handler(CommandHandler("clear", clear_command))
telegram_app.add_handler(CommandHandler("myid", myid_command))
telegram_app.add_handler(CallbackQueryHandler(button_handler))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
