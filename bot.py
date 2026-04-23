import os
import asyncio
import uuid
import hashlib
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice, PreCheckoutQuery
from supabase import create_client, Client
import base64
import json

# Конфигурация
BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
WORKER_URL = os.getenv("WORKER_URL")
YOOKASSA_TOKEN = os.getenv("YOOKASSA_TOKEN", "")  # Токен ЮKassa

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Тарифы (цены в рублях)
PRICES = {
    "7": {"days": 7, "price": 35, "name": "7 дней"},
    "30": {"days": 30, "price": 75, "name": "30 дней"},
    "forever": {"days": 36500, "price": 400, "name": "Навсегда"}
}

# Клавиатуры
def main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Пробный ключ (1 день)", callback_data="trial")],
        [InlineKeyboardButton(text="💳 Купить подписку", callback_data="buy")],
        [InlineKeyboardButton(text="🔑 Мои ключи", callback_data="mykeys")],
        [InlineKeyboardButton(text="ℹ️ Инструкция", callback_data="help")]
    ])

def buy_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 7 дней - 35₽", callback_data="buy_7")],
        [InlineKeyboardButton(text="💳 30 дней - 75₽", callback_data="buy_30")],
        [InlineKeyboardButton(text="💳 Навсегда - 400₽", callback_data="buy_forever")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back")]
    ])

def admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🎁 Выдать ключ", callback_data="admin_give")],
        [InlineKeyboardButton(text="🗑 Удалить ключ", callback_data="admin_delete")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back")]
    ])

# Генерация device fingerprint
def get_device_fingerprint(user_id: int, message: types.Message) -> str:
    """Создает уникальный отпечаток устройства"""
    data = f"{user_id}_{message.from_user.language_code}"
    return hashlib.sha256(data.encode()).hexdigest()[:16]

# Проверка лимитов устройств
async def check_device_limit(user_id: int, device_fp: str, subscription_type: str) -> tuple[bool, str]:
    """Проверяет, можно ли добавить устройство"""
    result = supabase.table("subscriptions").select("*").eq("user_id", user_id).execute()
    
    if not result.data:
        return True, ""
    
    active_subs = [s for s in result.data if datetime.fromisoformat(s["expires_at"]) > datetime.utcnow()]
    
    if not active_subs:
        return True, ""
    
    # Проверяем устройства
    devices = set()
    for sub in active_subs:
        devices.add(sub["device_fingerprint"])
    
    max_devices = 1 if subscription_type == "trial" else 4
    
    if device_fp in devices:
        return True, ""  # Это устройство уже зарегистрировано
    
    if len(devices) >= max_devices:
        return False, f"Достигнут лимит устройств ({max_devices})"
    
    return True, ""

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        "🚀 WopeVPN - Быстрый и надежный VPN для игр и повседневки\n\n"
        "🎁 Получи пробный ключ на 1 день бесплатно!\n"
        "💎 Платные подписки - до 4 устройств одновременно",
        reply_markup=main_keyboard()
    )

@dp.callback_query(F.data == "back")
async def back_to_main(callback: types.CallbackQuery):
    await callback.message.edit_text(
        f"👋 WopeVPN - Главное меню\n\n"
        "🚀 Быстрый и надежный VPN для игр и повседневки",
        reply_markup=main_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "trial")
