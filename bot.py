import os
import re
import asyncio
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, ChannelPrivateError
from telethon.tl.types import MessageMediaWebPage
from flask import Flask
from threading import Thread
import logging
import tempfile
import shutil
import signal
import sys

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Environment variables
API_ID = int(os.environ.get('API_ID', '20598098'))
API_HASH = os.environ.get('API_HASH', 'c1727e40f8585b869cef73b828b2bf69')
BOT_TOKEN = os.environ.get('BOT_TOKEN', '8481545345:AAEIB3zKphtr29h0232hykXuG_qIRllk1aQ')
PORT = int(os.environ.get('PORT', '8080'))

# Storage
user_sessions = {}
user_settings = {}
active_extractions = {}
user_conversations = {}
bot_client = None

class UserSettings:
    def __init__(self):
        self.target_chat_id = None
        self.custom_caption = None
        self.thumbnail = None
        self.replace_words = {}
        self.remove_words = []

def get_user_settings(user_id):
    if user_id not in user_settings:
        user_settings[user_id] = UserSettings()
    return user_settings[user_id]

# Flask health check
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running! ✅", 200

@app.route('/health')
def health():
    global bot_client
    status = "connected" if bot_client and bot_client.is_connected() else "disconnected"
    return {"status": "ok", "bot": status}, 200

def run_flask():
    try:
        app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)
    except Exception as e:
        logger.error(f"Flask error: {e}")

def keep_alive():
    t = Thread(target=run_flask, daemon=True)
    t.start()
    logger.info(f"Health check server started on port {PORT}")

def parse_channel_link(link):
    link = link.strip()
    match = re.search(r't\.me/c/(\d+)/(\d+)', link)
    if match:
        channel_id = int(match.group(1))
        channel_entity = int(f"-100{channel_id}")
        msg_id = int(match.group(2))
        return channel_entity, msg_id, True
    match = re.search(r't\.me/([^/]+)/(\d+)', link)
    if match:
        username = match.group(1)
        msg_id = int(match.group(2))
        return username, msg_id, False
    return None, None, None

