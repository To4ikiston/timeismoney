import asyncio
import datetime
import logging
import os
from zoneinfo import ZoneInfo

from quart import Quart, request
from hypercorn.asyncio import serve
from hypercorn.config import Config
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
TARGET_DATETIME = datetime.datetime(2025, 3, 14, 0, 0, tzinfo=ekb_tz)  # Ваша целевая дата
UPDATE_INTERVAL = 1  # Обновление каждую секунду

# Инициализация приложений
app = Quart(__name__)
application = None

# Глобальное хранилище
active_timers = {}  # {chat_id: {"message_id": int, "task": asyncio.Task, "thread_id": int}}

async def calculate_progress() -> tuple:
    """Возвращает (дней, часов, минут, секунд, процент выполнения)"""
    now = datetime.datetime.now(ekb_tz)
    diff = TARGET_DATETIME - now
    total_seconds = diff.total_seconds()
    
    if total_seconds <= 0:
        return 0, 0, 0, 0, 100

    days = diff.days
    hours, rem = divmod(diff.seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    
    total_duration = (TARGET_DATETIME - datetime.datetime.now(ekb_tz)).total_seconds()
    progress = min((total_duration - total_seconds) / total_duration, 1.0)
    
    return days, hours, minutes, seconds, int(progress * 100)

async def update_timer_message(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    try:
        data = active_timers.get(chat_id)
        if not data:
            return

        days, h, m, s, progress = await calculate_progress()
        filled_len = int(BAR_LENGTH * (progress / 100))
        bar_str = "█" * filled_len + "─" * (BAR_LENGTH - filled_len)
        
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
            text=f"До {TARGET_DATETIME.strftime('%Y-%m-%d %H:%M')} (ЕКБ) осталось:",
            reply_markup=InlineKeyboardMarkup([[time_button], [progress_button]]),
            message_thread_id=data["thread_id"]
        )
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
    
    if chat_id in active_timers:
        active_timers[chat_id]["task"].cancel()
    
    msg = await context.bot.send_message(
        chat_id=chat_id,
        text="🔄 Запускаю таймер...",
        message_thread_id=thread_id,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Инициализация...", callback_data="none")]])
    )
    
    active_timers[chat_id] = {
        "message_id": msg.message_id,
        "task": asyncio.create_task(timer_task(chat_id, context)),
        "thread_id": thread_id
    }
    
    await update_timer_message(chat_id, context)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    thread_id = update.message.message_thread_id
    text = (
        "🚀 Доступные команды:\n"
        "/countdown - Запустить/перезапустить таймер\n"
        "/help - Показать это сообщение"
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
