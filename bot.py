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
APP_URL = os.getenv("APP_URL")  # Пример: https://your-domain.com
PORT = int(os.getenv("PORT", "8000"))
SECRET_TOKEN = os.getenv("SECRET_TOKEN")
BAR_LENGTH = 16 
# Часовой пояс и даты
ekb_tz = ZoneInfo("Asia/Yekaterinburg")
START_DATE = datetime.datetime(2025, 3, 14, 0, 0, tzinfo=ekb_tz)
END_DATE = datetime.datetime(2025, 7, 1, 23, 59, tzinfo=ekb_tz)
UPDATE_INTERVAL = 60  # Обновление каждые 60 секунд

# Инициализация приложений
app = Quart(__name__)
application = None  # Инициализируется в main()

# Глобальное хранилище (для простоты)
active_timers = {}  # Формат: {chat_id: {"message_id": int, "task": asyncio.Task}}

async def calculate_progress() -> tuple:
    """Возвращает (дней осталось, процент выполнения)"""
    now = datetime.datetime.now(ekb_tz)
    total_seconds = (END_DATE - START_DATE).total_seconds()
    elapsed = (now - START_DATE).total_seconds()
    
    if elapsed < 0:
        return (END_DATE - START_DATE).days, 0.0
    
    progress = min(elapsed / total_seconds, 1.0) if total_seconds > 0 else 0.0
    days_left = (END_DATE - now).days
    return days_left, progress

async def update_timer_message(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Обновляет сообщение с таймером"""
    try:
        days_left, progress = await calculate_progress()
        percent = int(progress * 100)
        
        # Прогресс-бар (20 символов)
        bar = "⬛" * int(BAR_LENGTH * progress) + "⬜" * (BAR_LENGTH - int(BAR_LENGTH * progress))  # <-- Здесь 16
        
        # Большая кнопка с текстом
        text = f"Дней осталось: {days_left}\n{bar} {percent}%"
        keyboard = [[InlineKeyboardButton(text, callback_data="refresh")]]
        
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=active_timers[chat_id]["message_id"],
            text="⏳ Таймер до 1 июля 2025 (ЕКБ):",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error(f"Ошибка обновления: {e}")

async def timer_task(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Фоновая задача для обновления таймера"""
    while True:
        if chat_id not in active_timers:
            break
            
        await update_timer_message(chat_id, context)
        await asyncio.sleep(UPDATE_INTERVAL)

@app.route('/health')
async def health():
    return 'OK'

@app.route('/telegram', methods=['POST'])
async def telegram_webhook():
    """Обработчик вебхуков Telegram"""
    try:
        update = Update.de_json(await request.get_json(), application.bot)
        await application.process_update(update)
        return 'OK', 200
    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
        return 'ERROR', 500

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    await update.message.reply_text(
        "⏰ Я бот-таймер!\n"
        "Используй /timer в группе или чате, чтобы запустить обратный отсчёт до 1 июля 2025."
    )

async def timer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /timer"""
    chat_id = update.effective_chat.id
    
    # Останавливаем предыдущий таймер
    if chat_id in active_timers:
        active_timers[chat_id]["task"].cancel()
    
    # Создаем новое сообщение
    msg = await context.bot.send_message(
        chat_id=chat_id,
        text="🔄 Запускаю таймер...",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Инициализация...", callback_data="none")]])
    )
    
    # Запускаем фоновую задачу
    task = asyncio.create_task(timer_task(chat_id, context))
    active_timers[chat_id] = {
        "message_id": msg.message_id,
        "task": task
    }
    
    # Первое обновление
    await update_timer_message(chat_id, context)

async def main():
    global application
    
    # Инициализация бота
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    
    # Регистрация обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("timer", timer_command))
    
    # Установка вебхука
    await application.bot.set_webhook(
        url=f"{APP_URL}/telegram",
        secret_token=SECRET_TOKEN
    )
    
    # Запуск сервера
    config = Config()
    config.bind = [f"0.0.0.0:{PORT}"]
    await serve(app, config)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
