import asyncio
import datetime
import logging
import os
from zoneinfo import ZoneInfo

from quart import Quart, request
from hypercorn.asyncio import serve
from hypercorn.config import Config
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Настройки логгера
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация
BOT_TOKEN = os.getenv("BOT_TOKEN")
APP_URL = os.getenv("APP_URL")
PORT = int(os.getenv("PORT", "8000"))
SECRET_TOKEN = os.getenv("SECRET_TOKEN")
BAR_LENGTH = 16

# Часовой пояс и даты
ekb_tz = ZoneInfo("Asia/Yekaterinburg")
START_DATE = datetime.datetime(2025, 3, 14, 0, 0, tzinfo=ekb_tz)  # Начало отсчёта
END_DATE = datetime.datetime(2025, 7, 1, 23, 59, tzinfo=ekb_tz)    # Конец отсчёта
UPDATE_INTERVAL = 1  # Обновление каждую секунду

# Инициализация приложений
app = Quart(__name__)
application = None

# Глобальное хранилище
active_timers = {}  # {chat_id: {"message_id": int, "task": asyncio.Task, "thread_id": int, "last_state": tuple}}

async def calculate_progress() -> tuple:
    """Возвращает (дней осталось, часов, минут, секунд, процент выполнения)"""
    now = datetime.datetime.now(ekb_tz)
    logger.info(f"Текущее время сервера: {now}")
    
    if now < START_DATE:
        # Время до начала отсчёта
        time_left = END_DATE - START_DATE
        progress = 0.0
    elif now > END_DATE:
        # Время истекло
        return 0, 0, 0, 0, 100
    else:
        # Активный отсчёт
        time_left = END_DATE - now
        total_duration = (END_DATE - START_DATE).total_seconds()
        elapsed = (now - START_DATE).total_seconds()
        progress = elapsed / total_duration

    days = time_left.days
    hours, rem = divmod(time_left.seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    
    logger.info(f"Расчёт: days={days}, h={hours}, m={minutes}, s={seconds}, progress={progress}")
    return days, hours, minutes, seconds, int(progress * 100)

async def update_timer_message(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    try:
        data = active_timers.get(chat_id)
        if not data:
            return

        days, h, m, s, progress = await calculate_progress()
        
        # Дебаг-логи
        logger.info(f"Обновление: {days}д {h:02d}:{m:02d}:{s:02d} ({progress}%)")
        
        filled_len = int(BAR_LENGTH * (progress / 100))
        bar_str = "█" * filled_len + "─" * (BAR_LENGTH - filled_len)
        
        # Проверяем изменения
        current_state = (days, h, m, s, progress)
        if data.get("last_state") == current_state:
            return
        
        data["last_state"] = current_state
        
        # Формируем сообщение
        time_button = InlineKeyboardButton(
            f"{days}д {h:02d}:{m:02d}:{s:02d}", 
            callback_data="none"
        )
        progress_button = InlineKeyboardButton(
            f"[{bar_str}]{progress}%", 
            callback_data="none"
        )
        
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=data["message_id"],
            text=f"⏳ 14.03 — 01.07.2025",
            reply_markup=InlineKeyboardMarkup([[time_button], [progress_button]])
        )
    except BadRequest as e:
        if "not modified" not in str(e):
            logger.error(f"Ошибка: {e}")
    except Exception as e:
        logger.error(f"Ошибка обновления: {e}")

async def timer_task(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    while chat_id in active_timers:
        await update_timer_message(chat_id, context)
        await asyncio.sleep(UPDATE_INTERVAL)

@app.route('/health')
async def health():
    return 'OK'

@app.route('/telegram', methods=['POST'])
async def telegram_webhook():
    try:
        update = Update.de_json(await request.get_json(), application.bot)
        await application.process_update(update)
        return 'OK', 200
    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
        return 'ERROR', 500

async def countdown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /countdown"""
    chat_id = update.effective_chat.id
    thread_id = update.message.message_thread_id
    
    # Останавливаем предыдущий таймер
    if chat_id in active_timers:
        active_timers[chat_id]["task"].cancel()
    
    # Создаем сообщение в теме
    msg = await context.bot.send_message(
        chat_id=chat_id,
        text="🔄 Запускаю таймер...",
        message_thread_id=thread_id,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Инициализация...", callback_data="none")]])
    )
    
    active_timers[chat_id] = {
        "message_id": msg.message_id,
        "task": asyncio.create_task(timer_task(chat_id, context)),
        "thread_id": thread_id,
        "last_state": None
    }
    
    await update_timer_message(chat_id, context)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    thread_id = update.message.message_thread_id
    text = (
        "🚀 Команды бота:\n"
        "/countdown - Запустить таймер\n"
        "/help - Показать справку\n\n"
        "Таймер отсчитывает время с 14.03.2025 до 01.07.2025"
    )
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text,
        message_thread_id=thread_id
    )

async def main():
    global application
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("countdown", countdown))
    application.add_handler(CommandHandler("help", help_command))
    
    await application.initialize()
    await application.bot.set_webhook(
        url=f"{APP_URL}/telegram",
        secret_token=SECRET_TOKEN
    )
    
    config = Config()
    config.bind = [f"0.0.0.0:{PORT}"]
    await serve(app, config)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
