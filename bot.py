import os
import re
import asyncio
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PhoneNumberInvalidError, ChannelPrivateError, ChatWriteForbiddenError
from telethon.tl.types import Channel, Chat, MessageMediaPhoto, MessageMediaDocument, MessageMediaWebPage
from flask import Flask
from threading import Thread
import logging
from typing import Dict, List, Optional
import tempfile
import shutil
import signal
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Environment variables
API_ID = int(os.environ.get('API_ID', '20598098'))
API_HASH = os.environ.get('API_HASH', 'c1727e40f8585b869cef73b828b2bf69')
BOT_TOKEN = os.environ.get('BOT_TOKEN', '8481545345:AAEIB3zKphtr29h0232hykXuG_qIRllk1aQ')
PORT = int(os.environ.get('PORT', '8080'))

# User data storage
user_sessions: Dict[int, str] = {}
user_settings: Dict[int, 'UserSettings'] = {}
active_extractions: Dict[int, bool] = {}
user_conversations: Dict[int, dict] = {}

# Global bot instance
bot_client = None

class UserSettings:
    def __init__(self):
        self.target_chat_id: Optional[int] = None
        self.custom_caption: Optional[str] = None
        self.thumbnail = None
        self.replace_words: Dict[str, str] = {}
        self.remove_words: List[str] = []

def get_user_settings(user_id: int) -> UserSettings:
    if user_id not in user_settings:
        user_settings[user_id] = UserSettings()
    return user_settings[user_id]

# Health check web server
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running! ✅", 200

@app.route('/health')
def health():
    global bot_client
    status = "connected" if bot_client and bot_client.is_connected() else "disconnected"
    return {"status": "ok", "bot": status}, 200

@app.route('/ping')
def ping():
    return "pong", 200

def run_flask():
    try:
        app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)
    except Exception as e:
        logger.error(f"Flask error: {e}")

def keep_alive():
    t = Thread(target=run_flask, daemon=True)
    t.start()
    logger.info(f"✅ Health check server started on port {PORT}")

def parse_channel_link(link: str):
    """Parse channel link and return entity and message ID"""
    link = link.strip()
    
    # Pattern 1: t.me/c/CHANNEL_ID/MSG_ID (private channel)
    match = re.search(r't\.me/c/(\d+)/(\d+)', link)
    if match:
        channel_id = int(match.group(1))
        channel_entity = int(f"-100{channel_id}")
        msg_id = int(match.group(2))
        return channel_entity, msg_id, True
    
    # Pattern 2: t.me/USERNAME/MSG_ID (public channel)
    match = re.search(r't\.me/([^/]+)/(\d+)', link)
    if match:
        username = match.group(1)
        msg_id = int(match.group(2))
        return username, msg_id, False
    
    return None, None, None