async def trial_key(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    device_fp = get_device_fingerprint(user_id, callback.message)
    
    # Проверяем, есть ли уже пробный ключ
    result = supabase.table("subscriptions").select("*").eq("user_id", user_id).eq("subscription_type", "trial").execute()
    
    if result.data:
        await callback.answer("❌ Пробный ключ уже был выдан", show_alert=True)
        return
    
    # Проверяем лимит устройств
    can_add, error = await check_device_limit(user_id, device_fp, "trial")
    if not can_add:
        await callback.answer(f"❌ {error}", show_alert=True)
        return
    
    # Создаем подписку
    sub_id = str(uuid.uuid4())
    expires_at = datetime.utcnow() + timedelta(days=1)
    
    supabase.table("subscriptions").insert({
        "id": sub_id,
        "user_id": user_id,
        "device_fingerprint": device_fp,
        "subscription_type": "trial",
        "expires_at": expires_at.isoformat(),
        "created_at": datetime.utcnow().isoformat()
    }).execute()
    
    # Генерируем subscription URL
    sub_url = f"{WORKER_URL}/sub?token={sub_id}"
    
    await callback.message.edit_text(
        f"🎉 WopeVPN - Пробный ключ создан!\n\n"
        f"⏰ Действует до: {expires_at.strftime('%d.%m.%Y %H:%M')}\n"
        f"📱 Устройств: 1\n\n"
        f"🔗 Subscription URL:\n"
        f"<code>{sub_url}</code>\n\n"
        f"📲 Скопируй ссылку и добавь в приложение:\n"
        f"• v2rayNG\n• Hiddify\n• Shadowrocket\n• V2Box",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back")]
        ])
    )
    await callback.answer()

@dp.callback_query(F.data == "buy")
async def buy_menu(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "💳 Выбери тариф:\n\n"
        "✨ Все платные подписки:\n"
        "• До 4 устройств одновременно\n"
        "• Полная скорость\n"
        "• Поддержка 24/7\n\n"
        "💳 Оплата картой (Visa, MasterCard, МИР)\n"
        "💰 Деньги поступают мгновенно",
        reply_markup=buy_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("buy_"))
async def process_buy(callback: types.CallbackQuery):
    plan = callback.data.split("_")[1]
    
    if plan not in PRICES:
        await callback.answer("❌ Неверный тариф", show_alert=True)
        return
    
    price_info = PRICES[plan]
    
    # Проверяем наличие токена ЮKassa
    if not YOOKASSA_TOKEN:
        await callback.message.edit_text(
            f"💳 Оплата подписки на {price_info['name']}\n\n"
            f"💰 Стоимость: {price_info['price']}₽\n\n"
            f"Для оплаты переведи {price_info['price']}₽ на карту:\n"
            f"<code>2200 7007 XXXX XXXX</code>\n\n"
            f"После оплаты отправь скриншот чека боту\n"
            f"и напиши команду /paid",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="buy")]
            ])
        )
        await callback.answer()
        return
    
    # Создаем инвойс для оплаты через ЮKassa
    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title=f"WopeVPN - {price_info['name']}",
        description=f"Подписка на {price_info['name']}\n• До 4 устройств\n• Полная скорость\n• Поддержка 24/7",
        payload=f"subscription_{plan}_{callback.from_user.id}",
        provider_token=YOOKASSA_TOKEN,
        currency="RUB",
        prices=[LabeledPrice(label=f"WopeVPN {price_info['name']}", amount=price_info['price'] * 100)]  # в копейках
    )
    
    await callback.answer("💳 Счет отправлен!")

# Обработка предварительной проверки платежа
@dp.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

