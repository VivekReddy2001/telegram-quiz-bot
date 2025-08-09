import os
import json
import logging
import asyncio
from datetime import datetime, timedelta
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.error import NetworkError, TimedOut, RetryAfter, BadRequest

# --- Robust logging with network error suppression ---
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.WARNING,
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Suppress common network error logs to reduce noise
logging.getLogger('httpx').setLevel(logging.ERROR)
logging.getLogger('httpcore').setLevel(logging.ERROR)
logging.getLogger('telegram').setLevel(logging.ERROR)

# Check python-telegram-bot version compatibility
try:
    from telegram import __version__ as ptb_version

    logger.info(f"Using python-telegram-bot version: {ptb_version}")
except ImportError:
    logger.warning("Could not determine python-telegram-bot version")


class SimpleTelegramQuizBot:
    def __init__(self, telegram_token: str):
        self.telegram_token = telegram_token
        # Store user preferences for anonymous/non-anonymous (with aggressive cleanup)
        self.user_preferences = {}
        # Store user states for workflow (with aggressive cleanup)
        self.user_states = {}
        # Track last activity for cleanup
        self.last_activity = {}
        # More aggressive cleanup counter
        self.cleanup_counter = 0
        # Connection retry settings
        self.max_retries = 3
        self.retry_delay = 2.0

    def cleanup_old_data(self):
        """Clean up old user data aggressively to prevent memory leaks and delays."""
        self.cleanup_counter += 1

        # Run cleanup every 15 operations (even more aggressive)
        if self.cleanup_counter % 15 != 0:
            return

        current_time = datetime.now()
        # Keep data for only 1 hour for maximum performance
        cutoff_time = current_time - timedelta(hours=1)

        # Get users to remove
        users_to_remove = [
            user_id for user_id, last_seen in self.last_activity.items()
            if last_seen < cutoff_time
        ]

        # Clean up old data more aggressively
        for user_id in users_to_remove:
            self.user_preferences.pop(user_id, None)
            self.user_states.pop(user_id, None)
            self.last_activity.pop(user_id, None)

        # Also clean up any orphaned data
        all_user_ids = set(self.last_activity.keys())
        for user_id in list(self.user_preferences.keys()):
            if user_id not in all_user_ids:
                self.user_preferences.pop(user_id, None)

        for user_id in list(self.user_states.keys()):
            if user_id not in all_user_ids:
                self.user_states.pop(user_id, None)

    def update_user_activity(self, user_id):
        """Update last activity timestamp for user with immediate cleanup"""
        self.last_activity[user_id] = datetime.now()
        self.cleanup_old_data()

    async def safe_send_message(self, chat_id, text, **kwargs):
        """Send message with retry logic and error handling"""
        for attempt in range(self.max_retries):
            try:
                # Get the bot instance from the application
                bot = self.application.bot
                return await bot.send_message(chat_id=chat_id, text=text, **kwargs)
            except (NetworkError, TimedOut) as e:
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                    continue
                else:
                    # Silently fail on final attempt to avoid log spam
                    return None
            except RetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
                continue
            except BadRequest:
                # Don't retry bad requests
                return None
            except Exception:
                # Catch any other exception silently
                return None
        return None

    async def safe_edit_message(self, message, text, **kwargs):
        """Edit message with retry logic and error handling"""
        for attempt in range(self.max_retries):
            try:
                return await message.edit_text(text, **kwargs)
            except (NetworkError, TimedOut) as e:
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                    continue
                else:
                    return None
            except RetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
                continue
            except BadRequest:
                # Don't retry bad requests
                return None
            except Exception:
                # Catch any other exception silently
                return None
        return None

    async def safe_send_poll(self, **poll_params):
        """Send poll with retry logic and error handling"""
        for attempt in range(self.max_retries):
            try:
                bot = self.application.bot
                return await bot.send_poll(**poll_params)
            except (NetworkError, TimedOut) as e:
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                    continue
                else:
                    return None
            except RetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
                continue
            except BadRequest:
                # Don't retry bad requests
                return None
            except Exception:
                # Catch any other exception silently
                return None
        return None

    async def send_quiz_questions(self, questions: list, chat_id: str, is_anonymous: bool = True):
        """Send quiz questions to the specific chat that requested them - optimized with error handling"""
        success_count = 0

        for i, question_data in enumerate(questions, 1):
            try:
                # Support ultra-short format and old formats
                question_text = (question_data.get("q") or
                                 question_data.get("question", ""))
                options = (question_data.get("o") or
                           question_data.get("options", []))

                # Handle correct field properly - 0 is a valid value
                correct_id = question_data.get("c")
                if correct_id is None:
                    correct_id = question_data.get("correct")
                    if correct_id is None:
                        correct_id = question_data.get("correct_option_id", 0)

                explanation = (question_data.get("e") or
                               question_data.get("explanation", ""))

                # Prepare poll parameters
                poll_params = {
                    "chat_id": chat_id,
                    "question": question_text,
                    "options": options,
                    "type": "quiz",
                    "correct_option_id": correct_id,
                    "is_anonymous": is_anonymous
                }

                # Add explanation if provided
                if explanation:
                    poll_params["explanation"] = explanation

                result = await self.safe_send_poll(**poll_params)
                if result:
                    success_count += 1

                # Small delay to prevent rate limiting
                await asyncio.sleep(0.05)

            except Exception:
                # swallow errors per-question to keep flow moving
                pass

        return success_count

    async def get_welcome_messages(self):
        """Get the welcome messages as separate parts with template"""
        message1 = """🎯 **Simple Quiz Bot** ⚡

✨ Create MCQ quizzes instantly!

💡 **Rules:**
• `q` = question, `o` = options, `c` = correct, `e` = explanation  
• `c` starts from 0 (0=A, 1=B, 2=C, 3=D)
• 2-4 options allowed per question
• Keep short to fit Telegram limits

🚀 **Fast • Reliable • Professional** 🎓"""

        # Updated template with 4 options as requested
        message2 = """{"all_q":[{"q":"Capital of France? 🇫🇷","o":["London","Paris","Berlin","Madrid"],"c":1,"e":"Paris is the capital and largest city of France 🗼"},{"q":"What is 2+2? 🔢","o":["3","4","5","6"],"c":1,"e":"Basic addition: 2+2=4 ✅"}]}"""

        return message1, message2

    async def get_quiz_type_selection_message(self):
        """Get the quiz type selection message with better emojis"""
        return """🎭 **Choose Your Quiz Style:**

🔒 **Anonymous Quiz:**
✅ Can forward to channels and groups
✅ Voters remain private
✅ Perfect for public sharing

👤 **Non-Anonymous Quiz:**  
✅ Shows who answered each question
✅ Great for tracking participation
❌ Cannot be forwarded to channels

**Which style do you prefer?** 👇✨"""

    async def get_json_request_message(self, is_anonymous: bool):
        """Get the message asking for JSON input with professional emojis"""
        quiz_type = "🔒 Anonymous" if is_anonymous else "👤 Non-Anonymous"

        return f"""✅ **{quiz_type} Quiz Selected!** 🎉

📝 **Next Steps:**
1️⃣ Copy the above JSON template
2️⃣ Give it to ChatGPT/AI 🤖
3️⃣ Ask to customize with your questions in our format

🚀 **Then send me your customized JSON:** 👇⚡"""

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command with robust error handling"""
        user_id = update.effective_user.id
        user_name = update.effective_user.first_name or "Friend"

        # Update activity tracking
        self.update_user_activity(user_id)

        # Set user state to choosing quiz type
        self.user_states[user_id] = "choosing_type"

        # Send welcome message with better emojis
        msg1, _ = await self.get_welcome_messages()

        result = await self.safe_send_message(
            update.effective_chat.id,
            f"👋 Hello **{user_name}**! 🌟\n\n{msg1}",
            parse_mode='Markdown'
        )

        if result:
            # Show quiz type selection immediately without delay
            await self.show_quiz_type_selection(update)

    async def show_quiz_type_selection(self, update):
        """Show quiz type selection with inline keyboard - with error handling"""
        # Create inline keyboard for quiz type selection
        keyboard = [
            [InlineKeyboardButton("🔒 Anonymous Quiz (Can forward to channels)", callback_data="anonymous_true")],
            [InlineKeyboardButton("👤 Non-Anonymous Quiz (Shows who voted)", callback_data="anonymous_false")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        selection_msg = await self.get_quiz_type_selection_message()

        if hasattr(update, 'message') and update.message:
            await self.safe_send_message(
                update.effective_chat.id,
                selection_msg,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        else:
            # This is from callback query
            await self.safe_send_message(
                update.effective_chat.id,
                selection_msg,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )

    async def handle_quiz_type_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle quiz type selection from inline keyboard - with error handling"""
        query = update.callback_query

        try:
            await query.answer()
        except Exception:
            pass  # Silently ignore answer failures

        user_id = query.from_user.id
        is_anonymous = query.data == "anonymous_true"

        # Update activity tracking
        self.update_user_activity(user_id)

        # Store user preference
        self.user_preferences[user_id] = is_anonymous
        self.user_states[user_id] = "waiting_for_json"

        quiz_type = "🔒 Anonymous" if is_anonymous else "👤 Non-Anonymous"

        result = await self.safe_edit_message(
            query.message,
            f"✅ **{quiz_type} Quiz Selected!** 🎉\n\n"
            f"⏭️ **Next:** JSON template coming... ⚡",
            parse_mode='Markdown'
        )

        if result:
            # Small delay for better UX
            await asyncio.sleep(0.1)

            # Send the JSON template again for easy access
            _, msg2 = await self.get_welcome_messages()
            await self.safe_send_message(query.message.chat_id, f"{msg2}")

            await asyncio.sleep(0.1)

            # Ask for JSON input
            json_request = await self.get_json_request_message(is_anonymous)
            await self.safe_send_message(query.message.chat_id, json_request, parse_mode='Markdown')

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command with professional emojis"""
        user_id = update.effective_user.id
        self.update_user_activity(user_id)

        help_text = """🆘 **Quiz Bot Help** 📚

