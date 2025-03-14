import asyncio
import datetime
import logging
import os
import sys
import nest_asyncio
from threading import Thread
from zoneinfo import ZoneInfo  # <-- Добавлено для работы с часовыми поясами

from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# Если работаете на Windows, иногда нужно установить политику цикла событий
if sys.platform.startswith('win'):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
nest_asyncio.apply()

app = Flask(__name__)

@app.route('/')
def index():
    return "OK"  # Health check endpoint

###############################################################################
# Настройки часового пояса и таймера
###############################################################################
ekb_tz = ZoneInfo("Asia/Yekaterinburg")  # Часовой пояс Екатеринбурга
TARGET_DATETIME = datetime.datetime(2025, 7, 1, 23, 59, 0, tzinfo=ekb_tz)  
UPDATE_INTERVAL = 60
BAR_LENGTH = 16

###############################################################################
# Логика бота (команды /start и /countdown)
###############################################################################
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = (
        "Привет! Я бот для обратного отсчёта.\n\n"
        "Используй /countdown, чтобы запустить таймер в этой теме группы.\n"
        "Я буду публиковать и обновлять сообщение именно здесь."
    )
    await update.message.reply_text(msg)

async def countdown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    thread_id = update.message.message_thread_id

    # Если нет "start_time", инициализируем текущим временем в Екатеринбурге
    if "start_time" not in context.bot_data:
        context.bot_data["start_time"] = datetime.datetime.now(ekb_tz)
    start_time = context.bot_data["start_time"]

    # Отправим первое сообщение
    sent_message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Таймер запускается...",
        message_thread_id=thread_id
    )

    while True:
        # Текущее время в Екатеринбурге
        now = datetime.datetime.now(ekb_tz)
        diff = TARGET_DATETIME - now

        # Проверяем, не истекло ли время
        if diff.total_seconds() <= 0:
            final_text = "Таймер завершён!"
            time_button = InlineKeyboardButton("0д 00:00", callback_data="none")
            progress_button = InlineKeyboardButton("[────────]100%", callback_data="none")
            keyboard = [[time_button], [progress_button]]
            await sent_message.edit_text(final_text, reply_markup=InlineKeyboardMarkup(keyboard))
            break

        # Считаем дни, часы, минуты, секунды до завершения
        days = diff.days
        seconds_left = diff.seconds
        hours = seconds_left // 3600
        minutes = (seconds_left % 3600) // 60
        seconds = seconds_left % 60

        # Форматируем строку оставшегося времени
        if UPDATE_INTERVAL >= 60:
            # Если обновляем раз в минуту, сек. не нужны
            time_str = f"{days}д {hours:02d}ч {minutes:02d}м"
        else:
            time_str = f"{days}д {hours:02d}ч {minutes:02d}м {seconds:02d}с"

        # Прогресс-бар
        total_duration = (TARGET_DATETIME - start_time).total_seconds()
        elapsed = (now - start_time).total_seconds()
        ratio = (elapsed / total_duration) if total_duration > 0 else 0
        ratio_percent = int(ratio * 100)
        filled_len = int(BAR_LENGTH * ratio)
        bar_str = "█" * filled_len + "─" * (BAR_LENGTH - filled_len)
        progress_str = f"[{bar_str}]{ratio_percent}%"

        # Две кнопки: остаток времени и прогресс
        time_button = InlineKeyboardButton(time_str, callback_data="none")
        progress_button = InlineKeyboardButton(progress_str, callback_data="none")
        keyboard = [[time_button], [progress_button]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        date_str = TARGET_DATETIME.strftime("%Y-%m-%d %H:%M")  # Просто формат для info
        new_text = f"До {date_str} (ЕКБ) осталось:"

        try:
            await sent_message.edit_text(new_text, reply_markup=reply_markup)
        except Exception as e:
            logging.error(f"Ошибка при редактировании: {e}")
            break

        # Ждём UPDATE_INTERVAL секунд и обновляем
        await asyncio.sleep(UPDATE_INTERVAL)

###############################################################################
# Запуск бота (polling) в отдельном потоке
###############################################################################
async def bot_main():
    from dotenv import load_dotenv
    load_dotenv()  # Если используете .env локально

    BOT_TOKEN = os.getenv("BOT_TOKEN")
    if not BOT_TOKEN:
        raise ValueError("Токен бота не найден в переменных окружения!")

    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("countdown", countdown))
    # Отключаем установку signal handlers в дочернем потоке
    await application.run_polling(stop_signals=None)

def run_bot():
    asyncio.run(bot_main())

###############################################################################
# Запуск Flask (health check) в главном потоке
###############################################################################
def run_flask():
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port)

###############################################################################
# Точка входа
###############################################################################
if __name__ == "__main__":
    # 1) Запускаем бота в отдельном потоке
    t = Thread(target=run_bot)
    t.start()

    # 2) Запускаем Flask (блокирующий вызов) в основном потоке
    run_flask()