async def start_bot():
    """Initialize and start the Telegram bot"""
    global bot_client
    
    bot = TelegramClient('bot_session', API_ID, API_HASH, 
                        connection_retries=5,
                        retry_delay=5,
                        timeout=30)
    
    try:
        await bot.start(bot_token=BOT_TOKEN)
        bot_client = bot
        logger.info("✅ Bot connected to Telegram!")
        
        # Test bot is working
        me = await bot.get_me()
        logger.info(f"✅ Bot username: @{me.username}")
        logger.info(f"✅ Bot ID: {me.id}")
        
    except Exception as e:
        logger.error(f"❌ Failed to start bot: {e}")
        raise
    
    @bot.on(events.NewMessage(pattern='/ping'))
    async def ping_handler(event):
        logger.info(f"📥 Ping from {event.sender_id}")
        try:
            await bot.send_message(
                user_id,
                f"🎉 **Extraction Complete!**\n\n"
                f"✅ Extracted: {extracted}\n"
                f"❌ Failed: {failed}\n"
                f"📊 Total: {count}\n"
                f"📈 Success: {success_rate}%\n\n"
                f"{'🌟 Perfect!' if success_rate >= 90 else '💡 Some posts missing' if success_rate > 0 else '❌ No posts extracted'}"
            )
        
        except Exception as e:
            active_extractions[user_id] = False
            logger.error(f"Fatal extraction error: {e}", exc_info=True)
            await bot.send_message(user_id, f"❌ **Fatal Error:** {str(e)}")
        
        finally:
            if client and client != bot:
                try:
                    await client.disconnect()
                except:
                    pass
            
            if temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                    logger.info(f"🗑️ Cleaned temp dir: {temp_dir}")
                except Exception as e:
                    logger.error(f"Cleanup error: {e}")

    @bot.on(events.CallbackQuery)
    async def callback_handler(event):
        user_id = event.sender_id
        data = event.data.decode()
        await event.answer()
        
        try:
            if data == "set_chat_id":
                await event.respond("📍 Send target chat ID:")
                user_conversations[user_id] = {'step': 'set_chat_id'}
            
            elif data == "replace_words":
                await event.respond("✏️ Format: old | new")
                user_conversations[user_id] = {'step': 'replace_words'}
            
            elif data == "remove_words":
                await event.respond("🗑️ Send word to remove:")
                user_conversations[user_id] = {'step': 'remove_words'}
            
            elif data == "custom_caption":
                await event.respond("💬 Send custom caption:")
                user_conversations[user_id] = {'step': 'custom_caption'}
            
            elif data == "set_thumbnail":
                await event.respond("🖼️ Send thumbnail image:")
                user_conversations[user_id] = {'step': 'set_thumbnail'}
            
            elif data == "view_settings":
                settings = get_user_settings(user_id)
                target = f"`{settings.target_chat_id}`" if settings.target_chat_id else "DM"
                caption = (settings.custom_caption[:50] + "...") if settings.custom_caption else "None"
                
                await event.respond(
                    f"📊 **Settings**\n\n"
                    f"📍 Target: {target}\n"
                    f"💬 Caption: {caption}\n"
                    f"✏️ Replacements: {len(settings.replace_words)}\n"
                    f"🗑️ Removals: {len(settings.remove_words)}\n"
                    f"🖼️ Thumbnail: {'✅' if settings.thumbnail else '❌'}"
                )
            
            elif data == "reset_settings":
                user_settings[user_id] = UserSettings()
                await event.respond("🔄 Settings reset!")
        
        except Exception as e:
            logger.error(f"Callback error: {e}")
            await event.respond(f"❌ Error: {str(e)}")

    logger.info("🎉 Bot is now running and listening for messages!")
    
    # Keep bot alive
    try:
        await bot.run_until_disconnected()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot run error: {e}", exc_info=True)
    finally:
        await bot.disconnect()

def signal_handler(signum, frame):
    """Handle shutdown signals"""
    logger.info("Received shutdown signal, cleaning up...")
    sys.exit(0)

