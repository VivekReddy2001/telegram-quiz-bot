#!/usr/bin/env python3
"""
Bulletproof Telegram Quiz Bot - PythonAnywhere Optimized
Designed to run 24/7 without termination issues
"""

import json
import logging
import asyncio
import time
import sys
import os
import gc
import signal
import threading
from datetime import datetime, timedelta
from collections import deque
from typing import Optional, Dict, Any, List
import weakref
import traceback

# Telegram imports with error handling
try:
    from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
    from telegram.error import NetworkError, TimedOut, RetryAfter, BadRequest, TelegramError, Forbidden
except ImportError as e:
    print(f"❌ Missing telegram dependency: {e}")
    print("Install with: pip install python-telegram-bot")
    sys.exit(1)

# ============================================================================
# BULLETPROOF LOGGING - NEVER CRASHES ON ENCODING/FORMATTING ERRORS
# ============================================================================

class CrashProofFormatter(logging.Formatter):
    """Formatter that never crashes even with encoding/unicode issues"""
    def format(self, record):
        try:
            return super().format(record)
        except (UnicodeError, UnicodeDecodeError, UnicodeEncodeError):
            try:
                return f"{record.levelname}: {repr(record.getMessage())}"
            except:
                return f"{record.levelname}: <MESSAGE_FORMATTING_ERROR>"
        except Exception:
            return f"{record.levelname}: <FORMATTER_ERROR>"

# Ultra-safe logging configuration
def setup_bulletproof_logging():
    """Setup logging that never crashes the process"""
    
    # Remove all existing handlers to prevent conflicts
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Create bulletproof handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(CrashProofFormatter('%(asctime)s - %(levelname)s - %(message)s'))
    handler.setLevel(logging.WARNING)
    
    # Configure root logger
    root_logger.setLevel(logging.WARNING)
    root_logger.addHandler(handler)
    
    # Aggressively suppress ALL noisy libraries
    NOISY_LOGGERS = [
        'httpx', 'httpcore', 'telegram', 'urllib3', 'asyncio',
        'concurrent.futures', 'websockets', 'aiohttp', 'requests',
        'httpx._client', 'httpcore.http11', 'httpcore.connection'
    ]
    
    for logger_name in NOISY_LOGGERS:
        try:
            noisy_logger = logging.getLogger(logger_name)
            noisy_logger.setLevel(logging.CRITICAL)
            noisy_logger.disabled = True
            noisy_logger.propagate = False
        except:
            pass

setup_bulletproof_logging()
logger = logging.getLogger(__name__)

# ============================================================================
# MEMORY AND RESOURCE MANAGEMENT
# ============================================================================

class MemoryManager:
    """Ultra-aggressive memory management to prevent accumulation"""
    
    def __init__(self):
        self.last_cleanup = time.time()
        self.cleanup_interval = 60  # Cleanup every minute
        self.max_memory_items = 100  # Maximum items to keep in memory
    
    def should_cleanup(self) -> bool:
        """Check if cleanup is needed"""
        return time.time() - self.last_cleanup > self.cleanup_interval
    
    def force_cleanup(self):
        """Force garbage collection and memory cleanup"""
        try:
            # Force garbage collection
            collected = gc.collect()
            
            # Force cleanup of all generations
            for i in range(3):
                gc.collect(i)
            
            self.last_cleanup = time.time()
            
        except Exception:
            pass  # Never let cleanup crash the bot

# ============================================================================
# PROCESS HEALTH MONITORING
# ============================================================================

class HealthMonitor:
    """Monitor process health and detect issues before they cause crashes"""
    
    def __init__(self):
        self.start_time = time.time()
        self.last_heartbeat = time.time()
        self.api_success_count = 0
        self.api_failure_count = 0
        self.consecutive_failures = 0
        self.max_consecutive_failures = 10
        self.is_healthy = True
        self.restart_requested = False
        
    def record_success(self):
        """Record a successful API call"""
        self.api_success_count += 1
        self.consecutive_failures = 0
        self.last_heartbeat = time.time()
        self.is_healthy = True
    
    def record_failure(self):
        """Record a failed API call"""
        self.api_failure_count += 1
        self.consecutive_failures += 1
        
        if self.consecutive_failures >= self.max_consecutive_failures:
            self.is_healthy = False
    
    def get_health_status(self) -> Dict[str, Any]:
        """Get current health status"""
        uptime = time.time() - self.start_time
        total_requests = self.api_success_count + self.api_failure_count
        success_rate = (self.api_success_count / max(total_requests, 1)) * 100
        
        return {
            'is_healthy': self.is_healthy,
            'uptime_seconds': uptime,
            'success_rate': success_rate,
            'consecutive_failures': self.consecutive_failures,
            'total_requests': total_requests
        }

# ============================================================================
# BULLETPROOF TELEGRAM BOT
# ============================================================================