# Обработка успешного платежа
@dp.message(F.successful_payment)
async def successful_payment_handler(message: types.Message):
    payment = message.successful_payment
    
    # Извлекаем данные из payload
    payload_parts = payment.invoice_payload.split("_")
    if len(payload_parts) != 3 or payload_parts[0] != "subscription":
        await message.answer("❌ Ошибка обработки платежа. Свяжись с поддержкой.")
        return
    
    plan = payload_parts[1]
    user_id = int(payload_parts[2])
    
    if plan not in PRICES:
        await message.answer("❌ Неверный тариф")
        return
    
    price_info = PRICES[plan]
    
    # Создаем подписку
    device_fp = get_device_fingerprint(user_id, message)
    sub_id = str(uuid.uuid4())
    expires_at = datetime.utcnow() + timedelta(days=price_info['days'])
    
    try:
        supabase.table("subscriptions").insert({
            "id": sub_id,
            "user_id": user_id,
            "device_fingerprint": device_fp,
            "subscription_type": plan,
            "expires_at": expires_at.isoformat(),
            "created_at": datetime.utcnow().isoformat()
        }).execute()
        
        sub_url = f"{WORKER_URL}/sub?token={sub_id}"
        
        await message.answer(
            f"✅ Оплата прошла успешно!\n\n"
            f"🎉 WopeVPN - Твоя подписка активирована!\n\n"
            f"📦 Тариф: {price_info['name']}\n"
            f"⏰ Действует до: {expires_at.strftime('%d.%m.%Y %H:%M')}\n"
            f"📱 Устройств: до 4\n\n"
            f"🔗 Subscription URL:\n"
            f"<code>{sub_url}</code>\n\n"
            f"📲 Скопируй ссылку и добавь в приложение:\n"
            f"• v2rayNG\n• Hiddify\n• Shadowrocket\n• V2Box\n\n"
            f"❓ Нужна помощь? Пиши @твой_username",
            parse_mode="HTML"
        )
        
        # Уведомляем админа
        await bot.send_message(
            ADMIN_ID,
            f"💰 Новая покупка!\n\n"
            f"👤 User: {message.from_user.id} (@{message.from_user.username or 'без username'})\n"
            f"📦 Тариф: {price_info['name']}\n"
            f"💵 Сумма: {price_info['price']}₽\n"
            f"🆔 Subscription ID: {sub_id}"
        )
        
    except Exception as e:
        await message.answer(
            f"❌ Ошибка создания подписки: {str(e)}\n"
            f"Деньги будут возвращены. Свяжись с @твой_username"
        )
        await bot.send_message(ADMIN_ID, f"❌ Ошибка создания подписки: {str(e)}\nUser: {user_id}")


@dp.callback_query(F.data == "mykeys")
async def my_keys(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    result = supabase.table("subscriptions").select("*").eq("user_id", user_id).execute()
    
    if not result.data:
        await callback.answer("❌ У тебя нет активных ключей", show_alert=True)
        return
    
    active_keys = []
    for sub in result.data:
        expires = datetime.fromisoformat(sub["expires_at"])
        if expires > datetime.utcnow():
            sub_url = f"{WORKER_URL}/sub?token={sub['id']}"
            days_left = (expires - datetime.utcnow()).days
            active_keys.append(
                f"🔑 {sub['subscription_type'].upper()}\n"
                f"⏰ Осталось: {days_left} дн.\n"
                f"🔗 <code>{sub_url}</code>\n"
            )
    
    if not active_keys:
        await callback.message.edit_text(
            "❌ Нет активных подписок",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back")]
            ])
        )
    else:
        await callback.message.edit_text(
            "🔑 Твои активные ключи:\n\n" + "\n".join(active_keys),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back")]
            ])
        )
    await callback.answer()

@dp.callback_query(F.data == "help")
async def help_menu(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "📱 WopeVPN - Инструкция по подключению:\n\n"
        "1️⃣ Скачай приложение:\n"
        "   • Android: v2rayNG, Hiddify\n"
        "   • iOS: Shadowrocket, V2Box\n\n"
        "2️⃣ Скопируй subscription URL\n\n"
        "3️⃣ В приложении:\n"
        "   • Найди 'Subscription' или 'Подписка'\n"
        "   • Вставь ссылку\n"
        "   • Обновить подписку\n\n"
        "4️⃣ Подключись к серверу!\n\n"
        "❓ Проблемы? Пиши @твой_username",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back")]
        ])
    )
    await callback.answer()

