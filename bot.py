import os
import json
import asyncio
from flask import Flask, request
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from oauth2client.service_account import ServiceAccountCredentials
import gspread
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)

# Google Sheets setup
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
CREDS = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(os.environ.get('GOOGLE_CREDENTIALS')), SCOPE)
GC = gspread.authorize(CREDS)
SHEET = GC.open_by_key("107KiGCg82U5dkqHHmDbmkgbeYq8XCSI6ECneEfl2j2I").sheet1

# Telegram bot setup
async def init_application():
    application = Application.builder().token(os.environ.get('BOT_TOKEN')).build()
    await application.initialize()
    return application

application = asyncio.run(init_application())
WEBHOOK_URL = os.environ.get('WEBHOOK_URL', 'https://debre-amin-new-bot.onrender.com')
TELEGRAM_TOKEN = os.environ.get('BOT_TOKEN')

# Data (in memory for now)
COURSES = ["Prayer Basics", "Psalms Intro", "Church History"]
PROGRESS = {}

# Helper functions
def get_user_progress(user_id):
    return PROGRESS.get(user_id, {course: "Not Started" for course in COURSES})

def save_progress(user_id, course, progress):
    if user_id not in PROGRESS:
        PROGRESS[user_id] = {}
    PROGRESS[user_id][course] = progress
    SHEET.append_row([user_id, course, progress])

# Commands
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Courses", callback_data='courses')],
        [InlineKeyboardButton("Progress", callback_data='progress')],
        [InlineKeyboardButton("Admin", callback_data='admin')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Welcome! Choose an option:", reply_markup=reply_markup)

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = str(query.from_user.id)
    if query.data == 'courses':
        keyboard = [[InlineKeyboardButton(course, callback_data=f'select_{course}') for course in COURSES[i:i+2]] for i in range(0, len(COURSES), 2)]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Select a course:", reply_markup=reply_markup)
    elif query.data.startswith('select_'):
        course = query.data.replace('select_', '')
        progress = get_user_progress(user_id).get(course, "Not Started")
        await query.edit_message_text(f"Course: {course}\nProgress: {progress}\nUse /update_progress to change.")
    elif query.data == 'progress':
        progress = get_user_progress(user_id)
        message = "Your Progress:\n" + "\n".join([f"{course}: {prog}" for course, prog in progress.items()])
        await query.edit_message_text(message)
    elif query.data == 'admin' and user_id == '5899761420':
        keyboard = [[InlineKeyboardButton("Add Course", callback_data='add_course')], [InlineKeyboardButton("Upload File", callback_data='upload_file')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Admin Options:", reply_markup=reply_markup)

async def update_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Usage: /update_progress <course> <progress>")
        return
    course, progress = context.args[0], " ".join(context.args[1:])
    user_id = str(update.message.from_user.id)
    save_progress(user_id, course, progress)
    await update.message.reply_text(f"Updated {course} progress to: {progress}")

async def add_course(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    if user_id != '5899761420':
        await update.message.reply_text("Only admins can add courses.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /add_course <name>")
        return
    course = context.args[0]
    if course not in COURSES:
        COURSES.append(course)
        await update.message.reply_text(f"Added course: {course}")
    else:
        await update.message.reply_text(f"{course} already exists!")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    if user_id != '5899761420' or not update.message.document:
        await update.message.reply_text("Only admins can upload files.")
        return
    file = update.message.document
    if file.file_size <= 50 * 1024 * 1024 and file.mime_type == 'application/pdf':
        file_path = await application.bot.get_file(file.file_id)
        downloaded_file = await file_path.download_as_bytearray()
        with open(f"{file.file_name}", 'wb') as new_file:
            new_file.write(downloaded_file)
        await update.message.reply_text(f"Uploaded {file.file_name}")
    else:
        await update.message.reply_text("Please upload a PDF under 50MB.")

# Register handlers
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("update_progress", update_progress))
application.add_handler(CommandHandler("add_course", add_course))
application.add_handler(CallbackQueryHandler(button))
application.add_handler(MessageHandler(filters.Document.ALL & ~filters.Command(), handle_document))

# Flask webhook route
@app.route(f'/{TELEGRAM_TOKEN}', methods=['POST'])
def webhook():
    try:
        update_data = request.get_json(force=True)
        if not update_data:
            print("Empty request body received")
            return 'Bad Request', 400
        update = Update.de_json(update_data, application.bot)
        if not update:
            print("Invalid update data")
            return 'Bad Request', 400
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(application.process_update(update))
        finally:
            loop.close()
        return 'OK', 200
    except Exception as e:
        print(f"Webhook error: {str(e)}")
        return f'Error: {str(e)}', 500

# Route to set webhook
@app.route('/set_webhook', methods=['GET'])
def set_webhook():
    try:
        application.bot.set_webhook(url=f'{WEBHOOK_URL}/{TELEGRAM_TOKEN}')
        return f"Webhook set to {WEBHOOK_URL}/{TELEGRAM_TOKEN}", 200
    except Exception as e:
        return f"Failed to set webhook: {str(e)})", 500

# Default route
@app.route('/')
def home():
    return "Telegram bot is running!"

if __name__ == '__main__':
    from waitress import serve
    port = int(os.environ.get('PORT', 8443))
    serve(app, host='0.0.0.0', port=port)