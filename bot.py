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

ASK_PRIORITY, ASK_CATEGORY, ASK_CATEGORY_TEXT, ASK_OWNER, ASK_TICKET, ASK_DEADLINE = range(6)


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
        [InlineKeyboardButton("✏️ Otra (escríbela)", callback_data="cat_other"),
         InlineKeyboardButton("❌ Cancelar", callback_data="cancel")],
    ])


def skip_keyboard(skip_data: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➡️ Saltar", callback_data=skip_data),
         InlineKeyboardButton("❌ Cancelar", callback_data="cancel")],
    ])


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name
    await update.message.reply_text(
        f"¡Hola {name}! 👋 Soy tu asistente de tareas.\n\n"
        "Usa los botones para navegar 👇",
        reply_markup=main_menu_keyboard()
    )


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("¿Qué quieres hacer? 👇", reply_markup=main_menu_keyboard())


def task_summary(ctx) -> str:
    d = ctx.user_data
    pri_icon = PRIORITY_EMOJI.get(d.get("priority", ""), "🟡")
    cat = d.get("category", "")
    cat_icon = CATEGORY_EMOJI.get(cat, "📌")
    lines = [f"📝 *{d.get('task_text', '')}*"]
    if d.get("priority"):
        lines.append(f"{pri_icon} {d['priority']}")
    if cat:
        lines.append(f"{cat_icon} {cat}")
    return "  ".join(lines)


# ── Entrada al flujo ──────────────────────────────────────────────────────────

async def start_new_task_from_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("📝 Cuéntame qué tienes que hacer:")
    return ASK_PRIORITY


async def free_text_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["task_text"] = update.message.text.strip()
    await update.message.reply_text(
        f"📝 *{context.user_data['task_text']}*\n\n¿Qué prioridad tiene?",
        parse_mode="Markdown",
        reply_markup=priority_keyboard()
    )
    return ASK_PRIORITY


async def received_task_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["task_text"] = update.message.text.strip()
    await update.message.reply_text(
        f"📝 *{context.user_data['task_text']}*\n\n¿Qué prioridad tiene?",
        parse_mode="Markdown",
        reply_markup=priority_keyboard()
    )
    return ASK_PRIORITY


# ── Paso: prioridad ───────────────────────────────────────────────────────────

async def received_priority(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["priority"] = query.data.replace("pri_", "")
    await query.edit_message_text(
        f"{task_summary(context)}\n\n¿En qué categoría va?",
        parse_mode="Markdown",
        reply_markup=category_keyboard()
    )
    return ASK_CATEGORY


# ── Paso: categoría ───────────────────────────────────────────────────────────

async def received_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "cat_other":
        await query.edit_message_text(
            f"{task_summary(context)}\n\n✏️ Escribe la categoría:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancelar", callback_data="cancel")]])
        )
        return ASK_CATEGORY_TEXT

    context.user_data["category"] = query.data.replace("cat_", "")
    await query.edit_message_text(
        f"{task_summary(context)}\n\n👤 ¿Quién es el responsable?\n_(escribe el nombre o salta)_",
        parse_mode="Markdown",
        reply_markup=skip_keyboard("skip_owner")
    )
    return ASK_OWNER


async def received_category_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["category"] = update.message.text.strip().lower()
    await update.message.reply_text(
        f"{task_summary(context)}\n\n👤 ¿Quién es el responsable?\n_(escribe el nombre o salta)_",
        parse_mode="Markdown",
        reply_markup=skip_keyboard("skip_owner")
    )
    return ASK_OWNER


# ── Paso: responsable ─────────────────────────────────────────────────────────

async def received_owner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["owner"] = update.message.text.strip()
    await update.message.reply_text(
        f"{task_summary(context)}\n\n🎫 ¿Tiene ticket de Yandex Tracker?\n_(ej: FLEETSUPPORT-2323, o salta)_",
        parse_mode="Markdown",
        reply_markup=skip_keyboard("skip_ticket")
    )
    return ASK_TICKET


async def skip_owner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["owner"] = update.effective_user.first_name
    await query.edit_message_text(
        f"{task_summary(context)}\n\n🎫 ¿Tiene ticket de Yandex Tracker?\n_(ej: FLEETSUPPORT-2323, o salta)_",
        parse_mode="Markdown",
        reply_markup=skip_keyboard("skip_ticket")
    )
    return ASK_TICKET


# ── Paso: ticket y guardar ────────────────────────────────────────────────────

async def received_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data["ticket"] = extract_ticket(text) or text
    await ask_deadline(update, context, from_callback=False)
    return ASK_DEADLINE


async def skip_ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["ticket"] = None
    await ask_deadline(update, context, from_callback=True)
    return ASK_DEADLINE