# Админ-панель
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Доступ запрещен")
        return
    
    await message.answer(
        "👨‍💼 Админ-панель",
        reply_markup=admin_keyboard()
    )

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Доступ запрещен", show_alert=True)
        return
    
    result = supabase.table("subscriptions").select("*").execute()
    
    total = len(result.data)
    active = sum(1 for s in result.data if datetime.fromisoformat(s["expires_at"]) > datetime.utcnow())
    trial = sum(1 for s in result.data if s["subscription_type"] == "trial")
    paid = total - trial
    
    await callback.message.edit_text(
        f"📊 Статистика:\n\n"
        f"👥 Всего подписок: {total}\n"
        f"✅ Активных: {active}\n"
        f"🎁 Пробных: {trial}\n"
        f"💎 Платных: {paid}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")]
        ])
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_back")
async def admin_back(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    
    await callback.message.edit_text(
        "👨‍💼 Админ-панель",
        reply_markup=admin_keyboard()
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_give")
async def admin_give_key(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Доступ запрещен", show_alert=True)
        return
    
    await callback.message.edit_text(
        "🎁 Выдать ключ пользователю\n\n"
        "Отправь сообщение в формате:\n"
        "<code>/give USER_ID DAYS</code>\n\n"
        "Примеры:\n"
        "• <code>/give 123456789 7</code> - 7 дней\n"
        "• <code>/give 123456789 30</code> - 30 дней\n"
        "• <code>/give 123456789 36500</code> - навсегда",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")]
        ])
    )
    await callback.answer()

@dp.message(Command("give"))
async def give_key_command(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    try:
        parts = message.text.split()
        if len(parts) != 3:
            await message.answer("❌ Неверный формат. Используй: /give USER_ID DAYS")
            return
        
        target_user_id = int(parts[1])
        days = int(parts[2])
        
        # Создаем подписку
        sub_id = str(uuid.uuid4())
        expires_at = datetime.utcnow() + timedelta(days=days)
        device_fp = hashlib.sha256(f"{target_user_id}_admin".encode()).hexdigest()[:16]
        
        sub_type = "forever" if days > 365 else f"{days}days"
        
        supabase.table("subscriptions").insert({
            "id": sub_id,
            "user_id": target_user_id,
            "device_fingerprint": device_fp,
            "subscription_type": sub_type,
            "expires_at": expires_at.isoformat(),
            "created_at": datetime.utcnow().isoformat()
        }).execute()
        
        sub_url = f"{WORKER_URL}/sub?token={sub_id}"
        
        # Отправляем ключ пользователю
        try:
            await bot.send_message(
                target_user_id,
                f"🎉 WopeVPN - Тебе выдан ключ!\n\n"
                f"⏰ Действует до: {expires_at.strftime('%d.%m.%Y %H:%M')}\n"
                f"📱 Устройств: до 4\n\n"
                f"🔗 Subscription URL:\n"
                f"<code>{sub_url}</code>\n\n"
                f"📲 Добавь в приложение v2rayNG/Hiddify",
                parse_mode="HTML"
            )
            await message.answer(
                f"✅ Ключ выдан пользователю {target_user_id}\n"
                f"Срок: {days} дней"
            )
        except Exception as e:
            await message.answer(
                f"⚠️ Ключ создан, но не удалось отправить пользователю\n"
                f"Возможно, он не запускал бота\n\n"
                f"Ключ: <code>{sub_url}</code>",
                parse_mode="HTML"
            )
    
    except ValueError:
        await message.answer("❌ USER_ID и DAYS должны быть числами")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

@dp.callback_query(F.data == "admin_delete")
async def admin_delete_key(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("❌ Доступ запрещен", show_alert=True)
        return
    
    await callback.message.edit_text(
        "🗑 Удалить ключ пользователя\n\n"
        "Отправь сообщение в формате:\n"
        "<code>/delete USER_ID</code>\n\n"
        "Пример:\n"
        "• <code>/delete 123456789</code>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")]
        ])
    )
    await callback.answer()

@dp.message(Command("delete"))
async def delete_key_command(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    try:
        parts = message.text.split()
        if len(parts) != 2:
            await message.answer("❌ Неверный формат. Используй: /delete USER_ID")
            return
        
        target_user_id = int(parts[1])
        
        # Удаляем все подписки пользователя
        result = supabase.table("subscriptions").delete().eq("user_id", target_user_id).execute()
        
        if result.data:
            await message.answer(f"✅ Удалено {len(result.data)} ключей пользователя {target_user_id}")
        else:
            await message.answer(f"❌ У пользователя {target_user_id} нет ключей")
    
    except ValueError:
        await message.answer("❌ USER_ID должен быть числом")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)}")

async def main():
    print("🤖 WopeVPN бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