🤖 **Commands:**
• `/start` ⭐ - Begin quiz creation
• `/quickstart` ⚡ - Quick 5-step guide
• `/template` 📋 - Get JSON template
• `/help` 🆘 - Show this help
• `/status` 📊 - Check settings
• `/toggle` 🔄 - Switch quiz types

📚 **JSON Format:**
• `all_q` 📝 - Questions array
• `q` ❓ - Question text
• `o` 📝 - Answer options (2-4 choices)
• `c` ✅ - Correct answer (0=A, 1=B, 2=C, 3=D)
• `e` 💡 - Explanation (optional)

💡 **Pro Tip:** Use `/quickstart` for fastest setup! 🚀"""

        await self.safe_send_message(update.effective_chat.id, help_text, parse_mode='Markdown')

    async def template_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /template command - show JSON template with 4 options"""
        user_id = update.effective_user.id
        self.update_user_activity(user_id)

        template_msg = """📋 **4-Option JSON Template:** 🎯"""

        result1 = await self.safe_send_message(update.effective_chat.id, template_msg, parse_mode='Markdown')

        if result1:
            # Send JSON template in plain text (now with 4 options)
            _, json_template = await self.get_welcome_messages()
            result2 = await self.safe_send_message(update.effective_chat.id, json_template)

            if result2:
                await self.safe_send_message(
                    update.effective_chat.id,
                    "💡 **Copy above template → Give to ChatGPT → Ask to customize with your questions!** 🤖✨",
                    parse_mode='Markdown'
                )

    async def quick_start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /quickstart command with better emojis"""
        user_id = update.effective_user.id
        self.update_user_activity(user_id)

        quick_msg = """⚡ **Quick Start Guide:** 🚀

