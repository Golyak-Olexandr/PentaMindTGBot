import asyncio
import logging
import time
from datetime import datetime
from sqlalchemy import text
import google.generativeai as genai
from google.api_core import exceptions

from db.engine import async_session_local
from config import Config
from services.prompts import (
    AGENT_1_PROMPT, 
    AGENT_2_PROMPT, 
    AGENT_3_PROMPT, 
    AGENT_4_PROMPT, 
    AGENT_5_PROMPT
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

genai.configure(api_key=Config.GEMINI_KEY)

class BaseAgent:
    def __init__(self, name: str, role: str):
        
        self.name = name
        self.role = role
        # ЗМІНЮВАТИ МОДЕЛЬ АІ-АГЕНТІВ ТУТ
        self.model = genai.GenerativeModel('gemini-2.5-flash', system_instruction=role)

    async def call_llm(self, user_input: str, context: str = "", db_data: str = "", semaphore: asyncio.Semaphore = None):
        """Виклик LLM з обробкою помилок та автоматичними ретраями."""
        full_prompt = (
            f"### ГОЛОВНЕ ЗАВДАННЯ ДЛЯ ВИКОНАННЯ:\n{user_input}\n\n"
            f"Твоя роль: {self.role}\n\n"
        )
        
        if db_data:
            full_prompt += f"--- ТВОЯ БАЗА ЗНАНЬ (ДАНІ З БД) ---\n{db_data}\n\n"
            
        if context:
            full_prompt += f"--- КОНТЕКСТ ВІД ІНШИХ АГЕНТІВ ---\n{context}\n\n"
            
        full_prompt += "\nСформуй чітку відповідь згідно з твоїм форматом. Якщо в назвах є лапки (\"), замінюй їх на одинарні (')."

        async with (semaphore or asyncio.Lock()):
            for attempt in range(3):
                try:
                    response = await self.model.generate_content_async(
                        full_prompt,
                    )
                    if not response.text:
                        return f"Агент {self.name} повернув порожню відповідь."
                    return response.text

                except exceptions.ResourceExhausted:
                    wait_time = 30 * (attempt + 1)
                    logger.warning(f"⚠️ Агент {self.name}: Ліміт 429! Спроба {attempt+1}/3. Чекаємо {wait_time}с...")
                    await asyncio.sleep(wait_time)
                
                except Exception as e:
                    logger.error(f"❌ Агент {self.name} помилка: {str(e)}")
                    return f"Внутрішня помилка агента {self.name}."

            return "ПОМИЛКА: Не вдалося отримати відповідь після кількох спроб через ліміти API."

class AnalysisPipeline:
    def __init__(self):
        self.agent1 = BaseAgent("Склад", AGENT_1_PROMPT)
        self.agent2 = BaseAgent("НЗВ", AGENT_2_PROMPT)
        self.agent3 = BaseAgent("Замовлення", AGENT_3_PROMPT)
        self.agent4 = BaseAgent("Аналітик", AGENT_4_PROMPT)
        self.agent5 = BaseAgent("Арбітр", AGENT_5_PROMPT)
        
        # Обмежуємо кількість одночасних запитів до мережі
        self.semaphore = asyncio.Semaphore(1)
        self.request_history = []

    async def _wait_for_quota(self):
        """Контролює дотримання ліміту 5 запитів на хвилину."""
        now = time.time()
        self.request_history = [t for t in self.request_history if now - t < 60]
        
        if len(self.request_history) >= 4:
            wait_time = 60 - (now - self.request_history[0]) + 2
            if wait_time > 0:
                logger.info(f"⏳ RPM ліміт! Пауза {wait_time:.1f} сек...")
                await asyncio.sleep(wait_time)
        
        self.request_history.append(time.time())

    async def fetch_formatted_db(self):
        """Збирає дані з БД та готує їх у Markdown форматі."""
        async with async_session_local() as session:
            try:
                raw_res = (await session.execute(text("SELECT location, name, unit, quantity FROM inventory_raw"))).all()
                semi_res = (await session.execute(text("SELECT location, name, unit, quantity FROM inventory_semi"))).all()
                spec_res = (await session.execute(text("SELECT parent_product, ingredient, norm FROM specifications"))).all()
                rate_res = (await session.execute(text("SELECT op_name, input_item, output_item, rate FROM production_rates"))).all()
                
                logger.info(f"DB Fetch: Raw:{len(raw_res)}, Semi:{len(semi_res)}, Specs:{len(spec_res)}")

                def to_md(rows, headers):
                    if not rows: return "Дані відсутні.\n"
                    table = f"| {' | '.join(headers)} |\n| {' | '.join(['---']*len(headers))} |\n"
                    for r in rows:
                        table += f"| {' | '.join([str(val) for val in r])} |\n"
                    return table
                return {
                    "raw": "### 📦 СКЛАД СИРОВИНИ\n" + to_md(raw_res, ["Місце", "Назва", "Од", "К-сть"]),
                    "semi": "### 🏭 ЗАЛИШКИ НЗВ\n" + to_md(semi_res, ["Місце", "Назва", "Од", "К-сть"]),
                    "spec": "### 📜 СПЕЦИФІКАЦІЇ\n" + to_md(spec_res, ["Продукт", "Інгредієнт", "Норма"]),
                    "rate": "### ⚙️ ПРОДУКТИВНІСТЬ\n" + to_md(rate_res, ["Операція", "Вхід", "Вихід", "Швидкість"])
                }
            except Exception as e:
                logger.error(f"Помилка БД: {e}")
                return {"raw": "", "semi": "", "spec": "", "rate": ""}

    async def run(self, input_data: str):
        """Запуск повного циклу аналізу з рівномірними паузами."""
        start_time = time.time()
        current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        db = await self.fetch_formatted_db()
        if not input_data:
            return {"verdict": "Помилка: вхідні дані порожні."}

        # КРОК 1
        print("--- Агент 1 аналізує склад... ---")
        res1 = await self.agent1.call_llm(input_data, db_data=db['raw'] + db['spec'], semaphore=self.semaphore)
        
        # Рівномірна пауза 15с між агентами (60с / 4 запити = 15с)
        print("--- Передишка для заходу в межі RPM ---")
        await asyncio.sleep(15)
        
        # КРОК 2
        print("--- Агент 2 аналізує напівфабрикати... ---")
        res2 = await self.agent2.call_llm(input_data, db_data=db['semi'] + db['spec'] + db['rate'], semaphore=self.semaphore)

        print("--- Передишка для заходу в межі RPM ---")
        await asyncio.sleep(15)

        # КРОК 3
        print("--- Агент 3 формує план... ---")
        a3_context = f"Звіт Складу (А1): {res1}\nЗвіт НЗВ (А2): {res2}"
        res3 = await self.agent3.call_llm(input_data, context=a3_context, db_data=db['spec'] + db['rate'], semaphore=self.semaphore)

        # Перевірка загального часу (умова: пауза після А3, якщо пройшло мало часу)
        elapsed = time.time() - start_time
        if elapsed < 60:
            wait_for_rest = 60 - elapsed + 2
            print(f"⏳ Пауза після А3: пройшло лише {elapsed:.1f}с. Чекаємо {wait_for_rest:.1f}с для оновлення токенів...")
            await asyncio.sleep(wait_for_rest)

        print("--- Передишка для заходу в межі RPM ---")
        await asyncio.sleep(15)

        # КРОК 4
        print("--- Агент 4 рахує таймінги... ---")
        res4 = await self.agent4.call_llm(res3, context=f"НЗВ: {res2}", db_data=db['raw']+db['semi']+db['spec']+db['rate'], semaphore=self.semaphore)

        print("--- Передишка для заходу в межі RPM ---")
        await asyncio.sleep(15)

        # КРОК 5
        print("--- Агент 5 формує вердикт... ---")
        final_context = (
            f"ПОТОЧНИЙ ЧАС: {current_time_str}\n"
            f"ЗАПИТ: {input_data}\n\n"
            f"ЗВІТ_А1: {res1}\n\nЗВІТ_А2: {res2}\n\n"
            f"ЗВІТ_А3: {res3}\n\nЗВІТ_А4: {res4}"
        )
        res5 = await self.agent5.call_llm("ВИКОНАЙ ФІНАЛЬНИЙ АНАЛІЗ", context=final_context, semaphore=self.semaphore)

        return {
            "md1": res1, "md2": res2, "md3": res3, "md4": res4, "verdict": res5
        }