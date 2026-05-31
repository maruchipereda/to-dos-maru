import os
import re
import logging
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv
import openai
import sheets

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

YANDEX_TRACKER_RE = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")
VALID_PRIORITIES = {"high", "medium", "low"}
VALID_CATEGORIES = {"work", "yango", "gr", "finance", "personal"}

openai.api_key = os.getenv("OPENAI_API_KEY")


def extract_ticket(text: str) -> str | None:
    match = YANDEX_TRACKER_RE.search(text)
    return match.group(1) if match else None


async def ai_parse_task(text: str) -> dict:
    prompt = (
        "Extract task details from the following message. "
        "Return JSON with keys: task (string), priority (high/medium/low), category (work/yango/gr/finance/personal). "
        "If unsure about priority default to medium, category default to work.\n\n"
        f"Message: {text}"
    )
    try:
        response = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=200,
        )
        import json
        data = json.loads(response.choices[0].message.content)
        task = data.get("task", text.strip())
        priority = data.get("priority", "medium").lower()
        category = data.get("category", "work").lower()
        if priority not in VALID_PRIORITIES:
            priority = "medium"
        if category not in VALID_CATEGORIES:
            category = "work"
        return {"task": task, "priority": priority, "category": category}
    except Exception as e:
        logger.error(f"AI parse error: {e}")
        return {"task": text.strip(), "priority": "medium", "category": "work"}


PRIORITY_EMOJI = {"high": "🔴", "medium": "🟡", "low": "🟢"}
CATEGORY_EMOJI = {"work": "💼", "yango": "🚕", "gr": "🏛️", "finance": "💰", "personal": "🙋"}


async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = " ".join(context.args)
    parts = [p.strip() for p in args.split("|")]
    if len(parts) < 1 or not parts[0]:
        await update.message.reply_text(
            "Casi! El formato es así:\n"
            "`/add tarea|prioridad|categoría|responsable`\n\n"
            "Por ejemplo:\n"
            "`/add Comprar café|low|personal|Maru`",
            parse_mode="Markdown"
        )
        return

    task = parts[0]
    priority = parts[1].lower() if len(parts) > 1 and parts[1] else "medium"
    category = parts[2].lower() if len(parts) > 2 and parts[2] else "work"
    owner = parts[3] if len(parts) > 3 and parts[3] else update.effective_user.first_name

    if priority not in VALID_PRIORITIES:
        priority = "medium"
    if category not in VALID_CATEGORIES:
        category = "work"

    ticket = extract_ticket(task)
    row_id = sheets.add_task(task, category, priority, owner, source="manual", ticket=ticket)
    ticket_link = f"\n🔗 Ticket: https://st.yandex-team.ru/{ticket}" if ticket else ""
    pri_icon = PRIORITY_EMOJI.get(priority, "🟡")
    cat_icon = CATEGORY_EMOJI.get(category, "📌")
    await update.message.reply_text(
        f"✅ ¡Listo! Agregué la tarea *#{row_id}*\n\n"
        f"📝 {task}\n"
        f"{pri_icon} Prioridad: {priority}  {cat_icon} Categoría: {category}{ticket_link}",
        parse_mode="Markdown"
    )


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tasks = sheets.list_tasks()
    if not tasks:
        await update.message.reply_text("🎉 ¡No hay tareas pendientes! Estás al día.")
        return

    lines = [f"📋 *Tus tareas pendientes* ({len(tasks)} en total)\n"]
    for t in tasks:
        ticket_part = f" [{t['ticket']}](https://st.yandex-team.ru/{t['ticket']})" if t.get("ticket") else ""
        pri_icon = PRIORITY_EMOJI.get(t['priority'], "🟡")
        cat_icon = CATEGORY_EMOJI.get(t['category'], "📌")
        lines.append(
            f"{pri_icon} *#{t['id']}* {t['task']}{ticket_part}\n"
            f"   {cat_icon} {t['category']} · 👤 {t['owner']}"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", disable_web_page_preview=True)


async def cmd_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Dime el número de la tarea 😊 Ej: `/done 3`", parse_mode="Markdown")
        return
    try:
        task_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Hmm, eso no parece un número válido. Prueba con `/done 3` por ejemplo.", parse_mode="Markdown")
        return

    success = sheets.mark_done(task_id)
    if success:
        await update.message.reply_text(f"🙌 ¡Excelente! La tarea *#{task_id}* está lista. Una menos en la lista 💪", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"🤔 No encontré la tarea *#{task_id}*. Usa /list para ver las que tienes.", parse_mode="Markdown")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name
    text = (
        f"¡Hola {name}! 👋 Soy tu asistente de tareas. Aquí te explico cómo usarme:\n\n"
        "💬 *Escríbeme cualquier cosa* y yo creo la tarea automáticamente. Así de fácil.\n\n"
        "📌 *Comandos disponibles:*\n"
        "/add tarea|prioridad|categoría|responsable — Agregar tarea manualmente\n"
        "/list — Ver todas tus tareas pendientes\n"
        "/done <número> — Marcar una tarea como completada\n"
        "/help — Ver este mensaje\n\n"
        "🎯 *Prioridades:* high 🔴 · medium 🟡 · low 🟢\n"
        "📂 *Categorías:* work 💼 · yango 🚕 · gr 🏛️ · finance 💰 · personal 🙋\n\n"
        "💡 Si mencionas un código de Yandex Tracker (ej. FLEETSUPPORT-2323), lo enlazo automáticamente."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def handle_free_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text:
        return

    parsed = await ai_parse_task(text)
    ticket = extract_ticket(text)
    owner = update.effective_user.first_name

    row_id = sheets.add_task(
        parsed["task"], parsed["category"], parsed["priority"],
        owner, source="ai", ticket=ticket
    )
    ticket_link = f"\n🔗 Ticket: https://st.yandex-team.ru/{ticket}" if ticket else ""
    pri_icon = PRIORITY_EMOJI.get(parsed["priority"], "🟡")
    cat_icon = CATEGORY_EMOJI.get(parsed["category"], "📌")
    await update.message.reply_text(
        f"🤖 ¡Entendido! Creé la tarea *#{row_id}*\n\n"
        f"📝 {parsed['task']}\n"
        f"{pri_icon} Prioridad: {parsed['priority']}  {cat_icon} Categoría: {parsed['category']}{ticket_link}",
        parse_mode="Markdown"
    )


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN not set")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("done", cmd_done))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("start", cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_free_text))

    logger.info("Bot started")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
