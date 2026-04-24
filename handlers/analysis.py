import json
import io
import pandas as pd
import logging
from aiogram import Router, F, Bot, types
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command

from services.ai_agents import AnalysisPipeline
from services.db_uploader import DBUploader
from db.engine import async_session_local
from db.models import AnalysisTask
from states import UploadState 
from keyboards.admin_kb import get_admin_kb

logger = logging.getLogger(__name__)

router = Router()
pipeline = AnalysisPipeline()

# --- СЕРВІСНА ФУНКЦІЯ: РЕМОНТ БИТОГО JSON ---
def repair_truncated_json(json_str: str) -> str:
    """
    Допомагає закрити дужки, якщо модель обірвала відповідь.
    Також намагається видалити 'сміття' в кінці обірваного рядка.
    """
    json_str = json_str.strip()
    last_valid_point = max(json_str.rfind(','), json_str.rfind('{'), json_str.rfind('['))
    if not json_str.endswith(('}', ']')) and last_valid_point != -1:
        json_str = json_str[:last_valid_point]
    braces = json_str.count('{') - json_str.count('}')
    brackets = json_str.count('[') - json_str.count(']')
    
    if brackets > 0:
        json_str += ']' * brackets
    if braces > 0:
        json_str += '}' * braces
        
    return json_str

# --- ДОПОМІЖНА ФУНКЦІЯ ДЛЯ ПАРСИНГУ ТА ФОРМАТУВАННЯ ---
def format_verdict_text(raw_json: str) -> str:
    try:
        clean_json = raw_json.strip()
        if "```json" in clean_json:
            clean_json = clean_json.split("```json")[1].split("```")[0]
        elif "```" in clean_json:
            clean_json = clean_json.split("```")[1].split("```")[0]

        start_idx = clean_json.find('{')
        if start_idx == -1:
            return f"💬 **Звіт Агента (текстовий формат):**\n\n{raw_json}"

        json_part = clean_json[start_idx:]
        
        try:
            data = json.loads(json_part)
            is_truncated = False
        except json.JSONDecodeError:
            repaired = repair_truncated_json(json_part)
            try:
                data = json.loads(repaired)
                is_truncated = True
            except:
                return f"⚠️ **Критична помилка JSON:**\nДані занадто пошкоджені для аналізу.\n\n`{raw_json[:300]}...`"

        color_map = {"ЗЕЛЕНИЙ": "🟢", "ЖОВТИЙ": "🟡", "ЧЕРВОНИЙ": "🔴"}
        status_emoji = color_map.get(str(data.get('колір', '')).upper(), "⚪️")

        text = (
            f"{status_emoji} **ВЕРДИКТ: {data.get('вердикт', 'АНАЛІЗ ЗАВЕРШЕНО')}**\n"
            f"📅 {data.get('timestamp', 'дата не вказана')}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
        )

        # Секція замовлення
        zamov = data.get('замовлення', {})
        text += (
            f"📦 **Замовлення:** {zamov.get('SKU', 'Н/Д')}\n"
            f"⚖️ **Обсяг:** {zamov.get('обсяг_кг', 0)} кг\n"
            f"⏰ **Дедлайн:** {zamov.get('дедлайн_відвантаження', 'Н/Д')}\n\n"
        )

        # Секція сировини
        if data.get('сировинний_баланс'):
            text += "🧱 **Сировинний баланс:**\n"
            for item in data['сировинний_баланс']:
                nom = item.get('номенклатура', 'Невідомо')
                bal = item.get('баланс', 0)
                unit = item.get('одиниця', 'кг')
                st = item.get('статус', '')
                
                icon = "✅" if st == "профіцит" else ("⚠️" if st == "в нуль" else "❌")
                text += f"{icon} {nom}: {bal} {unit}\n"
            text += "\n"

        # Обладнання
        if data.get('завантаженість_обладнання'):
            text += "⚙️ **Обладнання:**\n"
            for eq in data['завантаженість_обладнання']:
                eq_st = eq.get('статус', '')
                eq_icon = "🟢" if eq_st == "вільно" else ("🟡" if eq_st == "напружено" else "🔴")
                text += f"{eq_icon} {eq.get('обладнання')}: {eq.get('вільний_час_год', 0)}г вільно\n"
            text += "\n"

        # Рекомендації та обґрунтування
        text += f"📝 **Обґрунтування:**\n{data.get('обґрунтування', 'Аналіз проведено на основі наявних залишків та норм виробництва.')}\n\n"
        
        if data.get('умови_виконання'):
            text += "💡 **Умови:**\n• " + "\n• ".join(data['умови_виконання']) + "\n\n"

        if is_truncated:
            text += "⚠️ **УВАГА:** Звіт було обірвано через ліміт токенів. Деякі дані можуть бути відсутні."

        return text

    except Exception as e:
        logger.error(f"Помилка форматування тексту: {e}")
        return f"❌ **Сталася помилка при обробці звіту.**\n\nТехнічні деталі: `{str(e)}`"

