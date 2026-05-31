import os
import re
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters, ContextTypes
)
from dotenv import load_dotenv
import sheets

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

YANDEX_TRACKER_RE = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")
PRIORITY_EMOJI = {"high": "🔴", "medium": "🟡", "low": "🟢"}
CATEGORY_EMOJI = {"work": "💼", "yango": "🚕", "gr": "🏛️", "finance": "💰", "personal": "🙋"}

# ConversationHandler states
ASK_PRIORITY, ASK_CATEGORY = range(2)


def extract_ticket(text: str) -> str | None:
    match = YANDEX_TRACKER_RE.search(text)
    return match.group(1) if match else None


def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Nueva tarea", callback_data="new_task"),
         InlineKeyboardButton("📋 Ver tareas", callback_data="list")],
        [InlineKeyboardButton("✅ Completar tarea", callback_data="done_prompt")],
    ])


def priority_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔴 Alta", callback_data="pri_high"),
         InlineKeyboardButton("🟡 Media", callback_data="pri_medium"),
         InlineKeyboardButton("🟢 Baja", callback_data="pri_low")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="cancel")],
    ])


def category_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💼 Work", callback_data="cat_work"),
         InlineKeyboardButton("🚕 Yango", callback_data="cat_yango")],
        [InlineKeyboardButton("🏛️ GR", callback_data="cat_gr"),
         InlineKeyboardButton("💰 Finance", callback_data="cat_finance")],
        [InlineKeyboardButton("🙋 Personal", callback_data="cat_personal")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="cancel")],
    ])


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name
    await update.message.reply_text(
        f"¡Hola {name}! 👋 Soy tu asistente de tareas.\n\n"
        "Usá los botones para navegar 👇",
        reply_markup=main_menu_keyboard()
    )


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¿Qué querés hacer? 👇", reply_markup=main_menu_keyboard())


# ── Nueva tarea: paso 1 — texto libre ────────────────────────────────────────

async def start_new_task_from_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Triggered by ➕ Nueva tarea button"""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("📝 Contame qué tenés que hacer:")
    return ASK_PRIORITY


async def free_text_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Free text message starts task creation flow"""
    context.user_data["task_text"] = update.message.text.strip()
    context.user_data["ticket"] = extract_ticket(update.message.text)
    await update.message.reply_text(
        f"📝 *{context.user_data['task_text']}*\n\n¿Qué prioridad tiene?",
        parse_mode="Markdown",
        reply_markup=priority_keyboard()
    )
    return ASK_PRIORITY


