import os
import re
import asyncio
from telethon import TelegramClient, events, Button
from telethon.tl.types import DocumentAttributeFilename
from telethon.sessions import StringSession
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Environment variables
API_ID = int(os.environ.get('API_ID', '0'))
API_HASH = os.environ.get('API_HASH', '')
BOT_TOKEN = os.environ.get('BOT_TOKEN', '')

# Initialize bot
bot = TelegramClient('bot_session', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# User data storage
user_sessions = {}
user_settings = {}
active_extractions = {}

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

@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    user_id = event.sender_id
    welcome_msg = """
🌟 **Welcome to Advanced Channel Extractor Bot!** 🌟

Main tumhare liye posts extract kar sakta hoon kisi bhi public ya private Telegram channel se!

**Available Commands:**
/batch - Extract multiple posts
/login - Login for private channels
/settings - Customize extraction settings
/cancel - Cancel ongoing extraction
/logout - Logout from current session
/help - Detailed help

**Features:**
✅ Extract from public & private channels
✅ Batch extraction (up to 1000 posts)
✅ Custom captions & thumbnails
✅ Word replacement
✅ Direct posting to your channel
✅ Bypass forwarding restrictions

Shuru karne ke liye /batch use karo!
"""
    await event.respond(welcome_msg)

@bot.on(events.NewMessage(pattern='/help'))
async def help_handler(event):
    help_text = """
📖 **Detailed Help Guide**

**1. Extract from Public Channel:**
   - Copy post link from channel
   - Send /batch
   - Paste link
   - Enter number of posts

**2. Extract from Private Channel:**
   - First use /login
   - Enter phone number with country code
   - Enter OTP (space-separated)
   - Enter password if 2FA enabled
   - Then use /batch

**3. Post to Your Channel:**
   - Add bot as admin in your channel
   - Get channel ID using /id in channel
   - Use /settings → Set Chat ID
   - Paste channel ID

**4. Customization:**
   - /settings → Replace Words
   - /settings → Custom Caption
   - /settings → Set Thumbnail

Need more help? Just ask!
"""
    await event.respond(help_text)

@bot.on(events.NewMessage(pattern='/login'))
async def login_handler(event):
    user_id = event.sender_id
    
    await event.respond("📱 **Login Process Started**\n\nPhone number enter karo (with country code):\nExample: +919876543210")
    
    # Wait for phone number
    async with bot.conversation(user_id, timeout=120) as conv:
        try:
            phone_response = await conv.get_response()
            phone = phone_response.text.strip()
            
            # Create user client
            user_client = TelegramClient(StringSession(), API_ID, API_HASH)
            await user_client.connect()
            
            await user_client.send_code_request(phone)
            await event.respond("✅ Code sent!\n\nOTP enter karo (space-separated digits):\nExample: 1 2 3 4 5")
            
            otp_response = await conv.get_response()
            code = otp_response.text.replace(' ', '').strip()
            
            try:
                await user_client.sign_in(phone, code)
                session_string = user_client.session.save()
                user_sessions[user_id] = session_string
                await event.respond("🎉 **Login Successful!**\n\nAb tum private channels se bhi extract kar sakte ho!")
                
            except Exception as e:
                if 'password' in str(e).lower() or 'SessionPasswordNeededError' in str(type(e).__name__):
                    await event.respond("🔐 Two-step verification detected!\n\nPassword enter karo:")
                    pwd_response = await conv.get_response()
                    password = pwd_response.text.strip()
                    await user_client.sign_in(password=password)
                    session_string = user_client.session.save()
                    user_sessions[user_id] = session_string
                    await event.respond("🎉 **Login Successful with 2FA!**")
                else:
                    raise e
                    
        except asyncio.TimeoutError:
            await event.respond("⏱️ Timeout! Please try /login again.")
        except Exception as e:
            await event.respond(f"❌ Login failed: {str(e)}\n\nPlease try again with /login")

@bot.on(events.NewMessage(pattern='/logout'))
async def logout_handler(event):
    user_id = event.sender_id
    if user_id in user_sessions:
        del user_sessions[user_id]
        await event.respond("👋 Logged out successfully!")
    else:
        await event.respond("You're not logged in.")

@bot.on(events.NewMessage(pattern='/batch'))
async def batch_handler(event):
    user_id = event.sender_id
    
    # Check if extraction is already running
    if user_id in active_extractions and active_extractions[user_id]:
        await event.respond("⚠️ Extraction already running! Use /cancel to stop it first.")
        return
    
    await event.respond("📎 **Batch Extraction Started**\n\nPost link paste karo:")
    
    async with bot.conversation(user_id, timeout=300) as conv:
        try:
            link_response = await conv.get_response()
            post_link = link_response.text.strip()
            
            # Parse link
            match = re.search(r't\.me/([^/]+)/(\d+)', post_link)
            if not match:
                await event.respond("❌ Invalid link! Example: https://t.me/channel_name/123")
                return
            
            channel_username = match.group(1)
            start_msg_id = int(match.group(2))
            
            await event.respond("🔢 Kitne posts extract karne hain? (Max 1000)")
            count_response = await conv.get_response()
            count = min(int(count_response.text.strip()), 1000)
            
            active_extractions[user_id] = True
            await event.respond(f"⚙️ Starting extraction of {count} posts...\n\n⏳ Please wait...")
            
            # Get client
            if user_id in user_sessions:
                client = TelegramClient(StringSession(user_sessions[user_id]), API_ID, API_HASH)
                await client.connect()
            else:
                client = bot
            
            settings = get_user_settings(user_id)
            target_chat = settings.target_chat_id or user_id
            
            # Extract posts
            extracted = 0
            failed = 0
            
            for i in range(count):
                if not active_extractions.get(user_id):
                    await event.respond("❌ Extraction cancelled!")
                    break
                
                msg_id = start_msg_id + i
                
                try:
                    message = await client.get_messages(channel_username, ids=msg_id)
                    
                    if message and not message.empty:
                        # Process caption
                        caption = message.text or ""
                        
                        # Apply word replacements
                        for old_word, new_word in settings.replace_words.items():
                            caption = caption.replace(old_word, new_word)
                        
                        # Remove words
                        for word in settings.remove_words:
                            caption = caption.replace(word, "")
                        
                        # Add custom caption
                        if settings.custom_caption:
                            caption = f"{caption}\n\n{settings.custom_caption}" if caption else settings.custom_caption
                        
                        # Send message
                        if message.media:
                            await bot.send_file(
                                target_chat,
                                message.media,
                                caption=caption[:1024] if caption else None,
                                thumb=settings.thumbnail,
                                force_document=False
                            )
                        else:
                            await bot.send_message(target_chat, caption or "Empty post")
                        
                        extracted += 1
                        
                        # Progress update every 10 posts
                        if extracted % 10 == 0:
                            await event.respond(f"✅ Extracted: {extracted}/{count}")
                        
                        await asyncio.sleep(0.5)  # Rate limiting
                        
                except Exception as e:
                    failed += 1
                    logger.error(f"Error extracting message {msg_id}: {e}")
                    continue
            
            active_extractions[user_id] = False
            await event.respond(f"🎉 **Extraction Complete!**\n\n✅ Extracted: {extracted}\n❌ Failed: {failed}")
            
            if user_id in user_sessions:
                await client.disconnect()
                
        except asyncio.TimeoutError:
            active_extractions[user_id] = False
            await event.respond("⏱️ Timeout! Please try again.")
        except Exception as e:
            active_extractions[user_id] = False
            await event.respond(f"❌ Error: {str(e)}")

@bot.on(events.NewMessage(pattern='/cancel'))
async def cancel_handler(event):
    user_id = event.sender_id
    if user_id in active_extractions:
        active_extractions[user_id] = False
        await event.respond("✋ Extraction process cancelled!")
    else:
        await event.respond("No active extraction found.")

@bot.on(events.NewMessage(pattern='/id'))
async def id_handler(event):
    chat_id = event.chat_id
    await event.respond(f"**Chat ID:** `{chat_id}`\n\nCopy this ID for settings!")

@bot.on(events.NewMessage(pattern='/settings'))
async def settings_handler(event):
    buttons = [
        [Button.inline("📍 Set Chat ID", b"set_chat_id")],
        [Button.inline("✏️ Replace Words", b"replace_words")],
        [Button.inline("🗑️ Remove Words", b"remove_words")],
        [Button.inline("💬 Custom Caption", b"custom_caption")],
        [Button.inline("🖼️ Set Thumbnail", b"set_thumbnail")],
        [Button.inline("🔄 Reset All", b"reset_settings")]
    ]
    await event.respond("⚙️ **Settings Menu**\n\nChoose an option:", buttons=buttons)

@bot.on(events.CallbackQuery)
async def callback_handler(event):
    user_id = event.sender_id
    data = event.data.decode()
    settings = get_user_settings(user_id)
    
    if data == "set_chat_id":
        await event.respond("📍 **Set Target Chat ID**\n\nChannel ID paste karo (use /id in your channel to get it):")
        async with bot.conversation(user_id, timeout=60) as conv:
            response = await conv.get_response()
            chat_id = int(response.text.strip())
            settings.target_chat_id = chat_id
            await event.respond(f"✅ Target chat set to: {chat_id}")
    
    elif data == "replace_words":
        await event.respond("✏️ **Replace Words**\n\nFormat: old_word | new_word\nExample: Harshit | MyBot")
        async with bot.conversation(user_id, timeout=60) as conv:
            response = await conv.get_response()
            parts = response.text.split('|')
            if len(parts) == 2:
                old_word = parts[0].strip()
                new_word = parts[1].strip()
                settings.replace_words[old_word] = new_word
                await event.respond(f"✅ Will replace '{old_word}' with '{new_word}'")
    
    elif data == "remove_words":
        await event.respond("🗑️ **Remove Words**\n\nWord enter karo jo remove karna hai:")
        async with bot.conversation(user_id, timeout=60) as conv:
            response = await conv.get_response()
            word = response.text.strip()
            settings.remove_words.append(word)
            await event.respond(f"✅ Will remove: {word}")
    
    elif data == "custom_caption":
        await event.respond("💬 **Custom Caption**\n\nCaption text bhejo:")
        async with bot.conversation(user_id, timeout=60) as conv:
            response = await conv.get_response()
            settings.custom_caption = response.text
            await event.respond("✅ Custom caption set!")
    
    elif data == "set_thumbnail":
        await event.respond("🖼️ **Set Thumbnail**\n\nThumbnail image bhejo:")
        async with bot.conversation(user_id, timeout=60) as conv:
            response = await conv.get_response()
            if response.photo:
                settings.thumbnail = response.photo
                await event.respond("✅ Thumbnail set!")
            else:
                await event.respond("❌ Please send an image!")
    
    elif data == "reset_settings":
        user_settings[user_id] = UserSettings()
        await event.respond("🔄 All settings reset!")

# Keep the bot running
if __name__ == "__main__":
    logger.info("Bot started!")
    bot.run_until_disconnected()