# --- БД І ЛОГІКА ЗБЕРЕЖЕННЯ ---
async def save_results_to_db(user_id: int, results: dict):
    async with async_session_local() as session:
        async with session.begin():
            new_task = AnalysisTask(
                user_id=user_id,
                md1=results.get('md1'),
                md2=results.get('md2'),
                md3=results.get('md3'),
                md4=results.get('md4'),
                final_report=results.get('verdict'),
                status="completed"
            )
            session.add(new_task)

# --- АДМІН-ПАНЕЛЬ ТА ОНОВЛЕННЯ БАЗИ ---
@router.message(Command("admin"))
async def show_admin_menu(message: Message):
    await message.answer("🛠 **Панель керування базою знань**\nОберіть таблицю для оновлення:", reply_markup=get_admin_kb())

@router.callback_query(F.data.startswith("up_"))
async def start_upload_process(callback: CallbackQuery, state: FSMContext):
    table_name = callback.data.replace("up_", "")
    await state.update_data(target_table=table_name)
    await state.set_state(UploadState.waiting_for_file)
    await callback.message.edit_text(f"📥 Надсилайте файл (.xlsx або .csv) для таблиці: `{table_name}`")
    await callback.answer()

@router.message(UploadState.waiting_for_file, F.document)
async def handle_db_update(message: Message, state: FSMContext, bot: Bot):
    user_data = await state.get_data()
    table = user_data.get("target_table")
    file_name = message.document.file_name
    
    status_msg = await message.answer(f"⏳ Оновлюю базу даних `{table}`...")
    file_obj = await bot.get_file(message.document.file_id)
    file_io = await bot.download_file(file_obj.file_path)
    
    try:
        count = await DBUploader.upload_file(file_io.read(), file_name, table)
        await status_msg.edit_text(f"✅ Успішно! Оновлено {count} записів у `{table}`.")
    except Exception as e:
        await status_msg.edit_text(f"❌ Помилка завантаження: {e}")
    finally:
        await state.clear()

# --- ВІДПРАВКА ЗВІТІВ ЯК ФАЙЛІВ ---
async def send_agent_reports(message: Message, results: dict):
    reports = {
        "md1": "📦_Склад.md",
        "md2": "🏭_НЗВ.md",
        "md3": "📜_План.md",
        "md4": "📊_Таймінги.md"
    }
    for key, filename in reports.items():
        content = results.get(key)
        if content:
            file = BufferedInputFile(content.encode('utf-8'), filename=filename)
            await message.answer_document(file)

# --- ОСНОВНИЙ ХЕНДЛЕР АНАЛІЗУ ---
@router.message(F.document)
async def handle_document_analysis(message: Message, bot: Bot):
    file_name = message.document.file_name
    status_msg = await message.answer(f"🚀 Запускаю агентів для аналізу `{file_name}`...")

    file_obj = await bot.get_file(message.document.file_id)
    file_io = await bot.download_file(file_obj.file_path)
    raw_data = file_io.read()
    
    try:
        if file_name.endswith(('.xlsx', '.xls')):
            df = pd.read_excel(io.BytesIO(raw_data))
            content = df.to_csv(index=False)
        else:
            try: content = raw_data.decode('utf-8-sig')
            except: content = raw_data.decode('cp1251')

        results = await pipeline.run(content)
        await save_results_to_db(message.from_user.id, results)
        
        readable_text = format_verdict_text(results.get('verdict', "{}"))
        await status_msg.edit_text(readable_text, parse_mode="Markdown")
        
        await send_agent_reports(message, results)
        
    except Exception as e:
        logger.exception("Помилка під час аналізу документа")
        await status_msg.edit_text(f"❌ Помилка аналізу: {e}")

@router.message(F.text)
async def handle_text_analysis(message: Message):
    if message.text.startswith('/'): return
    
    status_msg = await message.answer("🤖 Агенти вивчають запит...")
    try:
        results = await pipeline.run(message.text)
        await save_results_to_db(message.from_user.id, results)
        
        readable_text = format_verdict_text(results.get('verdict', "{}"))
        await status_msg.edit_text(readable_text, parse_mode="Markdown")
        
        await send_agent_reports(message, results)
    except Exception as e:
        await status_msg.edit_text(f"❌ Помилка: {e}")