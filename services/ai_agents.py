import asyncio
import logging
from openai import AsyncOpenAI, RateLimitError, OpenAIError
import time
from datetime import datetime
from config import Config
from services.prompts import AGENT_5_PROMPT
from services.deterministic_agents import run_deterministic_pipeline

logger = logging.getLogger(__name__)

client = AsyncOpenAI(api_key=Config.OPENAI_KEY)
class BaseAgent:
    def __init__(self, name: str, role: str):
        self.name = name
        self.role = role
        self.model_name = "gpt-5.4-mini"

    async def call_llm(self, user_input: str, context: str = "", semaphore: asyncio.Semaphore = None):
        full_input = (
            f"SYSTEM ROLE: {self.role}\n\n"
            f"### ЗАВДАННЯ:\n{user_input}\n\n"
            f"### КОНТЕКСТ (JSON):\n{context}\n\n"
            "Сформуй відповідь строго у форматі JSON. "
            "Якщо в назвах є лапки (\"), замінюй їх на одинарні (\')."
        )

        async with (semaphore or asyncio.Lock()):
            max_attempts = 2
            for current_attempt in range(max_attempts):
                try:
                    response = await client.responses.create(
                        model=self.model_name,
                        input=full_input,
                        store=True,
                    )
                    
                    if not response.output_text:
                        return f"Агент {self.name} повернув порожню відповідь."
                    
                    return response.output_text

                except RateLimitError:
                    if current_attempt < max_attempts - 1:
                        wait_time = 2
                        logger.warning(f"⚠️ Агент {self.name}: 429 (Rate Limit), спроба {current_attempt + 1}")
                        await asyncio.sleep(wait_time)
                        continue
                    return "ПОМИЛКА: Ліміти OpenAI вичерпано (429). Спробуйте пізніше."

                except OpenAIError as e:
                    logger.error(f"❌ Помилка OpenAI у агента {self.name}: {e}")
                    return f"Внутрішня помилка API: {str(e)}"

                except Exception as e:
                    logger.error(f"❌ Непередбачена помилка агента {self.name}: {e}")
                    return f"Помилка: {str(e)}"
            
            return "ПОМИЛКА: Не вдалося отримати відповідь від OpenAI."
        
class AnalysisPipeline:
    def __init__(self):
        self.agent5 = BaseAgent("Арбітр", AGENT_5_PROMPT)
        self.semaphore = asyncio.Semaphore(1)

    async def run(self, input_data: str | bytes, filename: str = "", status_msg=None, send_func=None) -> dict:
        start_time = time.time()
        current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M")

        if not input_data:
            return {"verdict": "Помилка: вхідні дані порожні."}

        if status_msg:
            await status_msg.edit_text("<b>Етап 1: Детермінований аналіз...</b>", parse_mode="HTML")

        if isinstance(input_data, bytes):
            try:
                res1, res2, res3, res4, agent5_context, _ = await run_deterministic_pipeline(
                    input_data, filename, current_time_str
                )
                
                if send_func:
                    await send_func(res1, "📦_Склад.md")
                    await send_func(res2, "🏭_НЗВ.md")
                    await send_func(res3, "📜_План.md")
                    await send_func(res4, "📊_Таймінги.md")

            except ValueError as e:
                error_msg = f"❌ Помилка формату файлу: {e}"
                if status_msg:
                    await status_msg.edit_text(error_msg)
                return {"verdict": error_msg}
        else:
            logger.warning("Текстовий вхід: детермінований аналіз пропущено")
            res1 = res2 = res3 = res4 = "⚠️ Excel не надано — детермінований аналіз пропущено."
            agent5_context = input_data

        if status_msg:
            await status_msg.edit_text("<b>Фінал: Агент 5 виносить вердикт...</b>", parse_mode="HTML")

        res5 = await self.agent5.call_llm(
            "ВИКОНАЙ ФІНАЛЬНИЙ АНАЛІЗ",
            context=agent5_context,
            semaphore=self.semaphore,
        )

        logger.info("Аналіз завершено.")
        return {"md1": res1, "md2": res2, "md3": res3, "md4": res4, "verdict": res5}