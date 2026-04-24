import pandas as pd
import io
import numpy as np
from sqlalchemy import text
from db.engine import async_session_local

class DBUploader:
    @staticmethod
    @staticmethod
    def transform_inventory(df):
        """Логіка для 'Залишки' та 'Залишки Напівфабрикатів' з обходом заголовків"""
        processed_data = []
        current_location = "Невідомо"
        
        for _, row in df.iterrows():
            col0 = str(row.iloc[0]).strip()
            unit = row.iloc[1]
            qty = row.iloc[2]

            if pd.isna(unit) and pd.isna(qty):
                if col0 not in ['nan', 'Номенклатура', 'Місце зберігання', 'None', '']:
                    current_location = col0
                continue
            
            if pd.notna(unit):
                try:
                    val = str(qty).replace(',', '.').strip()
                    numeric_qty = float(val)
                except ValueError:
                    continue

                processed_data.append({
                    'location': current_location,
                    'name': col0,
                    'unit': unit,
                    'quantity': numeric_qty
                })
        return pd.DataFrame(processed_data)

    @staticmethod
    def transform_specs(df):
        """Логіка для 'Специфікації'"""
        specs_data = []
        current_product = None

        for _, row in df.iterrows():
            col0 = str(row.iloc[0]).strip() 
            col1 = str(row.iloc[1]).strip() 
            col2 = row.iloc[2]              

            if col1 in ['nan', 'Номенклатура', 'None'] or (col0 == 'nan' and col1 == 'nan'):
                continue

            if col0 == 'nan' and col1 != 'nan':
                current_product = col1
                continue

            if col0.replace('.', '').isdigit():
                specs_data.append({
                    'parent_product': current_product,
                    'ingredient': col1,
                    'norm': float(str(col2).replace(',', '.')) if pd.notna(col2) else 0.0
                })
        return pd.DataFrame(specs_data)

    @staticmethod
    async def upload_file(file_bytes: bytes, file_name: str, table_name: str):
        """Універсальний завантажувач для CSV та Excel"""
        
        is_excel = file_name.lower().endswith(('.xlsx', '.xls'))
        
        if is_excel:
            raw_df = pd.read_excel(io.BytesIO(file_bytes), header=None)
        else:
            try:
                raw_df = pd.read_csv(io.BytesIO(file_bytes), header=None, encoding='utf-8-sig')
            except:
                raw_df = pd.read_csv(io.BytesIO(file_bytes), header=None, encoding='cp1251')

        if table_name in ['inventory_raw', 'inventory_semi']:
            df = DBUploader.transform_inventory(raw_df)
        elif table_name == 'specifications':
            df = DBUploader.transform_specs(raw_df)
        elif table_name == 'production_rates':
            if is_excel:
                df = pd.read_excel(io.BytesIO(file_bytes))
            else:
                try:
                    df = pd.read_csv(io.BytesIO(file_bytes), encoding='utf-8-sig')
                except:
                    df = pd.read_csv(io.BytesIO(file_bytes), encoding='cp1251')
            
            mapping = {
                'Порядок операції': 'op_order',
                'Операція': 'op_name',
                'Вхідний Напівфабрикат': 'input_item',
                'Вихідний Напівфабрикат': 'output_item',
                'Продуктивність кг/год': 'rate'
            }
            df = df.rename(columns=mapping)
            df = df[[col for col in mapping.values() if col in df.columns]]
            if 'rate' in df.columns:
                df['rate'] = pd.to_numeric(df['rate'].astype(str).str.replace(',', '.'), errors='coerce').fillna(0.0)
        else:
            raise ValueError(f"Невідома таблиця: {table_name}")

        # Завантаження в БД
        async with async_session_local() as session:
            async with session.begin():
                await session.execute(text(f"DELETE FROM {table_name}"))
                
                columns = ", ".join(df.columns)
                placeholders = ", ".join([f":{col}" for col in df.columns])
                query = text(f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders})")
                
                records = df.replace({np.nan: None}).to_dict(orient='records')
                for row in records:
                    await session.execute(query, row)
            
            await session.commit()
        return len(df)