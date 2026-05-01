import json
import io
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

processing_users = set()

#Ремонт пошкодженого джсон файлу
def repair_truncated_json(json_str: str) -> str:
    json_str = json_str.strip()
    last_valid_point = max(json_str.rfind(","), json_str.rfind("{"), json_str.rfind("["))
    if not json_str.endswith(("}", "]")) and last_valid_point != -1:
        json_str = json_str[:last_valid_point]
    braces   = json_str.count("{") - json_str.count("}")
    brackets = json_str.count("[") - json_str.count("]")
    if brackets > 0:
        json_str += "]" * brackets
    if braces > 0:
        json_str += "}" * braces
    return json_str

#Форматування відповіді 5 агента
def format_verdict_text(raw_json: str) -> str:
    try:
        clean_json = raw_json.strip()

        if "```json" in clean_json:
            clean_json = clean_json.split("```json")[1].split("```")[0]
        elif "```" in clean_json:
            clean_json = clean_json.split("```")[1].split("```")[0]

        start_idx = clean_json.find("{")
        end_idx   = clean_json.rfind("}")

        if start_idx == -1 or end_idx == -1:
            safe_raw = html.escape(raw_json)
            return f"💬 <b>Звіт Агента (текстовий формат):</b>\n\n{safe_raw}"

        json_part = clean_json[start_idx : end_idx + 1]

        try:
            data = json.loads(json_part)
            is_truncated = False
        except json.JSONDecodeError:
            repaired = repair_truncated_json(json_part)
            try:
                data = json.loads(repaired)
                is_truncated = True
            except Exception:
                safe_snippet = html.escape(raw_json[:300])
                return (
                    f"⚠️ <b>Критична помилка JSON:</b>\n"
                    f"Дані занадто пошкоджені.\n\n<code>{safe_snippet}...</code>"
                )

        def s(value):
            return html.escape(str(value))

        color_map = {"ЗЕЛЕНИЙ": "🟢", "ЖОВТИЙ": "🟡", "ЧЕРВОНИЙ": "🔴"}
        status_emoji = color_map.get(str(data.get("колір", "")).upper(), "⚪️")

        text = (
            f"{status_emoji} <b>ВЕРДИКТ: {s(data.get('вердикт', 'АНАЛІЗ ЗАВЕРШЕНО'))}</b>\n"
            f"📅 {s(data.get('timestamp', 'дата не вказана'))}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
        )

        zv = data.get("зведення_по_замовленнях", {})
        text += (
            f"📦 <b>Замовлень:</b> {s(zv.get('кількість_замовлень', 'Н/Д'))} шт | "
            f"⚖️ <b>Вага:</b> {s(zv.get('загальна_вага_кг', 0))} кг\n"
            f"⏰ <b>Найближчий дедлайн:</b> {s(zv.get('найближчий_дедлайн', 'Н/Д'))}\n\n"
        )

        umovy = data.get("умови_виконання", [])
        if umovy and isinstance(umovy, list) and any(umovy):
            text += "<b>✅ ЩО ТРЕБА ЗРОБИТИ ДЛЯ ВИКОНАННЯ:</b>\n"
            for u in umovy:
                text += f"🔹 {s(u)}\n"
            text += "\n"

        obs = s(data.get("обґрунтування", "Аналіз проведено на основі наявних залишків."))
        text += f"📝 <b>Аналіз ситуації:</b>\n{obs}\n\n"

        alt = data.get("альтернативи", [])
        if alt and isinstance(alt, list) and any(alt):
            text += "<b>🔄 Деталі та обмеження:</b>\n"
            for a in alt:
                text += f"• {s(a)}\n"
            text += "\n"

        ops = data.get("завантаженість_операцій", [])
        if ops:
            text += "<b>⏱ Витрати часу на процеси:</b>\n"
            for op in ops:
                text += f"⚙️ {s(op.get('операція'))}: {s(op.get('необхідний_час_год'))} год\n"
            text += "\n"

        balance = data.get("повний_сировинний_баланс", [])
        if balance:
            text += "<b>🧱 Критичні позиції сировини:</b>\n"
            found_minus = False
            for item in balance:
                bal_val = 0.0
                try: bal_val = float(item.get("баланс", 0))
                except: pass

                if bal_val < 0:
                    found_minus = True
                    text += f"❌ <b>{s(item.get('номенклатура'))}</b>: {s(bal_val)} {s(item.get('одиниця'))}\n"
            
            if not found_minus:
                text += "✅ Весь необхідний запас сировини в наявності.\n"
            text += "\n"

        if is_truncated:
            text += "⚠️ <b>УВАГА:</b> Звіт було обірвано через ліміт токенів."

        return text

    except Exception as e:
        logger.error(f"Помилка форматування тексту: {e}")
        return (
            f"❌ <b>Сталася помилка при обробці звіту.</b>\n\n"
            f"Технічні деталі: <code>{html.escape(str(e))}</code>"
        )

