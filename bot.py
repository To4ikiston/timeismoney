import asyncio
import datetime
import logging
import os
from zoneinfo import ZoneInfo

from quart import Quart, request
from hypercorn.asyncio import serve
from hypercorn.config import Config
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, RetryAfter
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
START_DATE = datetime.datetime(2025, 3, 14, 0, 0, tzinfo=ekb_tz)
END_DATE = datetime.datetime(2025, 7, 1, 23, 59, tzinfo=ekb_tz)
UPDATE_INTERVAL = 60  # Обновление каждые 10 секунд

app = Quart(__name__)
application = None

active_timers = {}  # {chat_id: {"message_id": int, "task": asyncio.Task}}

async def calculate_progress() -> tuple:
    """Возвращает (дней, часов, минут, секунд, процент выполнения)"""
    now = datetime.datetime.now(ekb_tz)
    
    if now < START_DATE:
        time_left = END_DATE - START_DATE
        progress = 0.0
    elif now > END_DATE:
        return 0, 0, 0, 0, 100
    else:
        time_left = END_DATE - now
        total_duration = (END_DATE - START_DATE).total_seconds()
        elapsed = (now - START_DATE).total_seconds()
        progress = min(elapsed / total_duration, 1.0)  # Защита от переполнения

    days = time_left.days
    hours, rem = divmod(time_left.seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    
    return days, hours, minutes, seconds, int(progress * 100)

async def update_timer_message(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    def get_day_form(days: int) -> str:
        if 11 <= days % 100 <= 14:
            return "дней"
        remainder = days % 10
        if remainder == 1:
            return "день"
        elif 2 <= remainder <= 4:
            return "дня"
        else:
            return "дней"
        
    try:
        data = active_timers.get(chat_id)
        if not data:
            return

        days, h, m, s, progress = await calculate_progress()
        current_state = (days, h, m, s, progress)
        
        # Пропускаем обновление если состояние не изменилось
        if data.get("last_state") == current_state:
            return
            
        data["last_state"] = current_state
        
        # Формируем прогресс-бар
        filled_len = int(BAR_LENGTH * (progress / 100))
        bar_str = "█" * filled_len + "─" * (BAR_LENGTH - filled_len)
        
        # Создаем кнопки
        time_button = InlineKeyboardButton(
            f"{days} {get_day_form(days)} {h:02d}ч {m:02d}м", 
            callback_data="none"
        )
        progress_button = InlineKeyboardButton(
            f"[{bar_str}] {progress}%", 
            callback_data="none"
        )
        
        # Обновляем сообщение
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=data["message_id"],
            text="ОСТАЛОСЬ",
            reply_markup=InlineKeyboardMarkup([[time_button], [progress_button]])
        )            
    except BadRequest as e:
        if "not modified" not in str(e):
            logger.error(f"Ошибка редактирования: {e}")
    except RetryAfter as e:
        logger.warning(f"Лимит запросов! Ждем {e.retry_after} сек.")
        await asyncio.sleep(e.retry_after)
    except Exception as e:
        logger.error(f"Неизвестная ошибка: {e}")

async def timer_task(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Задача для периодического обновления"""
    while True:
        try:
            if chat_id not in active_timers:
                break
                
            await update_timer_message(chat_id, context)
            await asyncio.sleep(UPDATE_INTERVAL)
            
        except asyncio.CancelledError:
            logger.info("Задача отменена")
            break
        except Exception as e:
            logger.error(f"Ошибка в таймер-задаче: {e}")
            await asyncio.sleep(10)

@app.route('/health')
async def health():
    return 'OK'

@app.route('/telegram', methods=['POST'])
async def telegram_webhook():
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != SECRET_TOKEN:
        return "Unauthorized", 401
        
    try:
        update = Update.de_json(await request.get_json(), application.bot)
        await application.process_update(update)
        return 'OK', 200
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return 'ERROR', 500

async def countdown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    thread_id = update.message.message_thread_id  # Получаем ID темы
    
    # Останавливаем предыдущий таймер
    if chat_id in active_timers:
        try:
            active_timers[chat_id]["task"].cancel()
        except:
            pass
        del active_timers[chat_id]

    # Создаем новое сообщение
    try:
        msg = await context.bot.send_message(
            chat_id=chat_id,
            text="🔄 Запускаю таймер...",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Инициализация...", callback_data="none")]]),  # Запятая
            message_thread_id=thread_id  # Теперь переменная определена
        )
        
        task = asyncio.create_task(timer_task(chat_id, context))
        active_timers[chat_id] = {
            "message_id": msg.message_id,
            "task": task
        }
        
        await update_timer_message(chat_id, context)
        
    except Exception as e:
        logger.error(f"Ошибка запуска таймера: {e}")
        await context.bot.send_message(chat_id, "❌ Ошибка запуска таймера")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🚀 Команды бота:\n"
        "/countdown - Запустить таймер\n"
        "/help - Показать справку\n\n"
        "Таймер отсчитывает время с 14.03.2025 до 01.07.2025"
    )
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=text
    )

async def main():
    global application
    max_attempts = 3  # Максимум 3 попытки
    attempt = 0
    
    while attempt < max_attempts:
        try:
            application = ApplicationBuilder().token(BOT_TOKEN).build()
            application.add_handler(CommandHandler("countdown", countdown))
            application.add_handler(CommandHandler("help", help_command))
            
            await application.initialize()
            
            # Удаляем старый вебхук
            await application.bot.delete_webhook()
            logger.info("Старый вебхук удален")
            
            # Устанавливаем новый вебхук
            await application.bot.set_webhook(
                url=f"{APP_URL}/telegram",
                secret_token=SECRET_TOKEN
            )
            logger.info(f"Новый вебхук установлен: {APP_URL}/telegram")
            
            # Проверяем статус вебхука (добавьте это)
            webhook_info = await application.bot.get_webhook_info()
            logger.info(f"Текущий вебхук: {webhook_info.url}")
            
            # Если всё успешно - выходим из цикла
            break
            
        except Exception as e:
            attempt += 1
            logger.error(f"Попытка {attempt}/{max_attempts} не удалась: {e}")
            if attempt == max_attempts:
                raise
            await asyncio.sleep(5 * attempt)  # Увеличиваем задержку с каждой попыткой
    
    # Запускаем сервер
    config = Config()
    config.bind = [f"0.0.0.0:{PORT}"]
    await serve(app, config)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
    finally:
        # Очистка при завершении
        for chat_id in list(active_timers.keys()):
            try:
                active_timers[chat_id]["task"].cancel()
            except:
                pass
