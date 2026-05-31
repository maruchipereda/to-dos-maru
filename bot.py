import os
import re
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters, ContextTypes
)
from dotenv import load_dotenv
import openai
import sheets

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

YANDEX_TRACKER_RE = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")
VALID_PRIORITIES = {"high", "medium", "low"}
VALID_CATEGORIES = {"work", "yango", "gr", "finance", "personal"}

PRIORITY_EMOJI = {"high": "🔴", "medium": "🟡", "low": "🟢"}
CATEGORY_EMOJI = {"work": "💼", "yango": "🚕", "gr": "🏛️", "finance": "💰", "personal": "🙋"}

openai.api_key = os.getenv("OPENAI_API_KEY")

# ConversationHandler states
WAITING_DONE_ID = 1


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


def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Ver tareas", callback_data="list"),
         InlineKeyboardButton("✅ Completar tarea", callback_data="done_prompt")],
        [InlineKeyboardButton("❓ Ayuda", callback_data="help")],
    ])


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name
    await update.message.reply_text(
        f"¡Hola {name}! 👋 Soy tu asistente de tareas.\n\n"
        "💬 *Escríbeme cualquier cosa* y creo la tarea automáticamente.\n"
        "O usá los botones de abajo para ver y gestionar tus tareas 👇",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard()
    )


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "¿Qué querés hacer? 👇",
        reply_markup=main_menu_keyboard()
    )


async def show_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE, from_callback=False):
    tasks = sheets.list_tasks()

    if not tasks:
        text = "🎉 ¡No hay tareas pendientes! Estás al día."
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menú", callback_data="menu")]])
    else:
        lines = [f"📋 *Tus tareas pendientes* ({len(tasks)} en total)\n"]
        for t in tasks:
            ticket_part = f" [{t['ticket']}](https://st.yandex-team.ru/{t['ticket']})" if t.get("ticket") else ""
            pri_icon = PRIORITY_EMOJI.get(t["priority"], "🟡")
            cat_icon = CATEGORY_EMOJI.get(t["category"], "📌")
            lines.append(
                f"{pri_icon} *#{t['id']}* {t['task']}{ticket_part}\n"
                f"   {cat_icon} {t['category']} · 👤 {t['owner']}"
            )
        text = "\n".join(lines)

        # Build done buttons for each task
        done_buttons = [
            InlineKeyboardButton(f"✅ #{t['id']}", callback_data=f"done_{t['id']}")
            for t in tasks
        ]
        rows = [done_buttons[i:i+3] for i in range(0, len(done_buttons), 3)]
        rows.append([InlineKeyboardButton("🏠 Menú", callback_data="menu")])
        keyboard = InlineKeyboardMarkup(rows)

    if from_callback:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown",
                                                       disable_web_page_preview=True,
                                                       reply_markup=keyboard)
    else:
        await update.message.reply_text(text, parse_mode="Markdown",
                                        disable_web_page_preview=True,
                                        reply_markup=keyboard)


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_tasks(update, context, from_callback=False)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "list":
        await show_tasks(update, context, from_callback=True)

    elif data == "menu":
        await query.edit_message_text("¿Qué querés hacer? 👇", reply_markup=main_menu_keyboard())

    elif data == "help":
        text = (
            "💡 *Cómo usarme:*\n\n"
            "💬 *Texto libre* — escribime lo que tenés que hacer y yo lo agrego automáticamente.\n\n"
            "📋 *Ver tareas* — te muestro todo lo pendiente con botones para completar cada una.\n\n"
            "✅ *Completar* — marcá una tarea como lista directo desde la lista.\n\n"
            "🎯 *Prioridades:* high 🔴 · medium 🟡 · low 🟢\n"
            "📂 *Categorías:* work 💼 · yango 🚕 · gr 🏛️ · finance 💰 · personal 🙋\n\n"
            "💡 Los códigos de Yandex Tracker (ej. FLEETSUPPORT-2323) se detectan solos."
        )
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menú", callback_data="menu")]])
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)

    elif data == "done_prompt":
        tasks = sheets.list_tasks()
        if not tasks:
            await query.edit_message_text(
                "🎉 ¡No hay tareas pendientes!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menú", callback_data="menu")]])
            )
            return
        lines = ["¿Cuál querés completar? Tocá el botón 👇\n"]
        for t in tasks:
            pri_icon = PRIORITY_EMOJI.get(t["priority"], "🟡")
            lines.append(f"{pri_icon} *#{t['id']}* {t['task']}")
        done_buttons = [
            InlineKeyboardButton(f"✅ #{t['id']}", callback_data=f"done_{t['id']}")
            for t in tasks
        ]
        rows = [done_buttons[i:i+3] for i in range(0, len(done_buttons), 3)]
        rows.append([InlineKeyboardButton("🏠 Menú", callback_data="menu")])
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(rows))

    elif data.startswith("done_"):
        task_id = int(data.split("_")[1])
        success = sheets.mark_done(task_id)
        if success:
            await query.edit_message_text(
                f"🙌 ¡Genial! La tarea *#{task_id}* está completada. Una menos 💪\n\n¿Qué más querés hacer?",
                parse_mode="Markdown",
                reply_markup=main_menu_keyboard()
            )
        else:
            await query.edit_message_text(
                f"🤔 No encontré la tarea #{task_id}.",
                reply_markup=main_menu_keyboard()
            )


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
    ticket_link = f"\n🔗 https://st.yandex-team.ru/{ticket}" if ticket else ""
    pri_icon = PRIORITY_EMOJI.get(parsed["priority"], "🟡")
    cat_icon = CATEGORY_EMOJI.get(parsed["category"], "📌")

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Ver todas las tareas", callback_data="list")],
        [InlineKeyboardButton("🏠 Menú", callback_data="menu")],
    ])

    await update.message.reply_text(
        f"🤖 ¡Listo! Guardé la tarea *#{row_id}*\n\n"
        f"📝 {parsed['task']}\n"
        f"{pri_icon} {parsed['priority']}  {cat_icon} {parsed['category']}{ticket_link}",
        parse_mode="Markdown",
        reply_markup=keyboard
    )


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN not set")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("help", cmd_menu))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_free_text))

    logger.info("Bot started")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