async def received_task_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receives task text after ➕ button flow"""
    context.user_data["task_text"] = update.message.text.strip()
    context.user_data["ticket"] = extract_ticket(update.message.text)
    await update.message.reply_text(
        f"📝 *{context.user_data['task_text']}*\n\n¿Qué prioridad tiene?",
        parse_mode="Markdown",
        reply_markup=priority_keyboard()
    )
    return ASK_PRIORITY


# ── Paso 2 — prioridad ───────────────────────────────────────────────────────

async def received_priority(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    priority = query.data.replace("pri_", "")
    context.user_data["priority"] = priority
    pri_icon = PRIORITY_EMOJI[priority]
    await query.edit_message_text(
        f"📝 *{context.user_data['task_text']}*\n"
        f"{pri_icon} Prioridad: *{priority}*\n\n¿En qué categoría va?",
        parse_mode="Markdown",
        reply_markup=category_keyboard()
    )
    return ASK_CATEGORY


# ── Paso 3 — categoría y guardar ────────────────────────────────────────────

async def received_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category = query.data.replace("cat_", "")
    context.user_data["category"] = category

    task = context.user_data["task_text"]
    priority = context.user_data["priority"]
    ticket = context.user_data.get("ticket")
    owner = update.effective_user.first_name

    row_id = sheets.add_task(task, category, priority, owner, source="manual", ticket=ticket)

    pri_icon = PRIORITY_EMOJI[priority]
    cat_icon = CATEGORY_EMOJI[category]
    ticket_link = f"\n🔗 https://st.yandex-team.ru/{ticket}" if ticket else ""

    await query.edit_message_text(
        f"✅ ¡Tarea *#{row_id}* guardada!\n\n"
        f"📝 {task}\n"
        f"{pri_icon} {priority}  {cat_icon} {category}{ticket_link}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Otra tarea", callback_data="new_task"),
             InlineKeyboardButton("📋 Ver tareas", callback_data="list")],
            [InlineKeyboardButton("🏠 Menú", callback_data="menu")],
        ])
    )
    context.user_data.clear()
    return ConversationHandler.END


async def cancel_conv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text("Cancelado. ¿Qué querés hacer?", reply_markup=main_menu_keyboard())
    return ConversationHandler.END


# ── Ver tareas ───────────────────────────────────────────────────────────────

async def show_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE, from_callback=False):
    tasks = sheets.list_tasks()

    if not tasks:
        text = "🎉 ¡No hay tareas pendientes! Estás al día."
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menú", callback_data="menu")]])
    else:
        lines = [f"📋 *Tareas pendientes* ({len(tasks)})\n"]
        for t in tasks:
            ticket_part = f" [{t['ticket']}](https://st.yandex-team.ru/{t['ticket']})" if t.get("ticket") else ""
            pri_icon = PRIORITY_EMOJI.get(t["priority"], "🟡")
            cat_icon = CATEGORY_EMOJI.get(t["category"], "📌")
            lines.append(f"{pri_icon} *#{t['id']}* {t['task']}{ticket_part}\n   {cat_icon} {t['category']} · 👤 {t['owner']}")
        text = "\n".join(lines)
        done_buttons = [InlineKeyboardButton(f"✅ #{t['id']}", callback_data=f"done_{t['id']}") for t in tasks]
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


# ── Botones generales ────────────────────────────────────────────────────────

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "list":
        await show_tasks(update, context, from_callback=True)

    elif data == "menu":
        await query.edit_message_text("¿Qué querés hacer? 👇", reply_markup=main_menu_keyboard())

    elif data == "done_prompt":
        tasks = sheets.list_tasks()
        if not tasks:
            await query.edit_message_text(
                "🎉 ¡No hay tareas pendientes!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menú", callback_data="menu")]])
            )
            return
        lines = ["¿Cuál completaste? Tocá el botón 👇\n"]
        for t in tasks:
            lines.append(f"{PRIORITY_EMOJI.get(t['priority'], '🟡')} *#{t['id']}* {t['task']}")
        done_buttons = [InlineKeyboardButton(f"✅ #{t['id']}", callback_data=f"done_{t['id']}") for t in tasks]
        rows = [done_buttons[i:i+3] for i in range(0, len(done_buttons), 3)]
        rows.append([InlineKeyboardButton("🏠 Menú", callback_data="menu")])
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(rows))

    elif data.startswith("done_"):
        task_id = int(data.split("_")[1])
        success = sheets.mark_done(task_id)
        if success:
            await query.edit_message_text(
                f"🙌 ¡Genial! Tarea *#{task_id}* completada. Una menos 💪",
                parse_mode="Markdown",
                reply_markup=main_menu_keyboard()
            )
        else:
            await query.edit_message_text(f"🤔 No encontré la tarea #{task_id}.", reply_markup=main_menu_keyboard())


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN not set")

    app = Application.builder().token(token).build()

    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_new_task_from_button, pattern="^new_task$"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, free_text_start),
        ],
        states={
            ASK_PRIORITY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, received_task_text),
                CallbackQueryHandler(received_priority, pattern="^pri_"),
                CallbackQueryHandler(cancel_conv, pattern="^cancel$"),
            ],
            ASK_CATEGORY: [
                CallbackQueryHandler(received_category, pattern="^cat_"),
                CallbackQueryHandler(cancel_conv, pattern="^cancel$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", lambda u, c: ConversationHandler.END),
            CallbackQueryHandler(cancel_conv, pattern="^cancel$"),
        ],
        per_message=False,
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Bot started")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
