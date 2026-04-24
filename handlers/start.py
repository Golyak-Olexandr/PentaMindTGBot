from aiogram import Router, types
from aiogram.filters import CommandStart, Command

router = Router()

@router.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer(
        f"👋 **Вітаю, {message.from_user.first_name}!**\n\n"
        "Я — твій інтелектуальний помічник з планування виробництва.\n"
        "Всередині мене працює **5 ШІ-агентів**, які аналізують:\n"
        "1️⃣ Залишки на складах\n"
        "2️⃣ Незавершене виробництво (НЗВ)\n"
        "3️⃣ Потребу в сировині\n"
        "4️⃣ Завантаження обладнання\n"
        "5️⃣ Фінальний вердикт щодо замовлення\n\n"
        "📥 **Просто надішліть мені .xlsx-файл із замовленнями, і я почну аналіз.**"
    )

@router.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        "📝 **Як користуватися ботом:**\n\n"
        "1. Підготуйте файл у форматі .xlsx або надішліть дані текстом.\n"
        "2. Дочекайтеся, поки всі 5 агентів оброблять запит (це займає близько хвилини).\n"
        "3. Отримайте вердикт: **ЗЕЛЕНИЙ**, **ЖОВТИЙ** або **ЧЕРВОНИЙ**.\n\n"
        "Всі результати автоматично зберігаються в базі MSSQL."
    )