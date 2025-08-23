#!/usr/bin/env python3
"""
Webhook-based Telegram Quiz Bot for PythonAnywhere Free Plan
Fixed version with proper async handling
"""

import json
import logging
import os
import sys
import time
import requests
from datetime import datetime
from flask import Flask, request, jsonify

# Configure logging to be less verbose
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Suppress noisy library logs
for logger_name in ['urllib3', 'requests', 'telegram']:
    logging.getLogger(logger_name).setLevel(logging.CRITICAL)

# Initialize Flask app
app = Flask(__name__)

# Bot token - REPLACE WITH YOUR ACTUAL TOKEN
BOT_TOKEN = "Pls add your bot token here"

# Validate token
if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
    print("❌ ERROR: Please set your actual bot token!")
    sys.exit(1)

# Telegram API base URL
TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Simple in-memory storage
user_data = {}
bot_stats = {
    'total_requests': 0,
    'successful_polls': 0,
    'errors': 0,
    'start_time': time.time()
}

# Memory management
MAX_USERS = 100
USER_TTL = 1800  # 30 minutes

def cleanup_old_users():
    """Clean up old user data to prevent memory issues"""
    try:
        current_time = time.time()
        if len(user_data) <= MAX_USERS:
            return
        
        # Remove users older than TTL
        to_remove = []
        for user_id, data in user_data.items():
            if current_time - data.get('last_activity', 0) > USER_TTL:
                to_remove.append(user_id)
        
        for user_id in to_remove:
            user_data.pop(user_id, None)
            
        # If still too many, keep only the most recent
        if len(user_data) > MAX_USERS:
            sorted_users = sorted(
                user_data.items(), 
                key=lambda x: x[1].get('last_activity', 0), 
                reverse=True
            )
            user_data.clear()
            for user_id, data in sorted_users[:MAX_USERS//2]:
                user_data[user_id] = data
                
    except Exception:
        # If cleanup fails, clear everything
        user_data.clear()

def make_telegram_request(method, data=None):
    """Make requests to Telegram API using requests library"""
    try:
        url = f"{TELEGRAM_API_URL}/{method}"
        
        if data:
            response = requests.post(url, json=data, timeout=30)
        else:
            response = requests.get(url, timeout=30)
            
        if response.status_code == 200:
            return response.json()
        else:
            logging.warning(f"Telegram API error: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        logging.warning(f"Request error: {e}")
        bot_stats['errors'] += 1
        return None

def safe_send_message(chat_id, text, reply_markup=None, parse_mode=None):
    """Send message using requests"""
    try:
        # Sanitize text
        text = str(text)[:4000]  # Telegram limit
        if not text.strip():
            text = "Empty message"
            
        data = {
            'chat_id': chat_id,
            'text': text
        }
        
        if parse_mode:
            data['parse_mode'] = parse_mode
            
        if reply_markup:
            data['reply_markup'] = reply_markup
            
        result = make_telegram_request('sendMessage', data)
        return result is not None
        
    except Exception as e:
        logging.warning(f"Send message error: {e}")
        bot_stats['errors'] += 1
        return False

def safe_send_poll(chat_id, question, options, correct_id, explanation=None, is_anonymous=True):
    """Send quiz poll using requests"""
    try:
        # Sanitize inputs
        question = str(question)[:255]
        options = [str(opt)[:100] for opt in options[:4]]
        
        if len(options) < 2:
            options = ["Option A", "Option B"]
            
        if not isinstance(correct_id, int) or correct_id < 0 or correct_id >= len(options):
            correct_id = 0
            
        data = {
            'chat_id': chat_id,
            'question': question,
            'options': options,
            'type': 'quiz',
            'correct_option_id': correct_id,
            'is_anonymous': is_anonymous
        }
        
        if explanation:
            data['explanation'] = str(explanation)[:200]
            
        result = make_telegram_request('sendPoll', data)
        if result:
            bot_stats['successful_polls'] += 1
            return True
        return False
        
    except Exception as e:
        logging.warning(f"Send poll error: {e}")
        bot_stats['errors'] += 1
        return False

def answer_callback_query(callback_query_id, text=""):
    """Answer callback query using requests"""
    try:
        data = {
            'callback_query_id': callback_query_id,
            'text': text
        }
        make_telegram_request('answerCallbackQuery', data)
    except Exception:
        pass

def edit_message_text(chat_id, message_id, text, parse_mode=None):
    """Edit message text using requests"""
    try:
        data = {
            'chat_id': chat_id,
            'message_id': message_id,
            'text': str(text)[:4000],
        }
        
        if parse_mode:
            data['parse_mode'] = parse_mode
            
        return make_telegram_request('editMessageText', data) is not None
        
    except Exception:
        return False

def update_user_activity(user_id):
    """Update user activity timestamp"""
    if user_id not in user_data:
        user_data[user_id] = {}
    user_data[user_id]['last_activity'] = time.time()

@app.route('/')
def home():
    """Home page with bot status"""
    uptime = time.time() - bot_stats['start_time']
    hours = int(uptime // 3600)
    minutes = int((uptime % 3600) // 60)
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Quiz Bot Status</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; }}
            .status {{ color: green; }}
            .stats {{ background: #f5f5f5; padding: 20px; border-radius: 10px; }}
            .button {{ display: inline-block; padding: 10px 20px; background: #007bff; color: white; text-decoration: none; border-radius: 5px; margin: 5px; }}
        </style>
    </head>
    <body>
        <h1>🎯 Telegram Quiz Bot</h1>
        <p class="status"><strong>Status:</strong> 🟢 Online</p>
        
        <div class="stats">
            <h3>📊 Statistics</h3>
            <p><strong>Uptime:</strong> {hours}h {minutes}m</p>
            <p><strong>Total Requests:</strong> {bot_stats['total_requests']}</p>
            <p><strong>Successful Polls:</strong> {bot_stats['successful_polls']}</p>
            <p><strong>Errors:</strong> {bot_stats['errors']}</p>
            <p><strong>Active Users:</strong> {len(user_data)}</p>
        </div>
        
        <h3>🔗 Quick Actions</h3>
        <a href="/set_webhook" class="button">Set Webhook</a>
        <a href="/webhook_info" class="button">Check Webhook</a>
        <a href="/debug" class="button">Debug Info</a>
        <a href="/clear_pending" class="button">Clear Pending Updates</a>
        
        <h3>📱 Bot Usage</h3>
        <p>Start a chat with your bot on Telegram and use /start</p>
        
        <footer style="margin-top: 40px; color: #666;">
            <p>Running on PythonAnywhere Free Plan 🚀</p>
        </footer>
    </body>
    </html>
    """
    return html

@app.route(f'/{BOT_TOKEN}', methods=['POST'])
def webhook():
    """Handle incoming Telegram updates via webhook"""
    try:
        bot_stats['total_requests'] += 1
        
        # Clean up old users periodically
        if bot_stats['total_requests'] % 100 == 0:
            cleanup_old_users()
            
        json_str = request.get_data().decode('UTF-8')
        update_data = json.loads(json_str)

        if 'message' in update_data:
            handle_message(update_data)
        elif 'callback_query' in update_data:
            handle_callback(update_data)

        return jsonify({"ok": True})
        
    except Exception as e:
        logging.error(f"Webhook error: {e}")
        bot_stats['errors'] += 1
        return jsonify({"error": str(e)}), 500

def handle_message(update_data):
    """Handle text messages"""
    try:
        message = update_data['message']
        user_id = message['from']['id']
        text = message.get('text', '').strip()
        chat_id = message['chat']['id']
        user_name = message['from'].get('first_name', 'Friend')

        update_user_activity(user_id)

        if text.startswith('/start'):
            handle_start(chat_id, user_id, user_name)
        elif text.startswith('/help'):
            handle_help(chat_id)
        elif text.startswith('/status'):
            handle_status(chat_id, user_id)
        elif text.startswith('/template'):
            handle_template(chat_id)
        elif text.startswith('{') or '"all_q"' in text:
            handle_json(chat_id, user_id, text)
        else:
            safe_send_message(
                chat_id, 
                "🎯 **Welcome!** Use /start to create quizzes! ✨",
                parse_mode='Markdown'
            )
            
    except Exception as e:
        logging.error(f"Message handling error: {e}")

def handle_start(chat_id, user_id, user_name):
    """Handle start command"""
    try:
        user_data[user_id] = {
            "state": "choosing_type",
            "last_activity": time.time()
        }

        welcome_msg = (
            f"👋 **Hello {user_name}!** 🌟\n\n"
            "🎯 **Simple Quiz Bot** ⚡\n\n"
            "✨ Create MCQ quizzes instantly!\n\n"
            "💡 **How it works:**\n"
            "1️⃣ Choose quiz type below\n"
            "2️⃣ Get JSON template\n"
            "3️⃣ Customize with your questions\n"
            "4️⃣ Send back → Get instant quizzes! 🚀"
        )

        keyboard = {
            "inline_keyboard": [
                [{"text": "🔒 Anonymous Quiz (Can forward anywhere)", "callback_data": "anon_true"}],
                [{"text": "👤 Non-Anonymous Quiz (Shows voters)", "callback_data": "anon_false"}]
            ]
        }

        result = safe_send_message(
            chat_id,
            welcome_msg,
            keyboard,
            parse_mode='Markdown'
        )
        
        if not result:
            # Fallback without markdown
            safe_send_message(
                chat_id,
                f"Hello {user_name}! Choose your quiz type:",
                keyboard
            )
            
    except Exception as e:
        logging.error(f"Start handling error: {e}")

def handle_help(chat_id):
    """Handle help command"""
    help_text = (
        "🆘 **Quiz Bot Help** 📚\n\n"
        "🤖 **Commands:**\n"
        "• `/start` - Begin quiz creation\n"
        "• `/template` - Get JSON template\n"
        "• `/help` - Show this help\n"
        "• `/status` - Check bot status\n\n"
        "📚 **JSON Format:**\n"
        "• `all_q` - Questions array\n"
        "• `q` - Question text\n"
        "• `o` - Answer options (2-4 choices)\n"
        "• `c` - Correct answer (0=A, 1=B, 2=C, 3=D)\n"
        "• `e` - Explanation (optional)\n\n"
        "🚀 **Quick Start:** Use /start and follow the steps!"
    )
    
    result = safe_send_message(chat_id, help_text, parse_mode='Markdown')
    if not result:
        safe_send_message(chat_id, "Bot Help: Use /start to create quizzes. Send JSON with your questions.")

def handle_status(chat_id, user_id):
    """Handle status command"""
    uptime = time.time() - bot_stats['start_time']
    hours = int(uptime // 3600)
    minutes = int((uptime % 3600) // 60)
    
    user_type = "🔒 Anonymous" if user_data.get(user_id, {}).get('anonymous', True) else "👤 Non-Anonymous"
    
    status_msg = (
        f"📊 **Bot Status** 🟢\n\n"
        f"⏱️ **Uptime:** {hours}h {minutes}m\n"
        f"📈 **Total Requests:** {bot_stats['total_requests']}\n"
        f"🎯 **Successful Polls:** {bot_stats['successful_polls']}\n"
        f"👥 **Active Users:** {len(user_data)}\n"
        f"🎭 **Your Quiz Type:** {user_type}\n\n"
        f"🚀 **Ready to create quizzes!** ✨"
    )
    
    result = safe_send_message(chat_id, status_msg, parse_mode='Markdown')
    if not result:
        safe_send_message(chat_id, f"Bot Status: Online\nUptime: {hours}h {minutes}m\nReady to create quizzes!")

def handle_template(chat_id):
    """Handle template command"""
    template = '{"all_q":[{"q":"Capital of France? 🇫🇷","o":["London","Paris","Berlin","Madrid"],"c":1,"e":"Paris is the capital and largest city of France 🗼"},{"q":"What is 2+2? 🔢","o":["3","4","5","6"],"c":1,"e":"Basic addition: 2+2=4 ✅"}]}'
    
    safe_send_message(chat_id, "📋 **JSON Template:**", parse_mode='Markdown')
    safe_send_message(chat_id, template)
    safe_send_message(
        chat_id, 
        "💡 **Copy above → Give to ChatGPT → Ask to customize with your questions!** 🤖✨",
        parse_mode='Markdown'
    )

def handle_callback(update_data):
    """Handle button callbacks"""
    try:
        callback_query = update_data['callback_query']
        user_id = callback_query['from']['id']
        chat_id = callback_query['message']['chat']['id']
        message_id = callback_query['message']['message_id']
        callback_data = callback_query['data']

        # Answer callback to remove loading state
        answer_callback_query(callback_query['id'])

        update_user_activity(user_id)

        is_anonymous = callback_data == "anon_true"
        user_data[user_id] = {
            "state": "waiting_json",
            "anonymous": is_anonymous,
            "last_activity": time.time()
        }

        quiz_type = "🔒 Anonymous" if is_anonymous else "👤 Non-Anonymous"
        
        # Edit the message
        edit_success = edit_message_text(
            chat_id,
            message_id,
            f"✅ **{quiz_type} Quiz Selected!** 🎉\n\n⭐ **JSON template coming...** ⚡",
            parse_mode='Markdown'
        )

        if not edit_success:
            safe_send_message(chat_id, f"{quiz_type} quiz selected!")

        # Send template
        template = '{"all_q":[{"q":"Sample question?","o":["Option A","Option B","Option C","Option D"],"c":1,"e":"Explanation here"}]}'
        safe_send_message(chat_id, "📋 **JSON Template:**", parse_mode='Markdown')
        safe_send_message(chat_id, template)
        
        instruction_msg = (
            f"✅ **{quiz_type} Quiz Selected!** 🎉\n\n"
            "📝 **Next Steps:**\n"
            "1️⃣ Copy the above JSON template\n"
            "2️⃣ Give it to ChatGPT/AI 🤖\n"
            "3️⃣ Ask to customize with your questions in our format\n\n"
            "🚀 **Then send me your customized JSON:** 👇⚡"
        )
        
        result = safe_send_message(chat_id, instruction_msg, parse_mode='Markdown')
        if not result:
            safe_send_message(chat_id, f"{quiz_type} selected! Send your quiz JSON now!")
            
    except Exception as e:
        logging.error(f"Callback handling error: {e}")

def handle_json(chat_id, user_id, json_text):
    """Handle JSON quiz data"""
    try:
        user_info = user_data.get(user_id, {})
        if user_info.get("state") != "waiting_json":
            safe_send_message(chat_id, "🔄 **Please use /start first!** ✨", parse_mode='Markdown')
            return

        # Parse JSON
        quiz_data = json.loads(json_text)
        questions = quiz_data.get("all_q", [])

        if not questions:
            safe_send_message(
                chat_id, 
                "❌ **No questions found!** Use /template for correct format 📋",
                parse_mode='Markdown'
            )
            return

        is_anonymous = user_info.get("anonymous", True)
        
        # Send processing message
        safe_send_message(
            chat_id, 
            "🔄 **Processing your quiz...** ⚡",
            parse_mode='Markdown'
        )

        success_count = 0
        max_questions = 20  # Limit for free plan

        for i, q_data in enumerate(questions[:max_questions]):
            try:
                question = q_data.get("q", f"Question {i+1}")
                options = q_data.get("o", ["Option A", "Option B"])
                correct_id = q_data.get("c", 0)
                explanation = q_data.get("e", "")

                if len(options) >= 2:
                    result = safe_send_poll(
                        chat_id, question, options,
                        correct_id, explanation, is_anonymous
                    )
                    if result:
                        success_count += 1
                    
                    # Small delay to avoid rate limits
                    if i < len(questions) - 1:
                        time.sleep(0.1)
                        
            except Exception as e:
                logging.warning(f"Question {i+1} error: {e}")
                continue

        quiz_type = "🔒 Anonymous" if is_anonymous else "👤 Non-Anonymous"
        completion_msg = f"🎯 **{success_count} {quiz_type} quizzes sent successfully!** ✅🎉"
        
        safe_send_message(chat_id, completion_msg, parse_mode='Markdown')

        # Reset user state for next quiz
        user_data[user_id] = {
            "state": "choosing_type",
            "last_activity": time.time()
        }
        
        # Offer to create another quiz
        safe_send_message(
            chat_id,
            "🎉 **Want to create another quiz?** Use /start! 🚀",
            parse_mode='Markdown'
        )

    except json.JSONDecodeError:
        safe_send_message(
            chat_id, 
            "❌ **Invalid JSON format!** Use /template for correct format 📋",
            parse_mode='Markdown'
        )
    except Exception as e:
        logging.error(f"JSON handling error: {e}")
        safe_send_message(
            chat_id, 
            "❌ **Error processing quiz!** Please try again 🔄",
            parse_mode='Markdown'
        )

@app.route('/set_webhook', methods=['GET'])
def set_webhook():
    """Set webhook URL"""
    try:
        webhook_url = f"https://vivekreddy0.pythonanywhere.com/{BOT_TOKEN}"
        
        data = {
            'url': webhook_url,
            'drop_pending_updates': True  # Clear pending updates
        }
        
        result = make_telegram_request('setWebhook', data)
        
        if result and result.get('ok'):
            return f"✅ Webhook set successfully!<br>URL: {webhook_url}<br>Result: {result.get('description', 'Success')}"
        else:
            return f"❌ Failed to set webhook: {result}"
            
    except Exception as e:
        return f"❌ Webhook setup error: {e}"

@app.route('/webhook_info', methods=['GET'])
def webhook_info():
    """Get webhook information"""
    try:
        result = make_telegram_request('getWebhookInfo')
        
        if result and result.get('ok'):
            info = result.get('result', {})
            return jsonify({
                "url": info.get('url', ''),
                "has_custom_certificate": info.get('has_custom_certificate', False),
                "pending_update_count": info.get('pending_update_count', 0),
                "last_error_date": info.get('last_error_date'),
                "last_error_message": info.get('last_error_message'),
                "max_connections": info.get('max_connections'),
                "allowed_updates": info.get('allowed_updates', [])
            })
        else:
            return jsonify({"error": "Failed to get webhook info", "result": result})
            
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/clear_pending', methods=['GET'])
def clear_pending():
    """Clear pending updates"""
    try:
        # First delete the webhook
        make_telegram_request('deleteWebhook')
        
        # Set webhook again with drop_pending_updates=True
        webhook_url = f"https://vivekreddy0.pythonanywhere.com/{BOT_TOKEN}"
        data = {
            'url': webhook_url,
            'drop_pending_updates': True
        }
        
        result = make_telegram_request('setWebhook', data)
        
        if result and result.get('ok'):
            return "✅ Pending updates cleared and webhook reset!"
        else:
            return f"❌ Error: {result}"
            
    except Exception as e:
        return f"❌ Error clearing pending updates: {e}"

@app.route('/debug', methods=['GET'])
def debug():
    """Debug endpoint to check bot status"""
    try:
        # Test bot with a simple API call
        me_result = make_telegram_request('getMe')
        
        debug_info = {
            "bot_token_set": bool(BOT_TOKEN and BOT_TOKEN != "YOUR_BOT_TOKEN_HERE"),
            "bot_stats": bot_stats,
            "active_users": len(user_data),
            "user_data_sample": dict(list(user_data.items())[:3]) if user_data else {},
        }
        
        if me_result and me_result.get('ok'):
            bot_info = me_result.get('result', {})
            debug_info["bot_username"] = bot_info.get('username')
            debug_info["bot_name"] = bot_info.get('first_name')
            debug_info["bot_test"] = "✅ Bot API working"
        else:
            debug_info["bot_test"] = f"❌ Bot API error: {me_result}"
            
        return jsonify(debug_info)
    except Exception as e:
        return jsonify({"debug_error": str(e)})

@app.route('/delete_webhook', methods=['GET'])
def delete_webhook():
    """Delete webhook (useful for debugging)"""
  
    try:
        result = make_telegram_request('deleteWebhook')
        
        if result and result.get('ok'):
            return f"✅ Webhook deleted: {result.get('description')}"
        else:
            return f"❌ Error deleting webhook: {result}"
    except Exception as e:
        return f"❌ Error: {e}"

if __name__ == '__main__':
    print("🚀 Quiz Bot Flask App Starting...")
    print(f"Bot token configured: {'✅' if BOT_TOKEN and BOT_TOKEN != 'YOUR_BOT_TOKEN_HERE' else '❌'}")
    app.run(debug=False)
