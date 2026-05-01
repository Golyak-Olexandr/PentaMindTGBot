import asyncio
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import text
from db.engine import async_session_local

async def debug_db():
    print("🚀 Починаю витягувати дані з БД...")
    try:
        async with async_session_local() as session:
            raw_res = (await session.execute(text("SELECT location, name, unit, quantity FROM inventory_raw"))).all()
            semi_res = (await session.execute(text("SELECT location, name, unit, quantity FROM inventory_semi"))).all()
            spec_res = (await session.execute(text("SELECT parent_product, ingredient, norm FROM specifications"))).all()
            
            def to_md(rows, headers):
                if not rows: return "Дані відсутні.\n"
                table = f"| {' | '.join(headers)} |\n| {' | '.join(['---']*len(headers))} |\n"
                for r in rows:
                    table += f"| {' | '.join([str(val) for val in r])} |\n"
                return table

            raw_md = to_md(raw_res, ["Місце", "Назва", "Од", "К-сть"])
            semi_md = to_md(semi_res, ["Місце", "Назва", "Од", "К-сть"])
            spec_md = to_md(spec_res, ["Продукт", "Інгредієнт", "Норма"])
            
            print("\n=== [ СКЛАД СИРОВИНИ ] ===")
            print(raw_md[:2000] + ("\n...далі ще багато тексту..." if len(raw_md) > 1000 else ""))
            
            print("\n=== [ СУМАРНА ВАГА КОНТЕКСТУ ] ===")
            print(f"📦 Склад: {len(raw_md)} симв.")
            print(f"🏭 НЗВ: {len(semi_md)} симв.")
            print(f"📜 Специфікації: {len(spec_md)} симв.")
            
            total_len = len(raw_md) + len(semi_md) + len(spec_md)
            print(f"\n🔥 ЗАГАЛОМ: {total_len} символів")
            print(f"🧩 Орієнтовно токенів: {total_len // 4}")

    except Exception as e:
        print(f"❌ Помилка: {e}")

if __name__ == "__main__":
    asyncio.run(debug_db())