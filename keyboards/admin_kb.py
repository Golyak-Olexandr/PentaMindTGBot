from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_admin_kb():
    buttons = [
        [InlineKeyboardButton(text="Залишки сировини", callback_data="up_inventory_raw")],
        [InlineKeyboardButton(text="Залишки НЗВ (напівфабрикати)", callback_data="up_inventory_semi")],
        [InlineKeyboardButton(text="Специфікації", callback_data="up_specifications")],
        [InlineKeyboardButton(text="Продуктивність", callback_data="up_production_rates")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)