1️⃣ Use `/template` to get 4-option JSON format 📋
2️⃣ Copy template → Give to AI (ChatGPT) 🤖  
3️⃣ Ask AI: "Customize with my questions in this format" 💭
4️⃣ Send customized JSON to me 📤
5️⃣ Get instant interactive quizzes! 🎯✨

**Need help?** Use `/help` for detailed guide 📚"""

        await self.safe_send_message(update.effective_chat.id, quick_msg, parse_mode='Markdown')

    async def toggle_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /toggle command to switch quiz types with emojis"""
        user_id = update.effective_user.id
        self.update_user_activity(user_id)

        keyboard = [
            [InlineKeyboardButton("🔒 Switch to Anonymous", callback_data="anonymous_true")],
            [InlineKeyboardButton("👤 Switch to Non-Anonymous", callback_data="anonymous_false")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        current_type = "🔒 Anonymous" if self.user_preferences.get(user_id, True) else "👤 Non-Anonymous"

        await self.safe_send_message(
            update.effective_chat.id,
            f"⚙️ **Current Setting:** {current_type} 📊\n\n"
            f"🔄 **Quick Toggle:** Choose your preferred quiz type: 👇✨",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command with professional emojis"""
        user_chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        user_name = update.effective_user.first_name or "User"
        self.update_user_activity(user_id)

        is_anonymous = self.user_preferences.get(user_id, True)
        quiz_type = "🔒 Anonymous" if is_anonymous else "👤 Non-Anonymous"

        status_emoji = "🟢" if is_anonymous else "🔵"

        # Show memory usage stats for monitoring
        active_users = len(self.user_preferences)
        active_states = len(self.user_states)

        await self.safe_send_message(
            user_chat_id,
            f"{status_emoji} **Bot Status: Active & Ready!** ⚡\n\n"
            f"👤 **User:** {user_name} 🌟\n"
            f"📍 **Chat ID:** `{user_chat_id}` 🔢\n"
            f"🎯 **Quiz Type:** {quiz_type} 🎭\n"
            f"{'🔐 Perfect for channels & forwarding 📡' if is_anonymous else '👁️ Shows voter participation 📊'}\n"
            f"📊 **Active Users:** {active_users} 👥\n\n"
            f"🚀 **Ready to create amazing quizzes!** ✨",
            parse_mode='Markdown'
        )

    async def restart_cycle(self, update: Update):
        """Restart the welcome cycle after quiz completion - with error handling"""
        user_id = update.effective_user.id
        user_name = update.effective_user.first_name or "Friend"

        self.update_user_activity(user_id)

        # Reset user state
        self.user_states[user_id] = "choosing_type"

        # Reduce delay for better performance
        await asyncio.sleep(0.1)

        # Send brief restart message with better emojis
        restart_msg = f"""🎉 **Ready for another quiz?** ✨"""

        result1 = await self.safe_send_message(update.effective_chat.id, restart_msg, parse_mode='Markdown')

        if result1:
            await asyncio.sleep(0.1)

            # Send welcome message again (NO JSON template here)
            msg1, _ = await self.get_welcome_messages()
            result2 = await self.safe_send_message(update.effective_chat.id, msg1, parse_mode='Markdown')

            if result2:
                await asyncio.sleep(0.1)
                # Show quiz type selection
                await self.show_quiz_type_selection(update)

    async def handle_json_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming JSON messages - with robust error handling"""
        user_message = update.message.text.strip()
        user_chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        user_name = update.effective_user.first_name or "User"

        self.update_user_activity(user_id)

        # Check if user has selected quiz type
        if self.user_states.get(user_id) != "waiting_for_json":
            # User hasn't selected quiz type yet, restart the flow
            result = await self.safe_send_message(user_chat_id, "🔄 **Let's start properly!** ✨", parse_mode='Markdown')
            if result:
                await self.start_command(update, None)
            return

        # Get user's quiz type preference (default to anonymous)
        is_anonymous = self.user_preferences.get(user_id, True)

        # Send processing message with better emojis
        processing_msg = await self.safe_send_message(user_chat_id, "🔄 **Processing your quiz JSON...** ⚡🎯")

        if not processing_msg:
            return  # Failed to send message, abort

        try:
            # Try to parse JSON
            quiz_data = json.loads(user_message)

            # Extract questions - support all formats
            questions = quiz_data.get("all_q", quiz_data.get("q", quiz_data.get("all_questions", [])))

            if not questions:
                await self.safe_edit_message(
                    processing_msg,
                    "❌ **No questions found!** 🔍\n\n"
                    "🔄 **Let's restart with proper format...** 📋",
                    parse_mode='Markdown'
                )
                await asyncio.sleep(0.5)
                await self.restart_cycle(update)
                return

            # Validate question format
            for i, question in enumerate(questions):
                # Support ultra-short format and old formats
                question_text = question.get("q") or question.get("question", "")
                options = question.get("o") or question.get("options", [])

                # Handle correct field - check for None explicitly since 0 is valid
                correct_id = question.get("c")
                if correct_id is None:
                    correct_id = question.get("correct")
                    if correct_id is None:
                        correct_id = question.get("correct_option_id", -1)

                if not question_text:
                    await self.safe_edit_message(
                        processing_msg,
                        f"❌ **Question {i + 1}: Missing question text** 📝\n\n🔄 **Restarting...** 🔄",
                        parse_mode='Markdown'
                    )
                    await asyncio.sleep(0.3)
                    await self.restart_cycle(update)
                    return

                if not options:
                    await self.safe_edit_message(
                        processing_msg,
                        f"❌ **Question {i + 1}: Missing options** 📝\n\n🔄 **Restarting...** 🔄",
                        parse_mode='Markdown'
                    )
                    await asyncio.sleep(0.3)
                    await self.restart_cycle(update)
                    return

                if correct_id is None or correct_id == -1:
                    await self.safe_edit_message(
                        processing_msg,
                        f"❌ **Question {i + 1}: Missing correct answer** ✅\n\n🔄 **Restarting...** 🔄",
                        parse_mode='Markdown'
                    )
                    await asyncio.sleep(0.3)
                    await self.restart_cycle(update)
                    return

                if not isinstance(options, list) or len(options) < 2 or len(options) > 4:
                    await self.safe_edit_message(
                        processing_msg,
                        f"❌ **Question {i + 1}: Invalid options** 📝\n\n🔄 **Restarting...** 🔄",
                        parse_mode='Markdown'
                    )
                    await asyncio.sleep(0.3)
                    await self.restart_cycle(update)
                    return

                if not isinstance(correct_id, int) or correct_id >= len(options) or correct_id < 0:
                    await self.safe_edit_message(
                        processing_msg,
                        f"❌ **Question {i + 1}: Invalid 'c' value** 🔢\n\n🔄 **Restarting...** 🔄",
                        parse_mode='Markdown'
                    )
                    await asyncio.sleep(0.3)
                    await self.restart_cycle(update)
                    return

            quiz_type = "anonymous" if is_anonymous else "non-anonymous"
            await self.safe_edit_message(
                processing_msg,
                f"✅ **{len(questions)} questions validated!** 🎯\n🚀 Sending {quiz_type} polls... ⚡",
                parse_mode='Markdown'
            )

            # Send quiz questions to the user who sent the JSON
            success_count = await self.send_quiz_questions(questions, user_chat_id, is_anonymous)

            if success_count == len(questions):
                quiz_type_text = "🔒 Anonymous" if is_anonymous else "👤 Non-Anonymous"
                completion_msg = f"🎯 **{success_count} {quiz_type_text} quizzes sent successfully!** ✅🎉"

                await self.safe_edit_message(processing_msg, completion_msg, parse_mode='Markdown')

                # >>> THE ONLY LOG LINE (username only) <<<
                logger.warning(f"Served MCQs to {user_name}")

                # Restart the cycle
                await self.restart_cycle(update)
            else:
                await self.safe_edit_message(
                    processing_msg,
                    f"⚠️ **Partial Success:** {success_count}/{len(questions)} questions sent 📊\n\n🔄 **Restarting...** 🔄",
                    parse_mode='Markdown'
                )
                await asyncio.sleep(0.3)
                await self.restart_cycle(update)

        except json.JSONDecodeError:
            await self.safe_edit_message(
                processing_msg,
                "❌ **Invalid JSON Format!** 📋\n\n🔄 **Let's restart with proper format...** ✨",
                parse_mode='Markdown'
            )
            await asyncio.sleep(0.3)
            await self.restart_cycle(update)
        except Exception:
            # stay quiet to avoid log spam; show friendly message to user
            await self.safe_edit_message(
                processing_msg,
                "❌ **Error occurred!** ⚠️\n\n🔄 **Restarting...** 🔄",
                parse_mode='Markdown'
            )
            await asyncio.sleep(0.3)
            await self.restart_cycle(update)

    def run(self):
        """Start the bot with maximum robustness for deployment"""
        try:
            # Create application with robust settings
            self.application = (Application.builder()
                                .token(self.telegram_token)
                                .pool_timeout(60)  # Longer timeout for stability
                                .connection_pool_size(4)  # Smaller pool for shared hosting
                                .get_updates_pool_timeout(60)  # Longer get updates timeout
                                .read_timeout(30)  # Longer read timeout
                                .write_timeout(30)  # Longer write timeout
                                .connect_timeout(30)  # Longer connect timeout
                                .build())

            # Add error handler to suppress network errors
            def error_handler(update, context):
                # Silently ignore network errors to reduce log spam
                error = context.error
                if isinstance(error, (NetworkError, TimedOut)):
                    return  # Don't log these
                # Log other errors at WARNING level only
                logger.warning(f"Bot error: {type(error).__name__}")

            self.application.add_error_handler(error_handler)

            # Add handlers
            self.application.add_handler(CommandHandler("start", self.start_command))
            self.application.add_handler(CommandHandler("help", self.help_command))
            self.application.add_handler(CommandHandler("template", self.template_command))
            self.application.add_handler(CommandHandler("quickstart", self.quick_start_command))
            self.application.add_handler(CommandHandler("status", self.status_command))
            self.application.add_handler(CommandHandler("toggle", self.toggle_command))
            self.application.add_handler(CallbackQueryHandler(self.handle_quiz_type_selection))
            self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_json_message))

            # Robust polling settings for deployment
            self.application.run_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True,
                poll_interval=2.0,  # Longer interval for stability
                timeout=30,  # Longer timeout
                bootstrap_retries=-1,  # Unlimited retries
                close_loop=False  # Don't close the loop on errors
            )

        except Exception as e:
            # Minimal logging for critical errors only
            logger.warning(f"Critical bot error: {type(e).__name__}")
            raise


def main():
    """Main function to run the bot"""
    # ✅ SECURE: Get bot token from environment variable
    TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

    if not TELEGRAM_TOKEN:
        logger.error("❌ TELEGRAM_BOT_TOKEN environment variable not found!")
        logger.error("Set it with: export TELEGRAM_BOT_TOKEN='your_bot_token_here'")
        return

    logger.info("🚀 Starting Telegram Quiz Bot...")

    # Create and run bot
    bot = SimpleTelegramQuizBot(TELEGRAM_TOKEN)
    bot.run()


if __name__ == "__main__":
    main()