#Збереження в бдшку
async def save_results_to_db(user_id: int, results: dict):
    async with async_session_local() as session:
        async with session.begin():
            new_task = AnalysisTask(
                user_id=user_id,
                md1=results.get("md1"),
                md2=results.get("md2"),
                md3=results.get("md3"),
                md4=results.get("md4"),
                final_report=results.get("verdict"),
                status="completed",
            )
            session.add(new_task)

#Адмінка
@router.message(Command("admin"))
async def show_admin_menu(message: Message):
    await message.answer(
        "🛠 **Панель керування базою знань**\nОберіть таблицю для оновлення:",
        reply_markup=get_admin_kb(),
    )

@router.callback_query(F.data.startswith("up_"))
async def start_upload_process(callback: CallbackQuery, state: FSMContext):
    table_name = callback.data.replace("up_", "")
    await state.update_data(target_table=table_name)
    await state.set_state(UploadState.waiting_for_file)
    await callback.message.edit_text(
        f"📥 Надсилайте файл (.xlsx або .csv) для таблиці: `{table_name}`"
    )
    await callback.answer()

@router.message(UploadState.waiting_for_file, F.document)
async def handle_db_update(message: Message, state: FSMContext, bot: Bot):
    user_data  = await state.get_data()
    table      = user_data.get("target_table")
    file_name  = message.document.file_name

    status_msg = await message.answer(f"⏳ Оновлюю базу даних `{table}`...")
    file_obj   = await bot.get_file(message.document.file_id)
    file_io    = await bot.download_file(file_obj.file_path)

    try:
        count = await DBUploader.upload_file(file_io.read(), file_name, table)
        await status_msg.edit_text(f"✅ Успішно! Оновлено {count} записів у `{table}`.")
    except Exception as e:
        await status_msg.edit_text(f"❌ Помилка завантаження: {e}")
    finally:
        await state.clear()

async def send_agent_reports(message: Message, results: dict):
    reports = {
        "md1": "📦_Склад.md",
        "md2": "🏭_НЗВ.md",
        "md3": "📜_План.md",
        "md4": "📊_Таймінги.md",
    }
    for key, filename in reports.items():
        content = results.get(key)
        if content:
            file = BufferedInputFile(content.encode("utf-8"), filename=filename)
            await message.answer_document(file)

#Обробка аналізу
@router.message(F.document)
async def handle_document_analysis(message: Message, bot: Bot):
    user_id = message.from_user.id

    if user_id in processing_users:
        logger.warning(f"Ігноруємо дублікат або спам від {user_id}")
        return

    processing_users.add(user_id)

    try:
        file_name  = message.document.file_name
        status_msg = await message.answer(
            f"🚀 Запускаю аналіз для `{file_name}`..."
        )

        file_obj = await bot.get_file(message.document.file_id)
        file_io  = await bot.download_file(file_obj.file_path)
        raw_data = file_io.read()

        async def send_temp_files(text_content: str, filename: str):
            if text_content and text_content.strip():
                file = BufferedInputFile(text_content.encode("utf-8"), filename=filename)
                await message.answer_document(file)

        results = await pipeline.run(
            raw_data,
            filename=file_name,
            status_msg=status_msg,
            send_func=send_temp_files 
        )
        await save_results_to_db(message.from_user.id, results)

        readable_text = format_verdict_text(results.get("verdict", "{}"))
        await status_msg.edit_text(readable_text, parse_mode="HTML")

    except Exception as e:
        logger.exception("Помилка під час аналізу документа")
        if 'status_msg' in locals():
            await status_msg.edit_text(f"❌ Помилка аналізу: {e}")
        else:
            await message.answer(f"❌ Помилка аналізу: {e}")
    finally:
        processing_users.discard(user_id)

@router.message(F.text)
async def handle_text_analysis(message: Message):
    if message.text.startswith("/"):
        return

    user_id = message.from_user.id
    if user_id in processing_users:
        logger.warning(f"Ігноруємо дублікат тексту від {user_id}")
        return

    processing_users.add(user_id)

    try:
        status_msg = await message.answer("🤖 Агенти вивчають запит...")
        results = await pipeline.run(
            message.text,
            filename="",
            status_msg=status_msg,
        )
        await save_results_to_db(message.from_user.id, results)

        readable_text = format_verdict_text(results.get("verdict", "{}"))
        await status_msg.edit_text(readable_text, parse_mode="HTML")

        await send_agent_reports(message, results)

    except Exception as e:
        if 'status_msg' in locals():
            await status_msg.edit_text(f"❌ Помилка: {e}")
        else:
            await message.answer(f"❌ Помилка: {e}")
    finally:
        processing_users.discard(user_id)