async def main():
    """Main entry point"""
    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # Start health check server
        keep_alive()
        
        # Small delay to ensure Flask starts
        await asyncio.sleep(2)
        
        # Start bot
        logger.info("🚀 Starting Telegram bot...")
        await start_bot()
        
    except KeyboardInterrupt:
        logger.info("Stopped by user")
    except Exception as e:
        logger.error(f"Fatal error in main: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("🤖 TELEGRAM CHANNEL EXTRACTOR BOT")
    logger.info("=" * 60)
    logger.info(f"API_ID: {'✅ Set' if API_ID else '❌ Missing'}")
    logger.info(f"API_HASH: {'✅ Set' if API_HASH else '❌ Missing'}")
    logger.info(f"BOT_TOKEN: {'✅ Set' if BOT_TOKEN else '❌ Missing'}")
    logger.info(f"PORT: {PORT}")
    logger.info("=" * 60)
    
    if not all([API_ID, API_HASH, BOT_TOKEN]):
        logger.error("❌ Missing required environment variables!")
        sys.exit(1)
    
    try:
        # Run the bot
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Bot stopped by user!")
    except Exception as e:
        logger.error(f"💥 Bot failed: {e}", exc_info=True)
        sys.exit(1) event.respond("🏓 Pong! Bot is alive and running.")
        except Exception as e:
            logger.error(f"Ping error: {e}")

    @bot.on(events.NewMessage(pattern='/start'))
    async def start_handler(event):
        logger.info(f"📥 Start command from {event.sender_id}")
        try:
            welcome_msg = """
🌟 **Welcome to Universal Channel Extractor Bot!** 🌟

Main **PUBLIC aur PRIVATE** dono channels se posts extract kar sakta hoon!

**📋 Commands:**
/batch - Extract posts
/login - Login for private channels
/settings - Bot settings
/logout - Logout from session
/cancel - Cancel extraction
/help - Detailed guide
/id - Get chat ID
/ping - Check if bot is alive

**🚀 Quick Start:**

**For PUBLIC channels:**
1. /batch
2. Paste any public channel post link
3. Enter number of posts
4. Done! ✅

**For PRIVATE channels:**
1. First /login (one time only)
2. Then /batch with private channel link
3. Done! ✅

**Need Help?** Type /help
"""
            await event.respond(welcome_msg)
            logger.info(f"✅ Start response sent to {event.sender_id}")
        except Exception as e:
            logger.error(f"Start handler error: {e}")

    @bot.on(events.NewMessage(pattern='/help'))
    async def help_handler(event):
        logger.info(f"📥 Help command from {event.sender_id}")
        try:
            help_text = """
📖 **Complete Guide**

**PUBLIC Channels (No Login):**
✅ Directly use /batch
✅ Paste post link
✅ Enter count
✅ Works instantly!

**PRIVATE Channels (Need Login):**
1️⃣ First time: Use /login
   • Enter phone: +919876543210
   • Enter OTP: 1 2 3 4 5
   • If 2FA: Enter password
   
2️⃣ After login: Use /batch normally
   • Works for ALL private channels you've joined
   • Login once, use forever!

**Auto-Post to Your Channel:**
1. Add bot as admin in target channel
2. Use /id in that channel
3. Copy the channel ID
4. /settings → Set Chat ID
5. Paste ID
6. Done! All posts go there directly

**Customization:**
• Replace Words - Change text in captions
• Custom Caption - Add your caption
• Set Thumbnail - Custom thumbnail
• Remove Words - Delete unwanted text

**Important Notes:**
⚠️ You must be JOINED in the channel (public/private)
⚠️ For private channels, /login is MANDATORY
⚠️ Bot can't extract from channels you haven't joined

**Rate Limits:**
• Max: 1000 posts per batch
• Recommended: 10-50 posts

Need help? Just ask! 😊
"""
            await event.respond(help_text)
        except Exception as e:
            logger.error(f"Help handler error: {e}")

    @bot.on(events.NewMessage(pattern='/login'))
    async def login_handler(event):
        user_id = event.sender_id
        logger.info(f"📥 Login command from {user_id}")
        
        try:
            if user_id in user_conversations:
                del user_conversations[user_id]
            
            await event.respond(
                "📱 **Login to Your Telegram Account**\n\n"
                "⚠️ **IMPORTANT:** Use the SAME account that has access to private channels!\n\n"
                "Enter phone number with country code:\n"
                "✅ Example: +919876543210"
            )
            
            user_conversations[user_id] = {'step': 'phone', 'client': None}
        except Exception as e:
            logger.error(f"Login handler error: {e}")

    @bot.on(events.NewMessage(pattern='/logout'))
    async def logout_handler(event):
        user_id = event.sender_id
        try:
            if user_id in user_sessions:
                del user_sessions[user_id]
                await event.respond("👋 **Logged Out Successfully!**\n\nYou can login again with /login")
            else:
                await event.respond("❌ You're not logged in.")
        except Exception as e:
            logger.error(f"Logout handler error: {e}")
    
    @bot.on(events.NewMessage(pattern='/session'))
    async def session_handler(event):
        """Export session string for debugging"""
        user_id = event.sender_id
        try:
            if user_id in user_sessions:
                session_str = user_sessions[user_id]
                await event.respond(
                    f"🔑 **Your Session String:**\n\n"
                    f"`{session_str[:50]}...`\n\n"
                    f"⚠️ Keep this private! Anyone with this can access your account."
                )
            else:
                await event.respond("❌ You're not logged in. Use /login first.")
        except Exception as e:
            logger.error(f"Session handler error: {e}")

    @bot.on(events.NewMessage(pattern='/batch'))
    async def batch_handler(event):
        user_id = event.sender_id
        logger.info(f"📥 Batch command from {user_id}")
        
        try:
            if active_extractions.get(user_id):
                await event.respond("⚠️ **Extraction Already Running!**\n\nUse /cancel to stop it first.")
                return
            
            if user_id in user_conversations:
                del user_conversations[user_id]
            
            await event.respond(
                "📎 **Batch Extraction**\n\n"
                "Send me the post link:\n\n"
                "✅ **Public channel:** https://t.me/channelname/123\n"
                "✅ **Private channel:** https://t.me/c/1234567890/123\n\n"
                "💡 Tip: For private channels, make sure you've used /login first!"
            )
            
            user_conversations[user_id] = {'step': 'link', 'data': {}}
        except Exception as e:
            logger.error(f"Batch handler error: {e}")

    @bot.on(events.NewMessage(pattern='/cancel'))
    async def cancel_handler(event):
        user_id = event.sender_id
        
        try:
            if active_extractions.get(user_id):
                active_extractions[user_id] = False
                await event.respond("✋ **Extraction Cancelled!**")
            
            if user_id in user_conversations:
                del user_conversations[user_id]
                if not active_extractions.get(user_id):
                    await event.respond("🔄 **Operation cancelled!**")
        except Exception as e:
            logger.error(f"Cancel handler error: {e}")

    @bot.on(events.NewMessage(pattern='/id'))
    async def id_handler(event):
        try:
            chat_id = event.chat_id
            user_id = event.sender_id
            chat_type = "Channel" if str(chat_id).startswith('-100') else "Group" if chat_id < 0 else "Private"
            
            await event.respond(
                f"🆔 **Chat Information**\n\n"
                f"**Chat ID:** `{chat_id}`\n"
                f"**Your ID:** `{user_id}`\n"
                f"**Type:** {chat_type}\n\n"
                f"💡 Copy Chat ID for settings!"
            )
        except Exception as e:
            logger.error(f"ID handler error: {e}")

    @bot.on(events.NewMessage(pattern='/settings'))
    async def settings_handler(event):
        try:
            buttons = [
                [Button.inline("📍 Set Target Chat ID", b"set_chat_id")],
                [Button.inline("✏️ Replace Words", b"replace_words")],
                [Button.inline("🗑️ Remove Words", b"remove_words")],
                [Button.inline("💬 Custom Caption", b"custom_caption")],
                [Button.inline("🖼️ Set Thumbnail", b"set_thumbnail")],
                [Button.inline("📊 View Settings", b"view_settings")],
                [Button.inline("🔄 Reset Settings", b"reset_settings")]
            ]
            await event.respond("⚙️ **Settings Menu**", buttons=buttons)
        except Exception as e:
            logger.error(f"Settings handler error: {e}")

    @bot.on(events.NewMessage(incoming=True, func=lambda e: e.text and not e.text.startswith('/')))
    async def message_handler(event):
        user_id = event.sender_id
        
        if user_id not in user_conversations:
            return
        
        conv_data = user_conversations[user_id]
        step = conv_data.get('step')
        logger.info(f"📥 Processing step '{step}' for user {user_id}")
        
        try:
            # ===== LOGIN FLOW =====
            if step == 'phone':
                phone = event.text.strip()
                logger.info(f"Phone received from {user_id}")
                
                if not re.match(r'^\+\d{10,15}$', phone):
                    await event.respond("❌ **Invalid format!**\n\nExample: +919876543210\n\nTry again:")
                    return
                
                try:
                    user_client = TelegramClient(StringSession(), API_ID, API_HASH)
                    await user_client.connect()
                    await user_client.send_code_request(phone)
                    
                    conv_data['client'] = user_client
                    conv_data['phone'] = phone
                    conv_data['step'] = 'otp'
                    
                    await event.respond("✅ **OTP Sent!**\n\nEnter OTP with spaces:\n✅ Example: 1 2 3 4 5")
                    
                except Exception as e:
                    logger.error(f"Phone error: {e}")
                    await event.respond(f"❌ Error: {str(e)}\n\nTry /login again")
                    del user_conversations[user_id]
            
            elif step == 'otp':
                code = event.text.replace(' ', '').strip()
                logger.info(f"OTP received from {user_id}")
                
                if not code.isdigit() or len(code) < 5:
                    await event.respond("❌ Invalid OTP!\n\nEnter 5-digit code: 1 2 3 4 5")
                    return
                
                user_client = conv_data['client']
                phone = conv_data['phone']
                
                try:
                    await user_client.sign_in(phone, code)
                    session_string = user_client.session.save()
                    user_sessions[user_id] = session_string
                    logger.info(f"✅ Login successful for {user_id}")
                    
                    await event.respond(
                        "🎉 **Login Successful!**\n\n"
                        "✅ You can now extract from private channels!\n"
                        "✅ Use /batch to start extraction"
                    )
                    await user_client.disconnect()
                    del user_conversations[user_id]
                    
                except SessionPasswordNeededError:
                    conv_data['step'] = 'password'
                    await event.respond("🔐 **2FA Detected**\n\nEnter your password:")
                    
                except PhoneCodeInvalidError:
                    await event.respond("❌ **Invalid OTP!**\n\nTry again:")
                    
                except Exception as e:
                    logger.error(f"OTP error: {e}")
                    await event.respond(f"❌ Error: {str(e)}\n\nTry /login again")
                    if user_client:
                        await user_client.disconnect()
                    del user_conversations[user_id]
            
            elif step == 'password':
                password = event.text.strip()
                logger.info(f"Password received from {user_id}")
                user_client = conv_data['client']
                
                try:
                    await user_client.sign_in(password=password)
                    session_string = user_client.session.save()
                    user_sessions[user_id] = session_string
                    logger.info(f"✅ 2FA Login successful for {user_id}")
                    
                    await event.respond(
                        "🎉 **Login Successful!**\n\n"
                        "✅ You can now extract from private channels!"
                    )
                    await user_client.disconnect()
                    del user_conversations[user_id]
                    
                except Exception as e:
                    logger.error(f"Password error: {e}")
                    await event.respond(f"❌ Wrong password!\n\n{str(e)}\n\nTry /login again")
                    if user_client:
                        await user_client.disconnect()
                    del user_conversations[user_id]
            
            # ===== BATCH FLOW =====
            elif step == 'link':
                post_link = event.text.strip()
                logger.info(f"Link received from {user_id}")
                
                channel_entity, start_msg_id, is_private = parse_channel_link(post_link)
                
                if not channel_entity or not start_msg_id:
                    await event.respond(
                        "❌ **Invalid Link!**\n\n"
                        "✅ Public: https://t.me/channelname/123\n"
                        "✅ Private: https://t.me/c/1234567890/123\n\n"
                        "Try again:"
                    )
                    return
                
                if is_private and user_id not in user_sessions:
                    await event.respond(
                        "⚠️ **Private Channel Detected!**\n\n"
                        "❌ You haven't logged in yet.\n\n"
                        "Please use /login first, then try /batch again!"
                    )
                    del user_conversations[user_id]
                    return
                
                conv_data['data']['channel'] = channel_entity
                conv_data['data']['start_id'] = start_msg_id
                conv_data['data']['is_private'] = is_private
                conv_data['step'] = 'count'
                
                await event.respond(
                    f"✅ **Link Valid!**\n"
                    f"{'🔒 Private' if is_private else '🌐 Public'} Channel\n\n"
                    f"🔢 How many posts to extract?\n\n"
                    f"💡 Max: 1000\n"
                    f"💡 Recommended: 10-50"
                )
            
            elif step == 'count':
                try:
                    count = int(event.text.strip())
                    logger.info(f"Count received from {user_id}: {count}")
                    
                    if count <= 0:
                        await event.respond("❌ Must be > 0!")
                        return
                    if count > 1000:
                        await event.respond("⚠️ Max 1000! Try again:")
                        return
                    
                    channel_entity = conv_data['data']['channel']
                    start_msg_id = conv_data['data']['start_id']
                    is_private = conv_data['data']['is_private']
                    
                    del user_conversations[user_id]
                    
                    # Run extraction in background
                    asyncio.create_task(extract_posts(bot, user_id, channel_entity, start_msg_id, count, is_private))
                    
                except ValueError:
                    await event.respond("❌ Invalid number!")
            
            # ===== SETTINGS =====
            elif step == 'set_chat_id':
                try:
                    chat_id = int(event.text.strip())
                    settings = get_user_settings(user_id)
                    settings.target_chat_id = chat_id
                    await event.respond(f"✅ **Target set:** `{chat_id}`")
                    del user_conversations[user_id]
                except ValueError:
                    await event.respond("❌ Invalid ID!")
            
            elif step == 'replace_words':
                parts = event.text.split('|')
                if len(parts) == 2:
                    old_word = parts[0].strip()
                    new_word = parts[1].strip()
                    settings = get_user_settings(user_id)
                    settings.replace_words[old_word] = new_word
                    await event.respond(f"✅ '{old_word}' → '{new_word}'")
                    del user_conversations[user_id]
                else:
                    await event.respond("❌ Format: old | new")
            
            elif step == 'remove_words':
                word = event.text.strip()
                if word:
                    settings = get_user_settings(user_id)
                    settings.remove_words.append(word)
                    await event.respond(f"✅ Will remove: '{word}'")
                    del user_conversations[user_id]
            
            elif step == 'custom_caption':
                settings = get_user_settings(user_id)
                settings.custom_caption = event.text
                await event.respond(f"✅ Caption set!")
                del user_conversations[user_id]
            
            elif step == 'set_thumbnail':
                if event.photo or event.document:
                    settings = get_user_settings(user_id)
                    settings.thumbnail = event.photo or event.document
                    await event.respond("✅ Thumbnail set!")
                    del user_conversations[user_id]
                else:
                    await event.respond("❌ Send image!")
        
        except Exception as e:
            logger.error(f"Message handler error: {e}", exc_info=True)
            await event.respond(f"❌ Error: {str(e)}")
            if user_id in user_conversations:
                del user_conversations[user_id]

    async def extract_posts(bot, user_id, channel_entity, start_msg_id, count, is_private):
        """Main extraction logic with improved file handling"""
        logger.info(f"🚀 Starting extraction for {user_id}")
        
        temp_dir = None
        client = None
        
        try:
            active_extractions[user_id] = True
            
            # Create temporary directory
            temp_dir = tempfile.mkdtemp(prefix=f"tg_extract_{user_id}_")
            logger.info(f"📁 Temp directory: {temp_dir}")
            
            # Select client
            if is_private:
                if user_id not in user_sessions:
                    await bot.send_message(user_id, "❌ **Private Channel - Login Required!**\n\nUse /login first!")
                    active_extractions[user_id] = False
                    return
                
                client = TelegramClient(StringSession(user_sessions[user_id]), API_ID, API_HASH)
                await client.connect()
                logger.info(f"✅ Using user session for private channel")
                await bot.send_message(user_id, "✅ Using your logged-in account")
            else:
                client = bot
                logger.info(f"✅ Using bot session for public channel")
                await bot.send_message(user_id, "ℹ️ Using bot account")
            
            # Test access
            try:
                await bot.send_message(user_id, "🔍 Testing channel access...")
                entity = await client.get_entity(channel_entity)
                logger.info(f"✅ Got entity: {getattr(entity, 'title', entity)}")
                
                test_msgs = await client.get_messages(entity, limit=1)
                if not test_msgs:
                    raise ValueError("Cannot access messages")
                
                await bot.send_message(user_id, "✅ Access verified! Starting...")
                
            except Exception as e:
                error_msg = str(e)
                await bot.send_message(
                    user_id,
                    f"❌ **Cannot Access Channel!**\n\n"
                    f"Error: {error_msg}\n\n"
                    f"Solutions:\n"
                    f"• Check if you joined the channel\n"
                    f"• For private: Use /login first\n"
                    f"• Verify channel exists"
                )
                active_extractions[user_id] = False
                if client != bot:
                    await client.disconnect()
                return
            
            # Get settings
            settings = get_user_settings(user_id)
            target_chat = settings.target_chat_id or user_id
            
            # Test target if different
            if target_chat != user_id:
                try:
                    test = await bot.send_message(target_chat, "🧪 Testing...")
                    await test.delete()
                    await bot.send_message(user_id, f"✅ Target OK: {target_chat}")
                except Exception as e:
                    await bot.send_message(
                        user_id,
                        f"❌ **Cannot send to target!**\n\n"
                        f"Add bot as ADMIN with post permission"
                    )
                    active_extractions[user_id] = False
                    if client != bot:
                        await client.disconnect()
                    return
            
            # Start extraction
            progress_msg = await bot.send_message(user_id, f"⚙️ **Extracting {count} posts...**\n⏳ Please wait...")
            
            extracted = 0
            failed = 0
            last_update = 0
            
            entity = await client.get_entity(channel_entity)
            
            for i in range(count):
                if not active_extractions.get(user_id):
                    await bot.send_message(user_id, "❌ Cancelled!")
                    break
                
                msg_id = start_msg_id + i
                file_path = None
                
                try:
                    message = await client.get_messages(entity, ids=msg_id)
                    
                    if not message or message.empty:
                        failed += 1
                        continue
                    
                    # Process caption
                    caption = message.text or ""
                    for old, new in settings.replace_words.items():
                        caption = caption.replace(old, new)
                    for word in settings.remove_words:
                        caption = caption.replace(word, "")
                    if settings.custom_caption:
                        caption = f"{caption}\n\n{settings.custom_caption}" if caption else settings.custom_caption
                    if len(caption) > 1024:
                        caption = caption[:1021] + "..."
                    
                    # Send message
                    sent = False
                    
                    if message.media:
                        try:
                            if isinstance(message.media, MessageMediaWebPage):
                                if caption:
                                    await bot.send_message(target_chat, caption)
                                    sent = True
                            else:
                                try:
                                    await bot.send_file(target_chat, message.media, caption=caption or None, force_document=False)
                                    sent = True
                                except:
                                    file_path = await client.download_media(message.media, file=temp_dir)
                                    if file_path and os.path.exists(file_path):
                                        await bot.send_file(target_chat, file_path, caption=caption or None, force_document=False)
                                        sent = True
                                        os.remove(file_path)
                                        file_path = None
                        except Exception as media_err:
                            logger.error(f"Media error {msg_id}: {media_err}")
                            if caption:
                                await bot.send_message(target_chat, f"⚠️ Media failed:\n{caption}")
                                sent = True
                    elif caption:
                        await bot.send_message(target_chat, caption)
                        sent = True
                    
                    if sent:
                        extracted += 1
                    else:
                        failed += 1
                    
                    # Update progress
                    if extracted - last_update >= 5 or i == count - 1:
                        try:
                            progress = int((i + 1) / count * 100)
                            await progress_msg.edit(
                                f"⚙️ **Extracting...**\n\n"
                                f"✅ Done: {extracted}/{count}\n"
                                f"❌ Failed: {failed}\n"
                                f"📊 Progress: {progress}%"
                            )
                            last_update = extracted
                        except:
                            pass
                    
                    await asyncio.sleep(1)
                
                except Exception as e:
                    failed += 1
                    logger.error(f"Error {msg_id}: {e}")
                    if file_path and os.path.exists(file_path):
                        try:
                            os.remove(file_path)
                        except:
                            pass
            
            # Complete
            active_extractions[user_id] = False
            success_rate = int((extracted / count) * 100) if count > 0 else 0
            
            await