class BulletproofTelegramQuizBot:
    """
    A Telegram bot designed to never crash or terminate unexpectedly.
    Optimized specifically for PythonAnywhere's shared hosting environment.
    """
    
    def __init__(self, telegram_token: str):
        if not telegram_token or telegram_token == "YOUR_BOT_TOKEN_HERE":
            raise ValueError("❌ Valid Telegram bot token required!")
        
        self.telegram_token = telegram_token
        self.application: Optional[Application] = None
        
        # Initialize components
        self.memory_manager = MemoryManager()
        self.health_monitor = HealthMonitor()
        
        # User data storage with automatic cleanup
        self.user_preferences: Dict[int, bool] = {}  # user_id -> is_anonymous
        self.user_states: Dict[int, str] = {}        # user_id -> current_state
        self.user_activity: Dict[int, float] = {}    # user_id -> last_activity_timestamp
        
        # Bulletproof configuration
        self.max_retries = 3
        self.base_retry_delay = 1.0
        self.max_retry_delay = 30.0
        self.request_timeout = 60
        self.max_stored_users = 200  # Prevent memory bloat
        self.user_data_ttl = 1800   # 30 minutes TTL for user data
        
        # Process control
        self.should_stop = False
        self.cleanup_thread: Optional[threading.Thread] = None
        self.is_running = False
        
        # Setup signal handlers for graceful shutdown
        self._setup_signal_handlers()
    
    def _setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown"""
        def signal_handler(signum, frame):
            logger.warning(f"Received signal {signum}, initiating graceful shutdown...")
            self.should_stop = True
            
            if self.application:
                try:
                    # Stop the application gracefully
                    asyncio.create_task(self.application.stop())
                    asyncio.create_task(self.application.shutdown())
                except:
                    pass
            
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    def start_background_tasks(self):
        """Start background maintenance tasks"""
        def maintenance_worker():
            """Background thread for maintenance tasks"""
            while not self.should_stop:
                try:
                    # Memory management
                    if self.memory_manager.should_cleanup():
                        self.aggressive_cleanup()
                        self.memory_manager.force_cleanup()
                    
                    # Health check
                    if not self.health_monitor.is_healthy:
                        logger.warning("Health check failed - considering restart")
                    
                    # Sleep for 30 seconds
                    for _ in range(30):
                        if self.should_stop:
                            break
                        time.sleep(1)
                        
                except Exception:
                    # Never let maintenance crash
                    pass
        
        self.cleanup_thread = threading.Thread(target=maintenance_worker, daemon=True)
        self.cleanup_thread.start()
    
    def update_user_activity(self, user_id: int):
        """Update user activity with automatic cleanup"""
        try:
            current_time = time.time()
            self.user_activity[user_id] = current_time
            
            # Trigger cleanup if we have too many users
            if len(self.user_activity) > self.max_stored_users:
                self.aggressive_cleanup()
                
        except Exception:
            pass
    
    def aggressive_cleanup(self):
        """Ultra-aggressive cleanup to prevent memory issues"""
        try:
            current_time = time.time()
            cutoff_time = current_time - self.user_data_ttl
            
            # Find inactive users
            inactive_users = [
                user_id for user_id, last_activity in self.user_activity.items()
                if last_activity < cutoff_time
            ]
            
            # Remove inactive users
            for user_id in inactive_users:
                self.user_preferences.pop(user_id, None)
                self.user_states.pop(user_id, None)
                self.user_activity.pop(user_id, None)
            
            # If still too many users, keep only the most recent ones
            if len(self.user_activity) > self.max_stored_users:
                # Sort by activity and keep only the most recent
                sorted_users = sorted(
                    self.user_activity.items(),
                    key=lambda x: x[1],
                    reverse=True
                )[:self.max_stored_users // 2]  # Keep half to prevent frequent cleanups
                
                keep_users = {user_id for user_id, _ in sorted_users}
                
                # Remove old users
                self.user_preferences = {
                    uid: pref for uid, pref in self.user_preferences.items()
                    if uid in keep_users
                }
                self.user_states = {
                    uid: state for uid, state in self.user_states.items()
                    if uid in keep_users
                }
                self.user_activity = {
                    uid: activity for uid, activity in self.user_activity.items()
                    if uid in keep_users
                }
            
            logger.warning(f"Cleanup completed. Active users: {len(self.user_activity)}")
            
        except Exception:
            # If cleanup fails completely, clear everything to prevent crashes
            try:
                self.user_preferences.clear()
                self.user_states.clear()
                self.user_activity.clear()
                logger.warning("Emergency cleanup - cleared all user data")
            except:
                pass
    
    def calculate_retry_delay(self, attempt: int) -> float:
        """Calculate retry delay with exponential backoff and jitter"""
        base_delay = min(self.base_retry_delay * (2 ** attempt), self.max_retry_delay)
        
        # Add jitter to prevent thundering herd
        jitter = base_delay * 0.1 * (hash(str(time.time())) % 100 / 100)
        
        return base_delay + jitter
    
    async def bulletproof_api_call(self, api_call, *args, **kwargs):
        """
        Make API calls with comprehensive error handling and retry logic.
        This method ensures no unhandled exceptions crash the bot.
        """
        last_exception = None
        
        for attempt in range(self.max_retries):
            try:
                # Set a timeout for the API call
                result = await asyncio.wait_for(
                    api_call(*args, **kwargs),
                    timeout=self.request_timeout
                )
                
                # Record success
                self.health_monitor.record_success()
                return result
                
            except RetryAfter as e:
                # Respect Telegram's rate limiting
                wait_time = min(e.retry_after + 1, 60)  # Max 60 seconds wait
                logger.warning(f"Rate limited, waiting {wait_time}s")
                await asyncio.sleep(wait_time)
                continue
                
            except (NetworkError, TimedOut, ConnectionError, OSError) as e:
                last_exception = e
                self.health_monitor.record_failure()
                
                if attempt < self.max_retries - 1:
                    delay = self.calculate_retry_delay(attempt)
                    logger.warning(f"Network error (attempt {attempt + 1}/{self.max_retries}), retrying in {delay:.1f}s")
                    await asyncio.sleep(delay)
                    continue
                    
            except (BadRequest, Forbidden) as e:
                # Don't retry client errors
                last_exception = e
                logger.warning(f"Client error: {e}")
                self.health_monitor.record_failure()
                break
                
            except TelegramError as e:
                last_exception = e
                self.health_monitor.record_failure()
                
                # Retry timeout-related Telegram errors
                if "timeout" in str(e).lower() or "timed out" in str(e).lower():
                    if attempt < self.max_retries - 1:
                        delay = self.calculate_retry_delay(attempt)
                        await asyncio.sleep(delay)
                        continue
                else:
                    logger.warning(f"Telegram error: {e}")
                    break
                    
            except asyncio.TimeoutError:
                last_exception = TimeoutError("API call timeout")
                self.health_monitor.record_failure()
                
                if attempt < self.max_retries - 1:
                    delay = self.calculate_retry_delay(attempt)
                    await asyncio.sleep(delay)
                    continue
                    
            except Exception as e:
                # Catch any other unexpected errors
                last_exception = e
                self.health_monitor.record_failure()
                logger.warning(f"Unexpected error in API call: {type(e).__name__}: {e}")
                
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(1)
                    continue
                break
        
        # All attempts failed
        logger.warning(f"API call failed after {self.max_retries} attempts. Last error: {last_exception}")
        return None
    
    async def safe_send_message(self, chat_id, text, **kwargs):
        """Send message with bulletproof error handling"""
        if not self.application or not self.application.bot:
            logger.warning("No application/bot available for sending message")
            return None
        
        # Sanitize and truncate text to prevent API errors
        try:
            text = str(text)[:4000]  # Telegram's message limit
            if not text.strip():
                text = "Empty message"
        except Exception:
            text = "Message formatting error"
        
        return await self.bulletproof_api_call(
            self.application.bot.send_message,
            chat_id=chat_id,
            text=text,
            **kwargs
        )
    
    async def safe_edit_message(self, message, text, **kwargs):
        """Edit message with bulletproof error handling"""
        if not message:
            return None
        
        try:
            text = str(text)[:4000]
            if not text.strip():
                text = "Empty message"
        except Exception:
            text = "Message formatting error"
        
        return await self.bulletproof_api_call(
            message.edit_text,
            text,
            **kwargs
        )
    
    async def safe_send_poll(self, **poll_params):
        """Send poll with bulletproof error handling"""
        if not self.application or not self.application.bot:
            return None
        
        # Sanitize poll parameters
        try:
            # Ensure question is valid
            question = str(poll_params.get('question', 'Question'))[:255]
            poll_params['question'] = question
            
            # Ensure options are valid
            options = poll_params.get('options', ['Option A', 'Option B'])
            if not isinstance(options, list) or len(options) < 2:
                options = ['Option A', 'Option B']
            
            # Sanitize options
            options = [str(opt)[:100] for opt in options[:10]]  # Max 10 options
            poll_params['options'] = options
            
            # Ensure correct_option_id is valid
            correct_id = poll_params.get('correct_option_id', 0)
            if not isinstance(correct_id, int) or correct_id < 0 or correct_id >= len(options):
                correct_id = 0
            poll_params['correct_option_id'] = correct_id
            
            # Sanitize explanation
            explanation = poll_params.get('explanation', '')
            if explanation:
                poll_params['explanation'] = str(explanation)[:200]
            
        except Exception:
            # Use default values if sanitization fails
            poll_params = {
                'chat_id': poll_params.get('chat_id'),
                'question': 'Question',
                'options': ['Option A', 'Option B'],
                'type': 'quiz',
                'correct_option_id': 0,
                'is_anonymous': True
            }
        
        return await self.bulletproof_api_call(
            self.application.bot.send_poll,
            **poll_params
        )
    
    async def send_quiz_questions(self, questions: List[Dict], chat_id: str, is_anonymous: bool = True) -> int:
        """Send quiz questions with bulletproof error handling"""
        if not questions:
            return 0
        
        success_count = 0
        
        for i, question_data in enumerate(questions[:50]):  # Limit to 50 questions max
            try:
                # Extract and sanitize question data
                question_text = question_data.get("q") or question_data.get("question", f"Question {i+1}")
                options = question_data.get("o") or question_data.get("options", ["Option A", "Option B"])
                correct_id = question_data.get("c")
                if correct_id is None:
                    correct_id = question_data.get("correct", 0)
                explanation = question_data.get("e") or question_data.get("explanation", "")
                
                # Validate data
                if not question_text or not options or len(options) < 2:
                    logger.warning(f"Skipping invalid question {i+1}")
                    continue
                
                # Ensure correct_id is valid
                if not isinstance(correct_id, int) or correct_id < 0 or correct_id >= len(options):
                    correct_id = 0
                
                # Prepare poll parameters
                poll_params = {
                    "chat_id": chat_id,
                    "question": str(question_text)[:255],
                    "options": [str(opt)[:100] for opt in options[:4]],  # Max 4 options
                    "type": "quiz",
                    "correct_option_id": int(correct_id),
                    "is_anonymous": bool(is_anonymous)
                }
                
                if explanation:
                    poll_params["explanation"] = str(explanation)[:200]
                
                # Send the poll
                result = await self.safe_send_poll(**poll_params)
                if result:
                    success_count += 1
                else:
                    logger.warning(f"Failed to send question {i+1}")
                
                # Adaptive delay based on success rate
                if success_count == i + 1:  # All successful so far
                    await asyncio.sleep(0.1)  # Short delay
                else:
                    await asyncio.sleep(0.5)  # Longer delay if issues
                
            except Exception as e:
                logger.warning(f"Error processing question {i+1}: {type(e).__name__}")
                continue
        
        return success_count
    
    # ========================================================================
    # MESSAGE TEMPLATES
    # ========================================================================
    
    async def get_welcome_messages(self):
        """Get welcome messages - cached for performance"""
        return (
            "🎯 **Simple Quiz Bot** ⚡\n\n"
            "✨ Create MCQ quizzes instantly!\n\n"
            "💡 **Rules:**\n"
            "• `q` = question, `o` = options, `c` = correct, `e` = explanation\n"
            "• `c` starts from 0 (0=A, 1=B, 2=C, 3=D)\n"
            "• 2-4 options allowed per question\n"
            "• Keep text short to fit Telegram limits\n\n"
            "🚀 **Fast • Reliable • Professional** 🎯",
            
            '{"all_q":[{"q":"Capital of France? 🇫🇷","o":["London","Paris","Berlin","Madrid"],"c":1,"e":"Paris is the capital and largest city of France 🗼"},{"q":"What is 2+2? 🔢","o":["3","4","5","6"],"c":1,"e":"Basic addition: 2+2=4 ✅"}]}'
        )
    
    async def get_quiz_type_selection_message(self):
        return (
            "🎭 **Choose Your Quiz Style:**\n\n"
            "🔒 **Anonymous Quiz:**\n"
            "✅ Can forward to channels and groups\n"
            "✅ Voters remain private\n"
            "✅ Perfect for public sharing\n\n"
            "👤 **Non-Anonymous Quiz:**\n"
            "✅ Shows who answered each question\n"
            "✅ Great for tracking participation\n"
            "❌ Cannot be forwarded to channels\n\n"
            "**Which style do you prefer?** 👇✨"
        )
    
    async def get_json_request_message(self, is_anonymous: bool):
        quiz_type = "🔒 Anonymous" if is_anonymous else "👤 Non-Anonymous"
        return (
            f"✅ **{quiz_type} Quiz Selected!** 🎉\n\n"
            "📝 **Next Steps:**\n"
            "1️⃣ Copy the above JSON template\n"
            "2️⃣ Give it to ChatGPT/AI 🤖\n"
            "3️⃣ Ask to customize with your questions in our format\n\n"
            "🚀 **Then send me your customized JSON:** 👇⚡"
        )
    
    # ========================================================================
    # COMMAND HANDLERS
    # ========================================================================
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command with bulletproof error handling"""
        try:
            if not update or not update.effective_user:
                return
            
            user_id = update.effective_user.id
            user_name = update.effective_user.first_name or "Friend"
            
            self.update_user_activity(user_id)
            self.user_states[user_id] = "choosing_type"
            
            msg1, _ = await self.get_welcome_messages()
            
            result = await self.safe_send_message(
                update.effective_chat.id,
                f"👋 Hello **{user_name}**! 🌟\n\n{msg1}",
                parse_mode='Markdown'
            )
            
            if result:
                await self.show_quiz_type_selection(update)
            else:
                # Fallback without markdown
                await self.safe_send_message(
                    update.effective_chat.id,
                    f"👋 Hello {user_name}! 🌟\n\nBot started successfully! Use /help for commands."
                )
                
        except Exception as e:
            logger.warning(f"Error in start_command: {type(e).__name__}")
            # Ultimate fallback
            try:
                await self.safe_send_message(
                    update.effective_chat.id,
                    "🤖 Bot started! Use /help for commands."
                )
            except:
                pass
    
    async def show_quiz_type_selection(self, update):
        """Show quiz type selection with error handling"""
        try:
            keyboard = [
                [InlineKeyboardButton("🔒 Anonymous Quiz (Can forward to channels)", callback_data="anonymous_true")],
                [InlineKeyboardButton("👤 Non-Anonymous Quiz (Shows who voted)", callback_data="anonymous_false")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            selection_msg = await self.get_quiz_type_selection_message()
            
            result = await self.safe_send_message(
                update.effective_chat.id,
                selection_msg,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
            if not result:
                # Fallback without markdown and keyboard
                await self.safe_send_message(
                    update.effective_chat.id,
                    "Choose quiz type: Use /toggle command to select Anonymous or Non-Anonymous quiz."
                )
                
        except Exception as e:
            logger.warning(f"Error in show_quiz_type_selection: {type(e).__name__}")
    
    async def handle_quiz_type_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle quiz type selection with bulletproof error handling"""
        try:
            if not update or not update.callback_query:
                return
                
            query = update.callback_query
            
            # Answer callback query to remove loading state
            try:
                await query.answer()
            except Exception:
                pass  # Don't let callback answer failure break the flow
            
            user_id = query.from_user.id
            is_anonymous = query.data == "anonymous_true"
            
            self.update_user_activity(user_id)
            self.user_preferences[user_id] = is_anonymous
            self.user_states[user_id] = "waiting_for_json"
            
            quiz_type = "🔒 Anonymous" if is_anonymous else "👤 Non-Anonymous"
            
            # Try to edit the message
            result = await self.safe_edit_message(
                query.message,
                f"✅ **{quiz_type} Quiz Selected!** 🎉\n\n⭐ **JSON template coming...** ⚡",
                parse_mode='Markdown'
            )
            
            if result:
                await asyncio.sleep(0.3)
                
                # Send JSON template
                _, template = await self.get_welcome_messages()
                await self.safe_send_message(query.message.chat_id, template)
                
                await asyncio.sleep(0.2)
                
                # Send instructions
                json_request = await self.get_json_request_message(is_anonymous)
                await self.safe_send_message(query.message.chat_id, json_request, parse_mode='Markdown')
            else:
                # Fallback if editing fails
                await self.safe_send_message(
                    query.message.chat_id,
                    f"Quiz type selected: {quiz_type}\nSend me your quiz JSON now!"
                )
                
        except Exception as e:
            logger.warning(f"Error in handle_quiz_type_selection: {type(e).__name__}")
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Enhanced status command with health monitoring"""
        try:
            if not update or not update.effective_user:
                return
                
            user_id = update.effective_user.id
            user_name = update.effective_user.first_name or "User"
            self.update_user_activity(user_id)
            
            # Get health status
            health = self.health_monitor.get_health_status()
            is_anonymous = self.user_preferences.get(user_id, True)
            quiz_type = "🔒 Anonymous" if is_anonymous else "👤 Non-Anonymous"
            
            # Format uptime
            uptime_hours = int(health['uptime_seconds'] // 3600)
            uptime_minutes = int((health['uptime_seconds'] % 3600) // 60)
            
            status_emoji = "🟢" if health['is_healthy'] else "🔴"
            
            status_msg = (
                f"📊 **Bot Health Status** {status_emoji}\n\n"
                f"👤 **User:** {user_name} 🌟\n"
                f"📝 **Chat ID:** `{update.effective_chat.id}`\n"
                f"🎯 **Quiz Type:** {quiz_type}\n"
                f"⏱️ **Uptime:** {uptime_hours}h {uptime_minutes}m\n"
                f"📈 **Success Rate:** {health['success_rate']:.1f}%\n"
                f"📊 **Total Requests:** {health['total_requests']}\n"
                f"⚠️ **Consecutive Failures:** {health['consecutive_failures']}\n"
                f"👥 **Active Users:** {len(self.user_preferences)}\n\n"
                f"🚀 **Ready to create quizzes!** ✨"
            )
            
            result = await self.safe_send_message(
                update.effective_chat.id,
                status_msg,
                parse_mode='Markdown'
            )
            
            if not result:
                # Fallback without markdown
                await self.safe_send_message(
                    update.effective_chat.id,
                    f"Bot Status: {status_emoji} Running\n"
                    f"Uptime: {uptime_hours}h {uptime_minutes}m\n"
                    f"Success Rate: {health['success_rate']:.1f}%\n"
                    f"Active Users: {len(self.user_preferences)}"
                )
                
        except Exception as e:
            logger.warning(f"Error in status_command: {type(e).__name__}")
            try:
                await self.safe_send_message(
                    update.effective_chat.id,
                    "📊 Bot is running! 🚀"
                )
            except:
                pass
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Help command with bulletproof error handling"""
        try:
            if not update or not update.effective_user:
                return
                
            user_id = update.effective_user.id
            self.update_user_activity(user_id)
            
            help_text = (
                "🆘 **Quiz Bot Help** 📚\n\n"
                "🤖 **Commands:**\n"
                "• `/start` ⭐ - Begin quiz creation\n"
                "• `/quickstart` ⚡ - Quick 5-step guide\n"
                "• `/template` 📋 - Get JSON template\n"
                "• `/help` 🆘 - Show this help\n"
                "• `/status` 📊 - Check bot health & settings\n"
                "• `/toggle` 🔄 - Switch quiz types\n\n"
                "📚 **JSON Format:**\n"
                "• `all_q` 📝 - Questions array\n"
                "• `q` ❓ - Question text\n"
                "• `o` 📋 - Answer options (2-4 choices)\n"
                "• `c` ✅ - Correct answer (0=A, 1=B, 2=C, 3=D)\n"
                "• `e` 💡 - Explanation (optional)\n\n"
                "💡 **Pro Tip:** Use `/quickstart` for fastest setup! 🚀"
            )
            
            result = await self.safe_send_message(update.effective_chat.id, help_text, parse_mode='Markdown')
            
            if not result:
                # Fallback without markdown
                simple_help = (
                    "Quiz Bot Help\n\n"
                    "Commands:\n"
                    "/start - Begin quiz creation\n"
                    "/template - Get JSON template\n"
                    "/help - Show this help\n"
                    "/status - Check bot health\n"
                    "/toggle - Switch quiz types\n\n"
                    "Send JSON with your questions to create quizzes!"
                )
                await self.safe_send_message(update.effective_chat.id, simple_help)
                
        except Exception as e:
            logger.warning(f"Error in help_command: {type(e).__name__}")
            try:
                await self.safe_send_message(update.effective_chat.id, "Use /start to begin creating quizzes!")
            except:
                pass
    
    async def template_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Template command with bulletproof error handling"""
        try:
            if not update or not update.effective_user:
                return
                
            user_id = update.effective_user.id
            self.update_user_activity(user_id)
            
            template_msg = "📋 **JSON Template:** 🎯"
            
            result1 = await self.safe_send_message(update.effective_chat.id, template_msg, parse_mode='Markdown')
            
            if result1:
                _, json_template = await self.get_welcome_messages()
                result2 = await self.safe_send_message(update.effective_chat.id, json_template)
                
                if result2:
                    await self.safe_send_message(
                        update.effective_chat.id,
                        "💡 **Copy above template → Give to ChatGPT → Ask to customize with your questions!** 🤖✨",
                        parse_mode='Markdown'
                    )
            else:
                # Fallback
                _, json_template = await self.get_welcome_messages()
                await self.safe_send_message(update.effective_chat.id, "JSON Template:")
                await self.safe_send_message(update.effective_chat.id, json_template)
                await self.safe_send_message(update.effective_chat.id, "Copy this template and customize it with your questions!")
                
        except Exception as e:
            logger.warning(f"Error in template_command: {type(e).__name__}")
            try:
                _, json_template = await self.get_welcome_messages()
                await self.safe_send_message(update.effective_chat.id, json_template)
            except:
                pass
    
    async def quickstart_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Quick start command with bulletproof error handling"""
        try:
            if not update or not update.effective_user:
                return
                
            user_id = update.effective_user.id
            self.update_user_activity(user_id)
            
            quick_msg = (
                "⚡ **Quick Start Guide:** 🚀\n\n"
                "1️⃣ Use `/template` to get JSON format 📋\n"
                "2️⃣ Copy template → Give to AI (ChatGPT) 🤖\n"
                "3️⃣ Ask AI: \"Customize with my questions in this format\" 💭\n"
                "4️⃣ Send customized JSON to me 📤\n"
                "5️⃣ Get instant interactive quizzes! 🎯✨\n\n"
                "**Need help?** Use `/help` for detailed guide 📚"
            )
            
            result = await self.safe_send_message(update.effective_chat.id, quick_msg, parse_mode='Markdown')
            
            if not result:
                # Fallback
                simple_quick = (
                    "Quick Start:\n"
                    "1. Use /template to get format\n"
                    "2. Give template to AI (ChatGPT)\n"
                    "3. Ask AI to customize with your questions\n"
                    "4. Send me the customized JSON\n"
                    "5. Get instant quizzes!"
                )
                await self.safe_send_message(update.effective_chat.id, simple_quick)
                
        except Exception as e:
            logger.warning(f"Error in quickstart_command: {type(e).__name__}")
    
    async def toggle_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Toggle command with bulletproof error handling"""
        try:
            if not update or not update.effective_user:
                return
                
            user_id = update.effective_user.id
            self.update_user_activity(user_id)
            
            keyboard = [
                [InlineKeyboardButton("🔒 Switch to Anonymous", callback_data="anonymous_true")],
                [InlineKeyboardButton("👤 Switch to Non-Anonymous", callback_data="anonymous_false")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            current_type = "🔒 Anonymous" if self.user_preferences.get(user_id, True) else "👤 Non-Anonymous"
            
            result = await self.safe_send_message(
                update.effective_chat.id,
                f"⚙️ **Current Setting:** {current_type} 📊\n\n🔄 **Quick Toggle:** Choose your preferred quiz type: 👇✨",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
            if not result:
                # Fallback without keyboard
                await self.safe_send_message(
                    update.effective_chat.id,
                    f"Current setting: {current_type}\nUse callback buttons or send 'anonymous' or 'non-anonymous' to change."
                )
                
        except Exception as e:
            logger.warning(f"Error in toggle_command: {type(e).__name__}")
    
    async def restart_cycle(self, update: Update):
        """Restart the welcome cycle with bulletproof error handling"""
        try:
            if not update or not update.effective_user:
                return
                
            user_id = update.effective_user.id
            self.update_user_activity(user_id)
            self.user_states[user_id] = "choosing_type"
            
            await asyncio.sleep(0.3)
            
            restart_msg = "🎉 **Ready for another quiz?** ✨"
            result1 = await self.safe_send_message(update.effective_chat.id, restart_msg, parse_mode='Markdown')
            
            if result1:
                await asyncio.sleep(0.2)
                msg1, _ = await self.get_welcome_messages()
                result2 = await self.safe_send_message(update.effective_chat.id, msg1, parse_mode='Markdown')
                
                if result2:
                    await asyncio.sleep(0.2)
                    await self.show_quiz_type_selection(update)
            else:
                # Fallback
                await self.safe_send_message(update.effective_chat.id, "Ready for another quiz? Use /start")
                
        except Exception as e:
            logger.warning(f"Error in restart_cycle: {type(e).__name__}")
    
    async def handle_json_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle JSON messages with comprehensive bulletproof validation"""
        try:
            if not update or not update.message or not update.effective_user:
                return
                
            user_message = update.message.text
            if not user_message:
                return
                
            user_message = user_message.strip()
            user_chat_id = update.effective_chat.id
            user_id = update.effective_user.id
            user_name = update.effective_user.first_name or "User"
            
            self.update_user_activity(user_id)
            
            # Check user state
            if self.user_states.get(user_id) != "waiting_for_json":
                result = await self.safe_send_message(user_chat_id, "🔄 **Let's start properly!** Use /start ✨", parse_mode='Markdown')
                if result:
                    await self.start_command(update, None)
                return
            
            is_anonymous = self.user_preferences.get(user_id, True)
            
            processing_msg = await self.safe_send_message(
                user_chat_id,
                "🔄 **Processing your quiz JSON...** ⚡🎯"
            )
            
            if not processing_msg:
                await self.safe_send_message(user_chat_id, "Processing your quiz...")
                processing_msg = None
            
            # Parse and validate JSON with comprehensive error handling
            try:
                quiz_data = json.loads(user_message)
                
                # Extract questions with multiple possible keys
                questions = None
                for key in ["all_q", "q", "questions", "all_questions", "quiz", "data"]:
                    if key in quiz_data:
                        questions = quiz_data[key]
                        break
                
                if not questions:
                    # Maybe the JSON is directly an array of questions
                    if isinstance(quiz_data, list):
                        questions = quiz_data
                    else:
                        questions = []
                
                if not questions or not isinstance(questions, list):
                    if processing_msg:
                        await self.safe_edit_message(
                            processing_msg,
                            "❌ **No questions found!** 📝\n\n🔄 **Use /template for correct format** 📋",
                            parse_mode='Markdown'
                        )
                    else:
                        await self.safe_send_message(
                            user_chat_id,
                            "❌ No questions found! Use /template for correct format"
                        )
                    
                    await asyncio.sleep(1)
                    await self.restart_cycle(update)
                    return
                
                # Validate and sanitize questions
                valid_questions = []
                for i, question in enumerate(questions[:50]):  # Limit to 50 questions
                    try:
                        if not isinstance(question, dict):
                            continue
                        
                        # Extract question text with multiple possible keys
                        q_text = None
                        for key in ["q", "question", "text", "question_text"]:
                            if key in question and question[key]:
                                q_text = question[key]
                                break
                        
                        if not q_text:
                            continue
                        
                        # Extract options with multiple possible keys
                        options = None
                        for key in ["o", "options", "choices", "answers"]:
                            if key in question and question[key]:
                                options = question[key]
                                break
                        
                        if not options or not isinstance(options, list) or len(options) < 2 or len(options) > 4:
                            continue
                        
                        # Extract correct answer with multiple possible keys
                        correct = None
                        for key in ["c", "correct", "correct_option_id", "answer", "correct_answer"]:
                            if key in question and question[key] is not None:
                                correct = question[key]
                                break
                        
                        if correct is None:
                            correct = 0  # Default to first option
                        
                        # Validate correct answer
                        if not isinstance(correct, int) or correct < 0 or correct >= len(options):
                            correct = 0
                        
                        # Extract explanation with multiple possible keys
                        explanation = ""
                        for key in ["e", "explanation", "desc", "description"]:
                            if key in question and question[key]:
                                explanation = question[key]
                                break
                        
                        # Sanitize all fields
                        valid_question = {
                            "q": str(q_text)[:255],  # Telegram limit
                            "o": [str(opt)[:100] for opt in options[:4]],  # Max 4 options, 100 chars each
                            "c": correct,
                            "e": str(explanation)[:200] if explanation else ""  # 200 char limit for explanation
                        }
                        
                        valid_questions.append(valid_question)
                        
                    except Exception as e:
                        logger.warning(f"Error processing question {i+1}: {type(e).__name__}")
                        continue
                
                if not valid_questions:
                    if processing_msg:
                        await self.safe_edit_message(
                            processing_msg,
                            "❌ **No valid questions found!** 📝\n\n🔄 **Check your JSON format** 📋",
                            parse_mode='Markdown'
                        )
                    else:
                        await self.safe_send_message(
                            user_chat_id,
                            "❌ No valid questions found! Check your JSON format"
                        )
                    
                    await asyncio.sleep(1)
                    await self.restart_cycle(update)
                    return
                
                # Update processing message
                quiz_type = "anonymous" if is_anonymous else "non-anonymous"
                if processing_msg:
                    await self.safe_edit_message(
                        processing_msg,
                        f"✅ **{len(valid_questions)} questions validated!** 🎯\n🚀 Sending {quiz_type} polls... ⚡",
                        parse_mode='Markdown'
                    )
                
                # Send quiz questions
                success_count = await self.send_quiz_questions(valid_questions, user_chat_id, is_anonymous)
                
                if success_count > 0:
                    quiz_type_text = "🔒 Anonymous" if is_anonymous else "👤 Non-Anonymous"
                    completion_msg = f"🎯 **{success_count} {quiz_type_text} quizzes sent successfully!** ✅🎉"
                    
                    if processing_msg:
                        await self.safe_edit_message(processing_msg, completion_msg, parse_mode='Markdown')
                    else:
                        await self.safe_send_message(user_chat_id, completion_msg, parse_mode='Markdown')
                    
                    logger.warning(f"Served {success_count} MCQs to {user_name}")
                    
                    # Restart cycle for new quiz
                    await asyncio.sleep(1)
                    await self.restart_cycle(update)
                else:
                    if processing_msg:
                        await self.safe_edit_message(
                            processing_msg,
                            "❌ **Failed to send quizzes** 📊\n\n🔄 **Please try again** 🔄",
                            parse_mode='Markdown'
                        )
                    else:
                        await self.safe_send_message(
                            user_chat_id,
                            "❌ Failed to send quizzes. Please try again"
                        )
                    
                    await asyncio.sleep(1)
                    await self.restart_cycle(update)
                
            except json.JSONDecodeError:
                if processing_msg:
                    await self.safe_edit_message(
                        processing_msg,
                        "❌ **Invalid JSON Format!** 📋\n\n🔄 **Use /template for correct format** ✨",
                        parse_mode='Markdown'
                    )
                else:
                    await self.safe_send_message(
                        user_chat_id,
                        "❌ Invalid JSON! Use /template for correct format"
                    )
                
                await asyncio.sleep(1)
                await self.restart_cycle(update)
                
            except Exception as e:
                logger.warning(f"JSON processing error: {type(e).__name__}")
                
                if processing_msg:
                    await self.safe_edit_message(
                        processing_msg,
                        "❌ **Processing error occurred!** ⚠️\n\n🔄 **Please try again** 🔄",
                        parse_mode='Markdown'
                    )
                else:
                    await self.safe_send_message(
                        user_chat_id,
                        "❌ Error occurred! Please try again"
                    )
                
                await asyncio.sleep(1)
                await self.restart_cycle(update)
                
        except Exception as e:
            logger.warning(f"Error in handle_json_message: {type(e).__name__}")
            # Ultimate fallback - never crash
            try:
                await self.safe_send_message(
                    update.effective_chat.id,
                    "❌ **Error occurred!** Use /start to restart"
                )
            except:
                pass
    
    # ========================================================================
    # ERROR HANDLER
    # ========================================================================
    
    def bulletproof_error_handler(self, update, context):
        """Bulletproof error handler that never crashes"""
        try:
            error = context.error
            self.health_monitor.record_failure()
            
            # Log error types we care about
            if isinstance(error, (NetworkError, TimedOut)):
                # Don't log network errors - they're expected
                pass
            elif isinstance(error, (BadRequest, Forbidden)):
                logger.warning(f"Client error: {type(error).__name__}")
            else:
                logger.warning(f"Bot error: {type(error).__name__}")
                
        except Exception:
            # Never let error handler crash
            pass
    
    # ========================================================================
    # MAIN RUN METHOD
    # ========================================================================
    
    def run(self):
        """
        Run the bot with maximum bulletproofing and automatic recovery.
        This method handles all possible failure scenarios and ensures 24/7 operation.
        """
        restart_count = 0
        max_restarts = 100  # Prevent infinite restart loops
        
        while not self.should_stop and restart_count < max_restarts:
            try:
                restart_count += 1
                logger.warning(f"Starting bot (attempt {restart_count})")
                
                # Create application with bulletproof settings optimized for PythonAnywhere
                app_builder = Application.builder().token(self.telegram_token)
                
                # Optimized settings for PythonAnywhere shared hosting
                app_builder.pool_timeout(300)                    # 5 minutes pool timeout
                app_builder.connection_pool_size(2)              # Minimal pool size for shared hosting
                app_builder.get_updates_pool_timeout(300)        # 5 minutes get updates timeout
                app_builder.read_timeout(120)                    # 2 minutes read timeout
                app_builder.write_timeout(120)                   # 2 minutes write timeout
                app_builder.connect_timeout(120)                 # 2 minutes connect timeout
                
                # Build the application
                self.application = app_builder.build()
                
                # Add bulletproof error handler
                self.application.add_error_handler(self.bulletproof_error_handler)
                
                # Add command handlers with error protection
                handlers = [
                    CommandHandler("start", self.start_command),
                    CommandHandler("help", self.help_command),
                    CommandHandler("template", self.template_command),
                    CommandHandler("quickstart", self.quickstart_command),
                    CommandHandler("status", self.status_command),
                    CommandHandler("toggle", self.toggle_command),
                    CallbackQueryHandler(self.handle_quiz_type_selection),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_json_message)
                ]
                
                for handler in handlers:
                    self.application.add_handler(handler)
                
                # Start background maintenance tasks
                self.start_background_tasks()
                
                logger.warning("🚀 Bot starting with bulletproof configuration...")
                
                # Mark as running
                self.is_running = True
                
                # Run with bulletproof polling settings for PythonAnywhere
                self.application.run_polling(
                    allowed_updates=Update.ALL_TYPES,
                    drop_pending_updates=True,           # Always drop pending updates on restart
                    poll_interval=3.0,                   # Conservative 3-second polling interval
                    timeout=120,                         # 2 minutes timeout for long polling
                    bootstrap_retries=5,                 # Limited bootstrap retries
                    close_loop=False,                    # Don't close the event loop
                    stop_signals=None                    # We handle signals ourselves
                )
                
                # If we reach here, bot stopped normally
                logger.warning("Bot stopped normally")
                break
                
            except KeyboardInterrupt:
                logger.warning("Bot stopped by user (Ctrl+C)")
                self.should_stop = True
                break
                
            except Exception as e:
                logger.warning(f"Bot crashed: {type(e).__name__}: {e}")
                
                # Mark as not running
                self.is_running = False
                
                # Clean up application
                if self.application:
                    try:
                        self.application.stop()
                        self.application.shutdown()
                    except:
                        pass
                    self.application = None
                
                # Progressive backoff delay
                if restart_count < 5:
                    delay = 5  # 5 seconds for first few restarts
                elif restart_count < 10:
                    delay = 30  # 30 seconds for moderate restarts
                else:
                    delay = 120  # 2 minutes for frequent restarts
                
                logger.warning(f"Restarting in {delay} seconds... (attempt {restart_count})")
                time.sleep(delay)
                
                # Force cleanup on restart
                self.aggressive_cleanup()
                self.memory_manager.force_cleanup()
                
        if restart_count >= max_restarts:
            logger.error("Maximum restart attempts reached. Bot stopping.")
        
        # Final cleanup
        self.should_stop = True
        if self.cleanup_thread and self.cleanup_thread.is_alive():
            self.cleanup_thread.join(timeout=5)


# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    """
    Main function with comprehensive error handling and validation
    """
    print("🚀 Initializing Bulletproof Telegram Quiz Bot...")
    
    # Get bot token from environment or user input
    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    
    if not bot_token:
        # Placeholder token - MUST be replaced with actual token
        bot_token = "YOUR_BOT_TOKEN_HERE"
    
    if not bot_token or bot_token == "YOUR_BOT_TOKEN_HERE":
        print("❌ ERROR: No valid bot token provided!")
        print("📝 Please:")
        print("   1. Replace 'YOUR_BOT_TOKEN_HERE' with your actual bot token, OR")
        print("   2. Set TELEGRAM_BOT_TOKEN environment variable")
        print("   3. Get your token from @BotFather on Telegram")
        return
    
    # Validate token format
    if not bot_token.strip() or ':' not in bot_token:
        print("❌ ERROR: Invalid bot token format!")
        print("📝 Token should look like: 123456789:ABCdefGHIjklMNOpqrSTUvwxyz")
        return
    
    try:
        # Create and run the bulletproof bot
        bot = BulletproofTelegramQuizBot(bot_token.strip())
        
        print("✅ Bot initialized successfully!")
        print("🔧 Configuration:")
        print(f"   • Max users in memory: {bot.max_stored_users}")
        print(f"   • User data TTL: {bot.user_data_ttl} seconds")
        print(f"   • Max retries: {bot.max_retries}")
        print(f"   • Request timeout: {bot.request_timeout} seconds")
        print("🌟 Starting bot with bulletproof configuration...")
        print("⚡ Press Ctrl+C to stop\n")
        
        # Run the bot
        bot.run()
        
    except KeyboardInterrupt:
        print("\n👋 Bot stopped by user")
    except Exception as e:
        print(f"\n💥 Critical error: {type(e).__name__}: {e}")
        print("📋 Full traceback:")
        traceback.print_exc()
    finally:
        print("🔄 Bot shutdown complete")


if __name__ == "__main__":
    main()
