import asyncio
import datetime
import logging
import sys
import nest_asyncio
import os  # Добавлено
from dotenv import load_dotenv  # Добавлено

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

###############################################################################
# Загружаем переменные из .env
###############################################################################
load_dotenv()  # Добавлено

###############################################################################
# Если вы работаете на Windows, иногда нужна эта строчка, чтобы избежать конфликтов
###############################################################################
if sys.platform.startswith('win'):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
nest_asyncio.apply()

###############################################################################
# Логирование для отладки (можно выключить)
###############################################################################
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

###############################################################################
# НАСТРОЙКИ
###############################################################################

TARGET_DATETIME = datetime.datetime(2025, 7, 1, 23, 59, 0)

# Интервал обновления (в секундах)
UPDATE_INTERVAL = 60
BAR_LENGTH = 16

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обработчик команды /start
    """
    msg = (
        "Привет! Я бот для обратного отсчёта.\n\n"
        "Используй /countdown, чтобы запустить таймер в этой теме группы.\n"
        "Бот будет публиковать и обновлять сообщение именно здесь."
    )
    await update.message.reply_text(msg)

async def countdown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Запускает обратный отсчёт.
    Если команду вызвали в теме, берём thread_id, чтобы отправлять/обновлять сообщение в ту же тему.
    """
    # Если команда вызвана в теме супергруппы, у нас будет ID темы:
    thread_id = update.message.message_thread_id

    # Запоминаем время начала (для прогресса)
    if "start_time" not in context.bot_data:
        context.bot_data["start_time"] = datetime.datetime.now()
    start_time = context.bot_data["start_time"]

    # Отправим первое сообщение в ту же тему (message_thread_id=thread_id)
    sent_message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Таймер запускается...",
        message_thread_id=thread_id
    )

    while True:
        now = datetime.datetime.now()
        diff = TARGET_DATETIME - now

        # Проверка окончания отсчёта
        if diff.total_seconds() <= 0:
            final_text = "Таймер завершён!"
            time_button = InlineKeyboardButton("0д 00:00", callback_data="none")
            progress_button = InlineKeyboardButton("[────────]100%", callback_data="none")
            keyboard = [[time_button], [progress_button]]
            await sent_message.edit_text(final_text, reply_markup=InlineKeyboardMarkup(keyboard))
            break

        days = diff.days
        seconds_left = diff.seconds
        hours = seconds_left // 3600
        minutes = (seconds_left % 3600) // 60
        seconds = seconds_left % 60

        # Форматируем время (убираем секунды, если UPDATE_INTERVAL >= 60)
        if UPDATE_INTERVAL >= 60:
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

        # Формируем inline-клавиатуру
        time_button = InlineKeyboardButton(time_str, callback_data="none")
        progress_button = InlineKeyboardButton(progress_str, callback_data="none")
        keyboard = [[time_button], [progress_button]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        date_str = TARGET_DATETIME.strftime("%Y-%m-%d %H:%M")
        new_text = f"До {date_str} осталось:"

        # Обновляем сообщение
        try:
            await sent_message.edit_text(new_text, reply_markup=reply_markup)
        except Exception as e:
            logging.error(f"Ошибка при редактировании: {e}")
            break

        # Ждём перед следующим обновлением
        await asyncio.sleep(UPDATE_INTERVAL)

async def main() -> None:
    # Получаем токен из переменных окружения
    BOT_TOKEN = os.getenv("BOT_TOKEN")  # Добавлено
    
    # Проверка на случай, если токен не найден
    if not BOT_TOKEN:
        raise ValueError("Токен бота не найден в переменных окружения!")
    
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("countdown", countdown))
    await application.run_polling()

if __name__ == "__main__":
    asyncio.run(main())