async def ask_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE, from_callback: bool):
    text = f"{task_summary(context)}\n\n📅 ¿Tiene fecha límite?\n_(escribe la fecha, ej: 15/06 o 15 jun, o salta)_"
    keyboard = skip_keyboard("skip_deadline")
    if from_callback:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)
    else:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def received_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["deadline"] = update.message.text.strip()
    await save_task(update, context, from_callback=False)
    return ConversationHandler.END


async def skip_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["deadline"] = None
    await save_task(update, context, from_callback=True)
    return ConversationHandler.END


async def save_task(update: Update, context: ContextTypes.DEFAULT_TYPE, from_callback: bool):
    d = context.user_data
    task = d["task_text"]
    priority = d.get("priority", "medium")
    category = d.get("category", "work")
    owner = d.get("owner", update.effective_user.first_name)
    ticket = d.get("ticket")

    deadline = d.get("deadline")
    row_id = sheets.add_task(task, category, priority, owner, source="manual", ticket=ticket, deadline=deadline)

    pri_icon = PRIORITY_EMOJI.get(priority, "🟡")
    cat_icon = CATEGORY_EMOJI.get(category, "📌")
    ticket_line = f"\n🎫 [{ticket}](https://st.yandex-team.ru/{ticket})" if ticket else ""
    deadline_line = f"\n📅 {deadline}" if deadline else ""

    text = (
        f"✅ ¡Tarea *#{row_id}* guardada!\n\n"
        f"📝 {task}\n"
        f"{pri_icon} {priority}  {cat_icon} {category}  👤 {owner}{ticket_line}{deadline_line}"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Otra tarea", callback_data="new_task"),
         InlineKeyboardButton("📋 Ver tareas", callback_data="list")],
        [InlineKeyboardButton("🏠 Menú", callback_data="menu")],
    ])

    if from_callback:
        await update.callback_query.edit_message_text(text, parse_mode="Markdown",
                                                       disable_web_page_preview=True,
                                                       reply_markup=keyboard)
    else:
        await update.message.reply_text(text, parse_mode="Markdown",
                                        disable_web_page_preview=True,
                                        reply_markup=keyboard)
    context.user_data.clear()


# ── Cancelar ──────────────────────────────────────────────────────────────────

async def cancel_conv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text("Cancelado. ¿Qué quieres hacer?", reply_markup=main_menu_keyboard())
    return ConversationHandler.END


# ── Ver tareas ────────────────────────────────────────────────────────────────

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
            deadline_part = f" · 📅 {t['deadline']}" if t.get("deadline") else ""
            lines.append(f"{pri_icon} *#{t['id']}* {t['task']}{ticket_part}\n   {cat_icon} {t['category']} · 👤 {t['owner']}{deadline_part}")
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


# ── Botones generales ─────────────────────────────────────────────────────────

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "list":
        await show_tasks(update, context, from_callback=True)

    elif data == "menu":
        await query.edit_message_text("¿Qué quieres hacer? 👇", reply_markup=main_menu_keyboard())

    elif data == "done_prompt":
        tasks = sheets.list_tasks()
        if not tasks:
            await query.edit_message_text(
                "🎉 ¡No hay tareas pendientes!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menú", callback_data="menu")]])
            )
            return
        lines = ["¿Cuál tarea completaste? 👇\n"]
        for t in tasks:
            lines.append(f"{PRIORITY_EMOJI.get(t['priority'], '🟡')} *#{t['id']}* {t['task']}")
        done_buttons = [InlineKeyboardButton(f"✅ #{t['id']}", callback_data=f"done_{t['id']}") for t in tasks]
        rows = [done_buttons[i:i+3] for i in range(0, len(done_buttons), 3)]
        rows.append([InlineKeyboardButton("🏠 Menú", callback_data="menu")])
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(rows))

    elif data.startswith("done_"):
        task_id = int(data.split("_")[1])
        if sheets.mark_done(task_id):
            await query.edit_message_text(
                f"🙌 ¡Genial! Tarea *#{task_id}* completada. Una menos 💪",
                parse_mode="Markdown", reply_markup=main_menu_keyboard()
            )
        else:
            await query.edit_message_text(f"🤔 No encontré la tarea #{task_id}.", reply_markup=main_menu_keyboard())


# ── Main ──────────────────────────────────────────────────────────────────────

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
            ASK_CATEGORY_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, received_category_text),
                CallbackQueryHandler(cancel_conv, pattern="^cancel$"),
            ],
            ASK_OWNER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, received_owner),
                CallbackQueryHandler(skip_owner, pattern="^skip_owner$"),
                CallbackQueryHandler(cancel_conv, pattern="^cancel$"),
            ],
            ASK_TICKET: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, received_ticket),
                CallbackQueryHandler(skip_ticket, pattern="^skip_ticket$"),
                CallbackQueryHandler(cancel_conv, pattern="^cancel$"),
            ],
            ASK_DEADLINE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, received_deadline),
                CallbackQueryHandler(skip_deadline, pattern="^skip_deadline$"),
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
