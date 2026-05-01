from __future__ import annotations
import io
import logging
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd
from sqlalchemy import text
from db.engine import async_session_local

logger = logging.getLogger(__name__)

@dataclass
class RawBalanceItem:
    nomenclature: str
    unit: str
    required_kg: float
    available_qty: float
    balance: float
    status: str

@dataclass
class Agent1Result:
    orders_summary: list[dict]
    raw_balance: list[RawBalanceItem] = field(default_factory=list)
    missing_specs: list[str] = field(default_factory=list)

    def to_md(self) -> str:
        total_weight = sum(o.get("вага", 0) for o in self.orders_summary)
        lines = [
            f"# 📦 Звіт Агента 1 — Загальна потреба під замовлення",
            f"**Кількість замовлень:** {len(self.orders_summary)}",
            f"**Загальний обсяг:** {total_weight:.1f} кг",
            "",
            "## Загальний баланс сировини",
            "| Номенклатура | Од | Потреба | Наявність | Баланс | Статус |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for item in self.raw_balance:
            icon = "✅" if item.status == "профіцит" else ("⚠️" if item.status == "в нуль" else "❌")
            lines.append(
                f"| {item.nomenclature} | {item.unit} | "
                f"{item.required_kg:.3f} | {item.available_qty:.3f} | "
                f"{item.balance:+.3f} | {icon} {item.status} |"
            )
        if self.missing_specs:
            lines += ["", "⚠️ **Відсутні специфікації для:**"]
            for s in self.missing_specs:
                lines.append(f"- {s}")
        return "\n".join(lines)

@dataclass
class SemiFinishedNeed:
    semi_name: str
    semi_qty: float
    semi_unit: str
    ingredient: str
    ingredient_unit: str
    need_qty: float

@dataclass
class OperationTime:
    op_name: str
    input_item: str
    volume_kg: float
    rate_kg_per_hour: float
    hours_needed: float

@dataclass
class Agent2Result:
    semi_raw_needs: list[SemiFinishedNeed] = field(default_factory=list)
    operation_times: list[OperationTime] = field(default_factory=list)

    def to_md(self) -> str:
        lines = [
            "# 🏭 Звіт Агента 2 — НЗВ (напівфабрикати)",
            "",
            "## Потреба в сировині для завершення НФ",
            "| НФ | К-сть НФ | Інгредієнт | Потреба | Од |",
            "| --- | --- | --- | --- | --- |",
        ]
        for item in self.semi_raw_needs:
            lines.append(
                f"| {item.semi_name} | {item.semi_qty:.3f} {item.semi_unit} | "
                f"{item.ingredient} | {item.need_qty:.3f} | {item.ingredient_unit} |"
            )
        lines += [
            "",
            "## Необхідний виробничий час",
            "| Операція | Об'єм (кг) | Швидкість (кг/год) | Час (год) |",
            "| --- | --- | --- | --- |",
        ]
        for op in self.operation_times:
            lines.append(
                f"| {op.op_name} | {op.volume_kg:.3f} | "
                f"{op.rate_kg_per_hour:.3f} | {op.hours_needed:.3f} |"
            )
        return "\n".join(lines)

@dataclass
class ConsolidatedNeed:
    ingredient: str
    unit: str
    need_from_order: float
    need_from_semi: float
    total_need: float
    available: float
    balance: float
    status: str

@dataclass
class Agent3Result:
    consolidated: list[ConsolidatedNeed] = field(default_factory=list)

    def to_md(self) -> str:
        lines = [
            "# 📜 Звіт Агента 3 — Зведений план потреби (Всі замовлення + НЗВ)",
            "",
            "| Номенклатура | Од | Потреба (замовл.) | Потреба (НЗВ) | РАЗОМ | Наявність | Баланс | Статус |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for item in self.consolidated:
            icon = "✅" if item.status == "профіцит" else ("⚠️" if item.status == "в нуль" else "❌")
            lines.append(
                f"| {item.ingredient} | {item.unit} | "
                f"{item.need_from_order:.3f} | {item.need_from_semi:.3f} | "
                f"{item.total_need:.3f} | {item.available:.3f} | "
                f"{item.balance:+.3f} | {icon} {item.status} |"
            )
        return "\n".join(lines)

FIELD_ALIASES = {
    "дата відвантаження": ["дата відвантаження", "дата_відвантаження", "date", "дата"],
    "продукція":          ["продукція", "sku", "продукт", "назва", "product"],
    "вага":               ["вага", "weight", "обсяг", "кг", "вага_кг"],
}

def _find_col(df: pd.DataFrame, key: str) -> Optional[str]:
    aliases = FIELD_ALIASES.get(key, [key])
    cols_lower = {c.strip().lower(): c for c in df.columns}
    for alias in aliases:
        if alias.lower() in cols_lower:
            return cols_lower[alias.lower()]
    return None

def _find_header_row(raw_bytes: bytes, filename: str) -> int:
    all_aliases = [alias for aliases in FIELD_ALIASES.values() for alias in aliases]

    for header_row in range(10):
        try:
            if filename.endswith((".xlsx", ".xls")):
                df_probe = pd.read_excel(io.BytesIO(raw_bytes), header=header_row, nrows=1)
            else:
                try:
                    df_probe = pd.read_csv(io.BytesIO(raw_bytes), header=header_row,
                                           nrows=1, encoding="utf-8-sig")
                except Exception:
                    df_probe = pd.read_csv(io.BytesIO(raw_bytes), header=header_row,
                                           nrows=1, encoding="cp1251")

            cols_lower = {str(c).strip().lower() for c in df_probe.columns}
            hits = sum(1 for alias in all_aliases if alias.lower() in cols_lower)
            if hits >= 2:
                logger.info(f"parse_user_excel: рядок-заголовок знайдено на рядку {header_row}")
                return header_row
        except Exception:
            continue
    logger.warning("parse_user_excel: рядок-заголовок не знайдено, використовуємо 0")
    return 0


def parse_user_excel(raw_bytes: bytes, filename: str) -> list[dict]:
    header_row = _find_header_row(raw_bytes, filename)

    if filename.endswith((".xlsx", ".xls")):
        df = pd.read_excel(io.BytesIO(raw_bytes), header=header_row)
    else:
        try:
            df = pd.read_csv(io.BytesIO(raw_bytes), header=header_row, encoding="utf-8-sig")
        except Exception:
            df = pd.read_csv(io.BytesIO(raw_bytes), header=header_row, encoding="cp1251")

    df = df.dropna(how="all").reset_index(drop=True)

    col_date    = _find_col(df, "дата відвантаження")
    col_product = _find_col(df, "продукція")
    col_weight  = _find_col(df, "вага")

    missing = [k for k, c in [("дата відвантаження", col_date),
                                ("продукція", col_product),
                                ("вага", col_weight)] if c is None]
    if missing:
        raise ValueError(f"Відсутні обов'язкові колонки у файлі: {', '.join(missing)}")

    orders = []
    for _, row in df.iterrows():
        if pd.isna(row[col_product]) or pd.isna(row[col_weight]) or pd.isna(row[col_date]):
            continue
        try:
            orders.append({
                "продукція":          str(row[col_product]).strip(),
                "вага":               float(row[col_weight]),
                "дата_відвантаження": str(row[col_date]).strip(),
            })
        except (ValueError, TypeError) as e:
            logger.warning(f"parse_user_excel: пропускаємо рядок через помилку конвертації: {e}")
            continue

    if not orders:
        raise ValueError("Файл не містить жодного коректного рядка із замовленням.")

    return orders

async def load_knowledge_base() -> dict:
    async with async_session_local() as session:
        raw_rows  = (await session.execute(text(
            "SELECT location, name, unit, quantity FROM inventory_raw"
        ))).all()
        semi_rows = (await session.execute(text(
            "SELECT location, name, unit, quantity FROM inventory_semi"
        ))).all()
        spec_rows = (await session.execute(text(
            "SELECT parent_product, ingredient, norm FROM specifications"
        ))).all()
        rate_rows = (await session.execute(text(
            "SELECT op_name, input_item, output_item, rate FROM production_rates"
        ))).all()

    df_raw  = pd.DataFrame(raw_rows,  columns=["location", "name", "unit", "quantity"])
    df_semi = pd.DataFrame(semi_rows, columns=["location", "name", "unit", "quantity"])
    df_spec = pd.DataFrame(spec_rows, columns=["parent_product", "ingredient", "norm"])
    df_rate = pd.DataFrame(rate_rows, columns=["op_name", "input_item", "output_item", "rate"])

    numeric_cols = {"quantity", "norm", "rate"}
    for df in (df_raw, df_semi, df_spec, df_rate):
        for col in df.columns:
            if col in numeric_cols:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
            else:
                df[col] = df[col].astype(str).str.strip()

    raw_agg = (
        df_raw.groupby(["name", "unit"], as_index=False)["quantity"].sum()
    )
    semi_agg = (
        df_semi.groupby(["name", "unit"], as_index=False)["quantity"].sum()
    )

    logger.info(
        f"KB loaded: raw={len(raw_agg)}, semi={len(semi_agg)}, "
        f"specs={len(df_spec)}, rates={len(df_rate)}"
    )
    return {
        "raw": raw_agg,
        "semi": semi_agg,
        "spec": df_spec,
        "rate": df_rate,
    }

def _status(balance: float) -> str:
    if balance > 0:
        return "профіцит"
    elif balance == 0:
        return "в нуль"
    else:
        return "дефіцит"

def _calc_ingredient_need(spec_df: pd.DataFrame,
                           product: str,
                           weight_kg: float) -> dict[str, dict]:

    product_specs = spec_df[
        spec_df["parent_product"].str.lower() == product.lower()
    ]

    needs: dict[str, dict] = {}
    for _, row in product_specs.iterrows():
        ingredient = row["ingredient"]
        norm_per_100kg = float(row["norm"])
        need = norm_per_100kg * weight_kg / 100.0
        needs[ingredient] = {"need": need, "unit": "кг"}

    return needs

def _get_available(raw_df: pd.DataFrame, ingredient: str) -> tuple[float, str]:
    match = raw_df[raw_df["name"].str.lower() == ingredient.lower()]
    if match.empty:
        return 0.0, "кг"
    return float(match["quantity"].sum()), str(match["unit"].iloc[0])




def run_agent1(orders: list[dict], kb: dict) -> Agent1Result:
    result = Agent1Result(orders_summary=orders)
    aggregated_needs = {}

    for order in orders:
        product = order["продукція"]
        weight = order["вага"]
        needs = _calc_ingredient_need(kb["spec"], product, weight)

        if not needs:
            if product not in result.missing_specs:
                result.missing_specs.append(product)
                logger.warning(f"Agent1: missing spec for '{product}'")
            continue

        for ingredient, meta in needs.items():
            if ingredient not in aggregated_needs:
                aggregated_needs[ingredient] = {"need": 0.0, "unit": meta["unit"]}
            aggregated_needs[ingredient]["need"] += meta["need"]

    for ingredient, meta in aggregated_needs.items():
        need_qty = meta["need"]
        available, unit = _get_available(kb["raw"], ingredient)
        balance = available - need_qty

        result.raw_balance.append(RawBalanceItem(
            nomenclature=ingredient,
            unit=unit,
            required_kg=need_qty,
            available_qty=available,
            balance=balance,
            status=_status(balance),
        ))

    result.raw_balance.sort(key=lambda x: x.nomenclature)
    return result

_STAGE_SUFFIXES = ["ФАРШ", "КО", "заморожені"]

def _extract_base_name(semi_name: str) -> tuple[str, str]:
    for suffix in _STAGE_SUFFIXES:
        if semi_name.strip().endswith(suffix):
            base = semi_name[: -len(suffix)].strip()
            return base, suffix
    return semi_name, ""


def run_agent2(kb: dict) -> Agent2Result:
    result = Agent2Result()
    semi_df = kb["semi"]
    spec_df = kb["spec"]
    rate_df = kb["rate"]

    for _, semi_row in semi_df.iterrows():
        semi_name = semi_row["name"].strip()
        semi_qty = float(semi_row["quantity"])
        semi_unit = semi_row["unit"]

        semi_needs = _calc_ingredient_need(spec_df, semi_name, semi_qty)
        for ingredient, meta in semi_needs.items():
            result.semi_raw_needs.append(SemiFinishedNeed(
                semi_name=semi_name,
                semi_qty=semi_qty,
                semi_unit=semi_unit,
                ingredient=ingredient,
                ingredient_unit=meta["unit"],
                need_qty=meta["need"],
            ))

        current_stages = [semi_name]
        visited_stages = set()
        visited_ops = set()

        while current_stages:
            next_stages = []
            for stage in current_stages:
                if stage in visited_stages:
                    continue
                visited_stages.add(stage)

                ops = rate_df[rate_df["input_item"].str.lower() == stage.lower()]
                
                for _, op_row in ops.iterrows():
                    op_name = op_row["op_name"]
                    op_key = (op_name, stage)
                    
                    if op_key in visited_ops:
                        continue
                    visited_ops.add(op_key)

                    rate = float(op_row["rate"])
                    if rate > 0:
                        result.operation_times.append(OperationTime(
                            op_name=op_name,
                            input_item=stage,
                            volume_kg=semi_qty,
                            rate_kg_per_hour=rate,
                            hours_needed=semi_qty / rate,
                        ))

                    output_stage = str(op_row.get("output_item", "")).strip()
                    if output_stage and output_stage.lower() not in ("nan", "none", ""):
                        next_stages.append(output_stage)

            current_stages = next_stages

    return result

def run_agent3(agent1: Agent1Result,
               agent2: Agent2Result,
               kb: dict) -> Agent3Result:
    result = Agent3Result()

    need_order = {item.nomenclature.lower(): item for item in agent1.raw_balance}
    
    need_semi = {}
    for item in agent2.semi_raw_needs:
        key = item.ingredient.lower()
        need_semi[key] = need_semi.get(key, 0.0) + item.need_qty

    all_ingredients = set(need_order.keys()) | set(need_semi.keys())

    for key in sorted(all_ingredients):
        n_ord = need_order[key].required_kg if key in need_order else 0.0
        n_sem = need_semi.get(key, 0.0)
        total = n_ord + n_sem
        
        name = need_order[key].nomenclature if key in need_order else key.title()

        available, unit_from_raw = _get_available(kb["raw"], name)
        
        unit = need_order[key].unit if key in need_order else "кг"
        if unit == "кг":
            unit = unit_from_raw

        balance = available - total

        result.consolidated.append(ConsolidatedNeed(
            ingredient=name,
            unit=unit,
            need_from_order=n_ord,
            need_from_semi=n_sem,
            total_need=total,
            available=available,
            balance=balance,
            status=_status(balance),
        ))

    return result

@dataclass
class OperationLoad:
    op_name: str
    semi_name: str
    volume_kg: float
    rate_kg_per_hour: float
    hours_needed: float

@dataclass
class Agent4Result:
    operation_loads: list[OperationLoad] = field(default_factory=list)

    def to_md(self) -> str:
        lines = [
            "# 📊 Звіт Агента 4 — Завантаженість операцій",
            "",
            "| Операція | НФ | Об'єм (кг) | Швидкість (кг/год) | Час (год) |",
            "| --- | --- | --- | --- | --- |",
        ]
        for op in self.operation_loads:
            lines.append(
                f"| {op.op_name} | {op.semi_name} | {op.volume_kg:.3f} | "
                f"{op.rate_kg_per_hour:.3f} | {op.hours_needed:.3f} |"
            )
        return "\n".join(lines)

def run_agent4(orders: list[dict], agent2: Agent2Result, kb: dict) -> Agent4Result:
    result = Agent4Result()
    rate_df = kb["rate"]
    aggregated = {}

    for op in agent2.operation_times:
        key = (op.op_name, op.input_item)
        if key not in aggregated:
            aggregated[key] = {
                "volume_kg": 0.0,
                "rate_kg_per_hour": op.rate_kg_per_hour,
                "hours_needed": 0.0
            }
        aggregated[key]["volume_kg"] += op.volume_kg
        aggregated[key]["hours_needed"] += op.hours_needed

    for order in orders:
        product = order["продукція"]
        volume = order["вага"]
        
        base_name = product
        for suffix in [" заморожені", " ФАРШ", " КО", " сирі"]:
            if product.endswith(suffix):
                base_name = product.replace(suffix, "")
                break
        
        ops = rate_df[rate_df["output_item"].str.contains(base_name, case=False, na=False, regex=False)]
        
        for _, op_row in ops.iterrows():
            op_name = op_row["op_name"]
            rate = float(op_row["rate"])
            if rate <= 0: continue
            
            stage_name = f"Нове Замовлення: {base_name}"
            key = (op_name, stage_name)
            
            if key not in aggregated:
                aggregated[key] = {
                    "volume_kg": 0.0,
                    "rate_kg_per_hour": rate,
                    "hours_needed": 0.0
                }
            aggregated[key]["volume_kg"] += volume
            aggregated[key]["hours_needed"] += volume / rate

    for (op_name, semi_name), data in aggregated.items():
        result.operation_loads.append(OperationLoad(
            op_name=op_name,
            semi_name=semi_name,
            volume_kg=data["volume_kg"],
            rate_kg_per_hour=data["rate_kg_per_hour"],
            hours_needed=data["hours_needed"]
        ))
        
    return result

def build_agent5_context(
    current_time_str: str,
    orders: list[dict],
    agent3: Agent3Result,
    agent4: Agent4Result,
) -> str:
    import json

    orders_summary = []
    total_weight = 0.0
    deadlines = []

    for o in orders:
        weight = float(o.get("вага", 0))
        total_weight += weight
        
        deadline = o.get("дата_відвантаження")
        if deadline:
            deadlines.append(deadline)

        orders_summary.append({
            "product": o["продукція"],
            "weightKg": weight,
            "deadline": deadline,
        })

    raw_balance_summary = []
    for item in agent3.consolidated:
        raw_balance_summary.append({
            "nomenclature": item.ingredient,
            "unit": item.unit,
            "available": item.available,
            "orderNeed": item.need_from_order,
            "semiNeed": item.need_from_semi,
            "totalNeed": item.total_need,
            "balance": item.balance,
            "status": item.status,
        })

    op_load_summary = []
    ops_by_name = {}
    for op in agent4.operation_loads:
        ops_by_name[op.op_name] = ops_by_name.get(op.op_name, 0.0) + op.hours_needed

    for op_name, total_hours in ops_by_name.items():
        op_load_summary.append({
            "operation": op_name, 
            "totalHours": round(total_hours, 3)
        })

    context_data = {
        "PRE_CALCULATED_SUMMARY": {
            "total_orders": len(orders),
            "total_weight_kg": round(total_weight, 2),
            "earliest_deadline": min(deadlines) if deadlines else "N/A"
        },
        "currentTime": current_time_str,
        "orders": orders_summary,
        "rawBalance": raw_balance_summary,
        "operationLoad": op_load_summary,
    }
    
    return json.dumps(context_data, ensure_ascii=False, indent=2)

async def run_deterministic_pipeline(
    raw_bytes: bytes,
    filename: str,
    current_time_str: str = "",
) -> tuple[str, str, str, str, str, list[dict]]:
    orders = parse_user_excel(raw_bytes, filename)
    kb = await load_knowledge_base()

    a2 = run_agent2(kb)
    a1 = run_agent1(orders, kb)
    a3 = run_agent3(a1, a2, kb)
    a4 = run_agent4(orders, a2, kb)

    agent5_context = build_agent5_context(current_time_str, orders, a3, a4)

    return (
        a1.to_md(),
        a2.to_md(),
        a3.to_md(),
        a4.to_md(),
        agent5_context,
        orders,
    )