async def start_bot():
    global bot_client
    bot = TelegramClient('bot_session', API_ID, API_HASH)
    
    try:
        await bot.start(bot_token=BOT_TOKEN)
        bot_client = bot
        me = await bot.get_me()
        logger.info(f"Bot connected! @{me.username} (ID: {me.id})")
    except Exception as e:
        logger.error(f"Failed to start: {e}")
        raise
    
    @bot.on(events.NewMessage(pattern='/ping'))
    async def ping_handler(event):
        logger.info(f"Ping from {event.sender_id}")
        try:
            await event.respond("🏓 Pong! Bot is alive and running.")
        except Exception as e:
            logger.error(f"Ping error: {e}")

    @bot.on(events.NewMessage(pattern='/start'))
    async def start_handler(event):
        logger.info(f"Start from {event.sender_id}")
        try:
            await event.respond("""🌟 **Welcome to Universal Channel Extractor Bot!**

**📋 Commands:**
/batch - Extract posts
/login - Login for private channels
/settings - Bot settings
/logout - Logout
/help - Detailed guide
/id - Get chat ID
/ping - Check bot status

**🚀 Quick Start:**

**PUBLIC channels:** Just use /batch
**PRIVATE channels:** First /login, then /batch

Type /help for complete guide!""")
            logger.info(f"Start response sent to {event.sender_id}")
        except Exception as e:
            logger.error(f"Start error: {e}")

    @bot.on(events.NewMessage(pattern='/help'))
    async def help_handler(event):
        logger.info(f"Help from {event.sender_id}")
        try:
            await event.respond("""📖 **Complete Guide**

**PUBLIC Channels:**
1. /batch
2. Paste post link
3. Enter count
4. Done! ✅

**PRIVATE Channels:**
1. /login (one time)
2. Enter phone: +919876543210
3. Enter OTP: 1 2 3 4 5
4. Then use /batch normally

**Auto-Post Setup:**
1. Add bot as admin in your channel
2. /id in that channel
3. /settings → Set Chat ID
4. Paste ID → Done!

**Important:**
⚠️ You must be joined in the channel
⚠️ Private channels need /login first
⚠️ Max 1000 posts per batch""")
        except Exception as e:
            logger.error(f"Help error: {e}")

    @bot.on(events.NewMessage(pattern='/login'))
    async def login_handler(event):
        user_id = event.sender_id
        logger.info(f"Login from {user_id}")
        try:
            if user_id in user_conversations:
                del user_conversations[user_id]
            await event.respond("""📱 **Login to Your Telegram Account**

⚠️ Use the SAME account with channel access!

Enter phone with country code:
✅ Example: +919876543210""")
            user_conversations[user_id] = {'step': 'phone', 'client': None}
        except Exception as e:
            logger.error(f"Login error: {e}")

    @bot.on(events.NewMessage(pattern='/logout'))
    async def logout_handler(event):
        user_id = event.sender_id
        try:
            if user_id in user_sessions:
                del user_sessions[user_id]
                await event.respond("👋 Logged out! Use /login to login again.")
            else:
                await event.respond("❌ You're not logged in.")
        except Exception as e:
            logger.error(f"Logout error: {e}")

    @bot.on(events.NewMessage(pattern='/batch'))
    async def batch_handler(event):
        user_id = event.sender_id
        logger.info(f"Batch from {user_id}")
        try:
            if active_extractions.get(user_id):
                await event.respond("⚠️ Extraction running! Use /cancel first.")
                return
            if user_id in user_conversations:
                del user_conversations[user_id]
            await event.respond("""📎 **Batch Extraction**

Send post link:

✅ **Public:** https://t.me/channelname/123
✅ **Private:** https://t.me/c/1234567890/123

💡 For private channels, use /login first!""")
            user_conversations[user_id] = {'step': 'link', 'data': {}}
        except Exception as e:
            logger.error(f"Batch error: {e}")

    @bot.on(events.NewMessage(pattern='/cancel'))
    async def cancel_handler(event):
        user_id = event.sender_id
        try:
            if active_extractions.get(user_id):
                active_extractions[user_id] = False
                await event.respond("✋ Extraction cancelled!")
            if user_id in user_conversations:
                del user_conversations[user_id]
                await event.respond("🔄 Operation cancelled!")
        except Exception as e:
            logger.error(f"Cancel error: {e}")

    @bot.on(events.NewMessage(pattern='/id'))
    async def id_handler(event):
        try:
            chat_id = event.chat_id
            user_id = event.sender_id
            chat_type = "Channel" if str(chat_id).startswith('-100') else "Group" if chat_id < 0 else "Private"
            await event.respond(f"""🆔 **Chat Information**

**Chat ID:** `{chat_id}`
**Your ID:** `{user_id}`
**Type:** {chat_type}

💡 Copy Chat ID for settings!""")
        except Exception as e:
            logger.error(f"ID error: {e}")

    @bot.on(events.NewMessage(pattern='/settings'))
    async def settings_handler(event):
        try:
            buttons = [
                [Button.inline("📍 Set Target Chat ID", b"set_chat_id")],
                [Button.inline("✏️ Replace Words", b"replace_words")],
                [Button.inline("🗑️ Remove Words", b"remove_words")],
                [Button.inline("💬 Custom Caption", b"custom_caption")],
                [Button.inline("📊 View Settings", b"view_settings")],
                [Button.inline("🔄 Reset Settings", b"reset_settings")]
            ]
            await event.respond("⚙️ **Settings Menu**", buttons=buttons)
        except Exception as e:
            logger.error(f"Settings error: {e}")

    @bot.on(events.NewMessage(incoming=True, func=lambda e: e.text and not e.text.startswith('/')))
    async def message_handler(event):
        user_id = event.sender_id
        if user_id not in user_conversations:
            return
        conv_data = user_conversations[user_id]
        step = conv_data.get('step')
        logger.info(f"Processing {step} for {user_id}")
        
        try:
            if step == 'phone':
                phone = event.text.strip()
                if not re.match(r'^\+\d{10,15}$', phone):
                    await event.respond("❌ Invalid format!\nExample: +919876543210")
                    return
                try:
                    user_client = TelegramClient(StringSession(), API_ID, API_HASH)
                    await user_client.connect()
                    await user_client.send_code_request(phone)
                    conv_data['client'] = user_client
                    conv_data['phone'] = phone
                    conv_data['step'] = 'otp'
                    await event.respond("✅ OTP Sent!\n\nEnter OTP: 1 2 3 4 5")
                except Exception as e:
                    logger.error(f"Phone error: {e}")
                    await event.respond(f"❌ Error: {str(e)}")
                    del user_conversations[user_id]
            
            elif step == 'otp':
                code = event.text.replace(' ', '').strip()
                if not code.isdigit() or len(code) < 5:
                    await event.respond("❌ Invalid OTP!")
                    return
                user_client = conv_data['client']
                phone = conv_data['phone']
                try:
                    await user_client.sign_in(phone, code)
                    session_string = user_client.session.save()
                    user_sessions[user_id] = session_string
                    logger.info(f"Login successful: {user_id}")
                    await event.respond("🎉 Login Successful!\n\n✅ Use /batch now!")
                    await user_client.disconnect()
                    del user_conversations[user_id]
                except SessionPasswordNeededError:
                    conv_data['step'] = 'password'
                    await event.respond("🔐 2FA detected\n\nEnter password:")
                except Exception as e:
                    logger.error(f"OTP error: {e}")
                    await event.respond(f"❌ Error: {str(e)}")
                    if user_client:
                        await user_client.disconnect()
                    del user_conversations[user_id]
            
            elif step == 'password':
                password = event.text.strip()
                user_client = conv_data['client']
                try:
                    await user_client.sign_in(password=password)
                    session_string = user_client.session.save()
                    user_sessions[user_id] = session_string
                    logger.info(f"2FA login successful: {user_id}")
                    await event.respond("🎉 Login Successful!")
                    await user_client.disconnect()
                    del user_conversations[user_id]
                except Exception as e:
                    logger.error(f"Password error: {e}")
                    await event.respond(f"❌ Wrong password!")
                    if user_client:
                        await user_client.disconnect()
                    del user_conversations[user_id]
            
            elif step == 'link':
                post_link = event.text.strip()
                channel_entity, start_msg_id, is_private = parse_channel_link(post_link)
                if not channel_entity or not start_msg_id:
                    await event.respond("❌ Invalid link!\n\n✅ Public: https://t.me/channel/123\n✅ Private: https://t.me/c/123/456")
                    return
                if is_private and user_id not in user_sessions:
                    await event.respond("⚠️ Private channel!\n\nUse /login first!")
                    del user_conversations[user_id]
                    return
                conv_data['data']['channel'] = channel_entity
                conv_data['data']['start_id'] = start_msg_id
                conv_data['data']['is_private'] = is_private
                conv_data['step'] = 'count'
                await event.respond(f"✅ Link valid!\n{'🔒 Private' if is_private else '🌐 Public'} Channel\n\n🔢 How many posts?\n\n💡 Max: 1000")
            
            elif step == 'count':
                try:
                    count = int(event.text.strip())
                    if count <= 0:
                        await event.respond("❌ Must be > 0!")
                        return
                    if count > 1000:
                        await event.respond("⚠️ Max 1000!")
                        return
                    channel_entity = conv_data['data']['channel']
                    start_msg_id = conv_data['data']['start_id']
                    is_private = conv_data['data']['is_private']
                    del user_conversations[user_id]
                    asyncio.create_task(extract_posts(bot, user_id, channel_entity, start_msg_id, count, is_private))
                except ValueError:
                    await event.respond("❌ Invalid number!")
            
            elif step == 'set_chat_id':
                try:
                    chat_id = int(event.text.strip())
                    settings = get_user_settings(user_id)
                    settings.target_chat_id = chat_id
                    await event.respond(f"✅ Target set: `{chat_id}`")
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
                await event.respond("✅ Caption set!")
                del user_conversations[user_id]
        
        except Exception as e:
            logger.error(f"Handler error: {e}", exc_info=True)
            await event.respond(f"❌ Error: {str(e)}")
            if user_id in user_conversations:
                del user_conversations[user_id]

    async def extract_posts(bot, user_id, channel_entity, start_msg_id, count, is_private):
        logger.info(f"Extraction started: {user_id}")
        temp_dir = None
        client = None
        
        try:
            active_extractions[user_id] = True
            temp_dir = tempfile.mkdtemp(prefix=f"tg_{user_id}_")
            logger.info(f"Temp dir: {temp_dir}")
            
            if is_private:
                if user_id not in user_sessions:
                    await bot.send_message(user_id, "❌ Login required!")
                    active_extractions[user_id] = False
                    return
                client = TelegramClient(StringSession(user_sessions[user_id]), API_ID, API_HASH)
                await client.connect()
                logger.info("Using user session")
                await bot.send_message(user_id, "✅ Using your account")
            else:
                client = bot
                logger.info("Using bot session")
                await bot.send_message(user_id, "ℹ️ Using bot account")
            
            try:
                await bot.send_message(user_id, "🔍 Testing access...")
                entity = await client.get_entity(channel_entity)
                logger.info(f"Got entity: {getattr(entity, 'title', entity)}")
                test_msgs = await client.get_messages(entity, limit=1)
                if not test_msgs:
                    raise ValueError("Cannot access")
                await bot.send_message(user_id, "✅ Access OK!")
            except Exception as e:
                await bot.send_message(user_id, f"❌ Cannot access!\n\nError: {str(e)}\n\nSolutions:\n• Join the channel\n• Use /login for private")
                active_extractions[user_id] = False
                if client != bot:
                    await client.disconnect()
                return
            
            settings = get_user_settings(user_id)
            target_chat = settings.target_chat_id or user_id
            
            if target_chat != user_id:
                try:
                    test = await bot.send_message(target_chat, "🧪 Test")
                    await test.delete()
                    await bot.send_message(user_id, f"✅ Target OK: {target_chat}")
                except Exception as e:
                    await bot.send_message(user_id, "❌ Cannot send to target!\n\nMake bot admin with post permission")
                    active_extractions[user_id] = False
                    if client != bot:
                        await client.disconnect()
                    return
            
            progress_msg = await bot.send_message(user_id, f"⚙️ Extracting {count} posts...\n⏳ Please wait...")
            
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
                    
                    caption = message.text or ""
                    for old, new in settings.replace_words.items():
                        caption = caption.replace(old, new)
                    for word in settings.remove_words:
                        caption = caption.replace(word, "")
                    if settings.custom_caption:
                        caption = f"{caption}\n\n{settings.custom_caption}" if caption else settings.custom_caption
                    if len(caption) > 1024:
                        caption = caption[:1021] + "..."
                    
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
                    
                    if extracted - last_update >= 5 or i == count - 1:
                        try:
                            progress = int((i + 1) / count * 100)
                            await progress_msg.edit(f"⚙️ Extracting...\n\n✅ Done: {extracted}/{count}\n❌ Failed: {failed}\n📊 {progress}%")
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
            
            active_extractions[user_id] = False
            success_rate = int((extracted / count) * 100) if count > 0 else 0
            await bot.send_message(user_id, f"🎉 Complete!\n\n✅ Extracted: {extracted}\n❌ Failed: {failed}\n📊 Total: {count}\n📈 Success: {success_rate}%\n\n{'🌟 Perfect!' if success_rate >= 90 else '💡 Some missing' if success_rate > 0 else '❌ None extracted'}")
        
        except Exception as e:
            active_extractions[user_id] = False
            logger.error(f"Fatal error: {e}", exc_info=True)
            await bot.send_message(user_id, f"❌ Fatal error: {str(e)}")
        
        finally:
            if client and client != bot:
                try:
                    await client.disconnect()
                except:
                    pass
            if temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                    logger.info(f"Cleaned: {temp_dir}")
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
            elif data == "view_settings":
                settings = get_user_settings(user_id)
                target = f"`{settings.target_chat_id}`" if settings.target_chat_id else "DM"
                caption = (settings.custom_caption[:50] + "...") if settings.custom_caption else "None"
                await event.respond(f"📊 Settings\n\n📍 Target: {target}\n💬 Caption: {caption}\n✏️ Replacements: {len(settings.replace_words)}\n🗑️ Removals: {len(settings.remove_words)}")
            elif data == "reset_settings":
                user_settings[user_id] = UserSettings()
                await event.respond("🔄 Reset!")
        except Exception as e:
            logger.error(f"Callback error: {e}")

    logger.info("Bot running and listening!")
    
    try:
        await bot.run_until_disconnected()
    except KeyboardInterrupt:
        logger.info("Stopped by user")
    except Exception as e:
        logger.error(f"Run error: {e}", exc_info=True)
    finally:
        await bot.disconnect()

def signal_handler(signum, frame):
    logger.info("Shutdown signal received")
    sys.exit(0)

async def main():
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        keep_alive()
        await asyncio.sleep(2)
        logger.info("Starting Telegram bot...")
        await start_bot()
    except KeyboardInterrupt:
        logger.info("Stopped")
    except Exception as e:
        logger.error(f"Fatal: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("🤖 TELEGRAM CHANNEL EXTRACTOR BOT")
    logger.info("=" * 60)
    logger.info(f"API_ID: {'✅' if API_ID else '❌'}")
    logger.info(f"API_HASH: {'✅' if API_HASH else '❌'}")
    logger.info(f"BOT_TOKEN: {'✅' if BOT_TOKEN else '❌'}")
    logger.info(f"PORT: {PORT}")
    logger.info("=" * 60)
    
    if not all([API_ID, API_HASH, BOT_TOKEN]):
        logger.error("Missing environment variables!")
        sys.exit(1)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopped by user!")
    except Exception as e:
        logger.error(f"Failed: {e}", exc_info=True)
        sys.exit(1)
