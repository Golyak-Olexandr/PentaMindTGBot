import json
import io
import pandas as pd
import logging
import html
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
        
        # 1. Покращена екстракція JSON (шукаємо межі фігурних дужок)
        if "```json" in clean_json:
            clean_json = clean_json.split("```json")[1].split("```")[0]
        elif "```" in clean_json:
            clean_json = clean_json.split("```")[1].split("```")[0]

        start_idx = clean_json.find('{')
        end_idx = clean_json.rfind('}')
        
        if start_idx == -1 or end_idx == -1:
            # Якщо JSON не знайдено, екрануємо весь текст, щоб не зламати HTML
            safe_raw = html.escape(raw_json)
            return f"💬 <b>Звіт Агента (текстовий формат):</b>\n\n{safe_raw}"

        json_part = clean_json[start_idx:end_idx+1]
        
        try:
            data = json.loads(json_part)
            is_truncated = False
        except json.JSONDecodeError:
            repaired = repair_truncated_json(json_part)
            try:
                data = json.loads(repaired)
                is_truncated = True
            except:
                safe_snippet = html.escape(raw_json[:300])
                return f"⚠️ <b>Критична помилка JSON:</b>\nДані занадто пошкоджені.\n\n<code>{safe_snippet}...</code>"

        # 2. Підготовка даних (безпечне отримання та екранування)
        def s(value): # Скорочена функція для безпечного тексту
            return html.escape(str(value))

        color_map = {"ЗЕЛЕНИЙ": "🟢", "ЖОВТИЙ": "🟡", "ЧЕРВОНИЙ": "🔴"}
        status_emoji = color_map.get(str(data.get('колір', '')).upper(), "⚪️")

        # 3. Формування HTML тексту
        text = (
            f"{status_emoji} <b>ВЕРДИКТ: {s(data.get('вердикт', 'АНАЛІЗ ЗАВЕРШЕНО'))}</b>\n"
            f"📅 {s(data.get('timestamp', 'дата не вказана'))}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
        )

        # Секція замовлення
        zamov = data.get('замовлення', {})
        text += (
            f"📦 <b>Замовлення:</b> {s(zamov.get('SKU', 'Н/Д'))}\n"
            f"⚖️ <b>Обсяг:</b> {s(zamov.get('обсяг_кг', 0))} кг\n"
            f"⏰ <b>Дедлайн:</b> {s(zamov.get('дедлайн_відвантаження', 'Н/Д'))}\n\n"
        )

        # Секція сировини
        if data.get('сировинний_баланс'):
            text += "<b>🧱 Сировинний баланс:</b>\n"
            for item in data['сировинний_баланс']:
                nom = s(item.get('номенклатура', 'Невідомо'))
                bal = s(item.get('баланс', 0))
                unit = s(item.get('одиниця', 'кг'))
                st = item.get('статус', '')
                
                icon = "✅" if st == "профіцит" else ("⚠️" if st == "в нуль" else "❌")
                text += f"{icon} {nom}: {bal} {unit}\n"
            text += "\n"

        # Обладнання
        if data.get('завантаженість_обладнання'):
            text += "<b>⚙️ Обладнання:</b>\n"
            for eq in data['завантаженість_обладнання']:
                eq_st = eq.get('статус', '')
                eq_icon = "🟢" if eq_st == "вільно" else ("🟡" if eq_st == "напружено" else "🔴")
                text += f"{eq_icon} {s(eq.get('обладнання'))}: {s(eq.get('вільний_час_год', 0))}г вільно\n"
            text += "\n"

        # Рекомендації
        obs = s(data.get('обґрунтування', 'Аналіз проведено на основі наявних залишків.'))
        text += f"📝 <b>Обґрунтування:</b>\n{obs}\n\n"
        
        if data.get('умови_виконання'):
            text += "<b>💡 Умови:</b>\n"
            for u in data['умови_виконання']:
                text += f"• {s(u)}\n"
            text += "\n"

        if is_truncated:
            text += "⚠️ <b>УВАГА:</b> Звіт було обірвано через ліміт токенів."

        return text

    except Exception as e:
        logger.error(f"Помилка форматування тексту: {e}")
        return f"❌ <b>Сталася помилка при обробці звіту.</b>\n\nТехнічні деталі: <code>{s(str(e))}</code>"

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

        results = await pipeline.run(content, status_msg=status_msg)
        await save_results_to_db(message.from_user.id, results)
        
        readable_text = format_verdict_text(results.get('verdict', "{}"))
        await status_msg.edit_text(readable_text, parse_mode="HTML")
        
        await send_agent_reports(message, results)
        
    except Exception as e:
        logger.exception("Помилка під час аналізу документа")
        await status_msg.edit_text(f"❌ Помилка аналізу: {e}")

@router.message(F.text)
async def handle_text_analysis(message: Message):
    if message.text.startswith('/'): return
    
    status_msg = await message.answer("🤖 Агенти вивчають запит...")
    try:
        results = await pipeline.run(message.text, status_msg=status_msg)
        await save_results_to_db(message.from_user.id, results)
        
        readable_text = format_verdict_text(results.get('verdict', "{}"))
        await status_msg.edit_text(readable_text, parse_mode="HTML")
        
        await send_agent_reports(message, results)
    except Exception as e:
        await status_msg.edit_text(f"❌ Помилка: {e}")