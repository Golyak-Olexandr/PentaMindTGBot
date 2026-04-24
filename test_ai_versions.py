import google.generativeai as genai
from config import Config

genai.configure(api_key=Config.GEMINI_KEY)

print("--- Доступні моделі Gemini ---")
try:
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f"Назва: {m.name}")
            print(f"   Опис: {m.description}")
            print(f"   Ліміт токенів (вхід): {m.input_token_limit}")
            print("-" * 30)
except Exception as e:
    print(f"Помилка при отриманні списку: {e}")