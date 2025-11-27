import os
import re
import asyncio
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError, 
    PhoneCodeInvalidError, 
    PhoneNumberInvalidError, 
    ChannelPrivateError,
    ChatWriteForbiddenError
)
from aiohttp import web
import logging
from typing import Dict, List, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Environment variables
API_ID = int(os.environ.get('API_ID', '20598098'))
API_HASH = os.environ.get('API_HASH', 'c1727e40f8585b869cef73b828b2bf69')
BOT_TOKEN = os.environ.get('BOT_TOKEN', '8481545345:AAEIB3zKphtr29h0232hykXuG_qIRllk1aQ')
PORT = int(os.environ.get('PORT', '8080'))

# Global storage
user_sessions: Dict[int, str] = {}
user_settings: Dict[int, 'UserSettings'] = {}
active_extractions: Dict[int, bool] = {}
user_conversations: Dict[int, dict] = {}

class UserSettings:
    """User settings storage"""
    def __init__(self):
        self.target_chat_id: Optional[int] = None
        self.custom_caption: Optional[str] = None
        self.thumbnail = None
        self.replace_words: Dict[str, str] = {}
        self.remove_words: List[str] = []

def get_user_settings(user_id: int) -> UserSettings:
    """Get or create user settings"""
    if user_id not in user_settings:
        user_settings[user_id] = UserSettings()
    return user_settings[user_id]

def parse_channel_link(link: str):
    """Parse channel link and return entity, message ID, and type"""
    link = link.strip()
    
    # Pattern 1: t.me/c/CHANNEL_ID/MSG_ID (private channel)
    match = re.search(r't\.me/c/(\d+)/(\d+)', link)
    if match:
        channel_id = int(match.group(1))
        # Correct conversion: -100 + channel_id
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

# Health check server for deployment
async def health_check(request):
    return web.Response(text="Bot is running! ✅")

async def create_web_server():
    """Create health check server"""
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"Health check server running on port {PORT}")

async def start_bot():
    """Initialize and start the bot"""
    bot = TelegramClient('bot_session', API_ID, API_HASH)
    await bot.start(bot_token=BOT_TOKEN)
    logger.info("Bot connected successfully!")
    
    # ==================== COMMAND HANDLERS ====================
    
    @bot.on(events.NewMessage(pattern='/start'))
    async def start_handler(event):
        """Welcome message"""
        welcome = """
🌟 **Welcome to Universal Channel Extractor Bot!** 🌟

Main **PUBLIC aur PRIVATE** dono channels se posts extract kar sakta hoon!

**📋 Main Commands:**
/batch - Extract posts from channel
/login - Login for private channels
/settings - Customize extraction settings
/logout - Logout from session
/cancel - Cancel ongoing extraction
/help - Detailed help guide
/id - Get chat/channel ID

**🚀 Quick Start:**

**For PUBLIC channels:**
1. /batch
2. Paste channel post link
3. Enter number of posts
4. Done! ✅

**For PRIVATE channels:**
1. First /login (one time)
2. Then /batch with private link
3. Done! ✅

Type /help for detailed guide!
"""
        await event.respond(welcome)
    
    @bot.on(events.NewMessage(pattern='/help'))
    async def help_handler(event):
        """Help guide"""
        help_text = """
📖 **Complete Bot Guide**

**1️⃣ Extract from PUBLIC Channel:**
   • No login needed!
   • Use /batch command
   • Paste public channel post link
   • Enter number of posts (max 1000)
   • Bot extracts instantly ✨

**2️⃣ Extract from PRIVATE Channel:**
   • First time: Use /login
     - Enter phone: +919876543210
     - Enter OTP with spaces: 1 2 3 4 5
     - If 2FA enabled: Enter password
   
   • After login: Use /batch normally
     - Works for ALL private channels you're joined in
     - Login once, use forever!

**3️⃣ Auto-Post to Your Channel:**
   • Add bot as admin in your target channel
   • Use /id command in that channel
   • Copy the channel ID
   • /settings → Set Chat ID
   • Paste the ID
   • Now all posts go there directly! 🎯

**4️⃣ Customization Options:**
   • **Replace Words** - Change specific text in captions
   • **Custom Caption** - Add your own caption to all posts
   • **Set Thumbnail** - Custom thumbnail for videos/documents
   • **Remove Words** - Delete unwanted text from captions

**⚙️ Advanced Features:**
   • Batch extraction up to 1000 posts
   • Works even if forwarding is disabled
   • Preserves media quality
   • Handles all media types (video, photo, document, audio)
   • Progress tracking during extraction

**⚠️ Important Notes:**
   • You must be MEMBER of the channel
   • For private channels: /login is MANDATORY
   • Bot must be ADMIN in target channel for auto-posting
   • Rate limit: 0.5 seconds between posts

**💡 Pro Tips:**
   • Test with 1-2 posts first
   • Use custom captions for branding
   • Replace words to remove unwanted tags
   • Set thumbnail for professional look

Need more help? Just ask! 😊
"""
        await event.respond(help_text)
    
    @bot.on(events.NewMessage(pattern='/login'))
    async def login_handler(event):
        """Login flow initiation"""
        user_id = event.sender_id
        
        if user_id in user_conversations:
            del user_conversations[user_id]
        
        await event.respond(
            "📱 **Login to Your Telegram Account**\n\n"
            "⚠️ **IMPORTANT:** Use the account that has access to private channels!\n\n"
            "Enter phone number with country code:\n"
            "✅ Example: +919876543210\n\n"
            "🔒 Your credentials are secure and only used for extraction."
        )
        
        user_conversations[user_id] = {'step': 'phone', 'client': None}
    
    @bot.on(events.NewMessage(pattern='/logout'))
    async def logout_handler(event):
        """Logout from session"""
        user_id = event.sender_id
        if user_id in user_sessions:
            del user_sessions[user_id]
            await event.respond(
                "👋 **Logged Out Successfully!**\n\n"
                "Your session has been removed.\n"
                "You can login again anytime with /login"
            )
        else:
            await event.respond("❌ You're not logged in.")
    
    @bot.on(events.NewMessage(pattern='/batch'))
    async def batch_handler(event):
        """Batch extraction initiation"""
        user_id = event.sender_id
        
        if active_extractions.get(user_id):
            await event.respond(
                "⚠️ **Extraction Already Running!**\n\n"
                "Please wait for current extraction to finish.\n"
                "Use /cancel to stop it."
            )
            return
        
        if user_id in user_conversations:
            del user_conversations[user_id]
        
        await event.respond(
            "📎 **Batch Extraction**\n\n"
            "Send me the post link:\n\n"
            "✅ **Public channel example:**\n"
            "https://t.me/channelname/123\n\n"
            "✅ **Private channel example:**\n"
            "https://t.me/c/1234567890/123\n\n"
            "💡 **Tip:** For private channels, make sure you've used /login first!"
        )
        
        user_conversations[user_id] = {'step': 'link', 'data': {}}
    
    @bot.on(events.NewMessage(pattern='/cancel'))
    async def cancel_handler(event):
        """Cancel ongoing operations"""
        user_id = event.sender_id
        cancelled = False
        
        if active_extractions.get(user_id):
            active_extractions[user_id] = False
            await event.respond("✋ **Extraction Cancelled!**\n\nYou can start a new one with /batch")
            cancelled = True
        
        if user_id in user_conversations:
            del user_conversations[user_id]
            if not cancelled:
                await event.respond("🔄 **Current operation cancelled!**")
    
    @bot.on(events.NewMessage(pattern='/id'))
    async def id_handler(event):
        """Get chat/channel ID"""
        chat_id = event.chat_id
        user_id = event.sender_id
        
        if str(chat_id).startswith('-100'):
            chat_type = "📢 Channel"
        elif chat_id < 0:
            chat_type = "👥 Group"
        else:
            chat_type = "💬 Private Chat"
        
        await event.respond(
            f"🆔 **Chat Information**\n\n"
            f"**Chat ID:** `{chat_id}`\n"
            f"**Your User ID:** `{user_id}`\n"
            f"**Type:** {chat_type}\n\n"
            f"💡 Copy the Chat ID above to use in /settings"
        )
    
    @bot.on(events.NewMessage(pattern='/settings'))
    async def settings_handler(event):
        """Settings menu"""
        buttons = [
            [Button.inline("📍 Set Target Chat ID", b"set_chat_id")],
            [Button.inline("✏️ Replace Words", b"replace_words")],
            [Button.inline("🗑️ Remove Words", b"remove_words")],
            [Button.inline("💬 Custom Caption", b"custom_caption")],
            [Button.inline("🖼️ Set Thumbnail", b"set_thumbnail")],
            [Button.inline("📊 View Settings", b"view_settings")],
            [Button.inline("🔄 Reset All Settings", b"reset_settings")]
        ]
        await event.respond(
            "⚙️ **Settings Menu**\n\n"
            "Choose an option to customize your extraction:",
            buttons=buttons
        )
    
    @bot.on(events.NewMessage(pattern='/session'))
    async def session_handler(event):
        """Export session string (for debugging)"""
        user_id = event.sender_id
        if user_id in user_sessions:
            session_str = user_sessions[user_id]
            await event.respond(
                f"🔑 **Your Session String**\n\n"
                f"Preview: `{session_str[:50]}...`\n\n"
                f"⚠️ **SECURITY WARNING:**\n"
                f"Keep this private! Anyone with this can access your account.\n\n"
                f"Full session (for debug purposes only):\n"
                f"`{session_str}`"
            )
        else:
            await event.respond("❌ You're not logged in. Use /login first.")
    
    # ==================== MESSAGE HANDLER ====================
    
    @bot.on(events.NewMessage(incoming=True, func=lambda e: not e.text.startswith('/')))
    async def message_handler(event):
        """Handle all non-command messages"""
        user_id = event.sender_id
        
        if user_id not in user_conversations:
            return
        
        conv_data = user_conversations[user_id]
        step = conv_data.get('step')
        
        try:
            # ===== LOGIN FLOW =====
            if step == 'phone':
                phone = event.text.strip()
                
                if not re.match(r'^\+\d{10,15}$', phone):
                    await event.respond(
                        "❌ **Invalid Phone Format!**\n\n"
                        "Format: +[country_code][phone_number]\n"
                        "Example: +919876543210\n\n"
                        "Try again:"
                    )
                    return
                
                try:
                    user_client = TelegramClient(StringSession(), API_ID, API_HASH)
                    await user_client.connect()
                    await user_client.send_code_request(phone)
                    
                    conv_data['client'] = user_client
                    conv_data['phone'] = phone
                    conv_data['step'] = 'otp'
                    
                    await event.respond(
                        "✅ **OTP Sent!**\n\n"
                        "Enter OTP with spaces between digits:\n"
                        "✅ Example: 1 2 3 4 5"
                    )
                    
                except Exception as e:
                    logger.error(f"Phone error: {e}")
                    await event.respond(
                        f"❌ **Error Sending OTP**\n\n"
                        f"{str(e)}\n\n"
                        f"Please try /login again"
                    )
                    del user_conversations[user_id]
            
            elif step == 'otp':
                code = event.text.replace(' ', '').strip()
                
                if not code.isdigit() or len(code) < 5:
                    await event.respond(
                        "❌ **Invalid OTP Format!**\n\n"
                        "Enter 5-digit code with spaces:\n"
                        "Example: 1 2 3 4 5"
                    )
                    return
                
                user_client = conv_data['client']
                phone = conv_data['phone']
                
                try:
                    await user_client.sign_in(phone, code)
                    session_string = user_client.session.save()
                    user_sessions[user_id] = session_string
                    
                    await event.respond(
                        "🎉 **Login Successful!**\n\n"
                        "✅ You can now extract from private channels!\n"
                        "✅ Your session is saved for future use\n\n"
                        "Use /batch to start extraction!"
                    )
                    await user_client.disconnect()
                    del user_conversations[user_id]
                    
                except SessionPasswordNeededError:
                    conv_data['step'] = 'password'
                    await event.respond(
                        "🔐 **Two-Step Verification Detected**\n\n"
                        "Enter your 2FA password:"
                    )
                    
                except PhoneCodeInvalidError:
                    await event.respond(
                        "❌ **Invalid OTP!**\n\n"
                        "Please check and try again:"
                    )
                    
                except Exception as e:
                    logger.error(f"OTP error: {e}")
                    await event.respond(
                        f"❌ **Login Failed**\n\n"
                        f"{str(e)}\n\n"
                        f"Try /login again"
                    )
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
                    
                    await event.respond(
                        "🎉 **Login Successful!**\n\n"
                        "✅ You can now extract from private channels!\n"
                        "✅ 2FA password saved securely\n\n"
                        "Use /batch to start extraction!"
                    )
                    await user_client.disconnect()
                    del user_conversations[user_id]
                    
                except Exception as e:
                    logger.error(f"Password error: {e}")
                    await event.respond(
                        f"❌ **Wrong Password!**\n\n"
                        f"{str(e)}\n\n"
                        f"Try /login again"
                    )
                    if user_client:
                        await user_client.disconnect()
                    del user_conversations[user_id]
            
            # ===== BATCH EXTRACTION FLOW =====
            elif step == 'link':
                post_link = event.text.strip()
                
                channel_entity, start_msg_id, is_private = parse_channel_link(post_link)
                
                if not channel_entity or not start_msg_id:
                    await event.respond(
                        "❌ **Invalid Link Format!**\n\n"
                        "Valid formats:\n"
                        "✅ Public: https://t.me/channelname/123\n"
                        "✅ Private: https://t.me/c/1234567890/123\n\n"
                        "Try again:"
                    )
                    return
                
                # Check login requirement for private channels
                if is_private and user_id not in user_sessions:
                    await event.respond(
                        "⚠️ **Private Channel Detected!**\n\n"
                        "❌ You haven't logged in yet.\n\n"
                        "Steps:\n"
                        "1. Use /login command\n"
                        "2. Complete login process\n"
                        "3. Come back and use /batch again\n\n"
                        "Operation cancelled."
                    )
                    del user_conversations[user_id]
                    return
                
                conv_data['data']['channel'] = channel_entity
                conv_data['data']['start_id'] = start_msg_id
                conv_data['data']['is_private'] = is_private
                conv_data['step'] = 'count'
                
                channel_type = "🔒 Private" if is_private else "🌐 Public"
                await event.respond(
                    f"✅ **Link Validated!**\n"
                    f"Type: {channel_type} Channel\n\n"
                    f"🔢 **How many posts to extract?**\n\n"
                    f"✅ Maximum: 1000 posts\n"
                    f"💡 Recommended: 10-50 for testing\n\n"
                    f"Enter number:"
                )
            
            elif step == 'count':
                try:
                    count = int(event.text.strip())
                    
                    if count <= 0:
                        await event.respond("❌ Count must be greater than 0. Try again:")
                        return
                    
                    if count > 1000:
                        await event.respond("⚠️ Maximum 1000 posts allowed. Enter again:")
                        return
                    
                    channel_entity = conv_data['data']['channel']
                    start_msg_id = conv_data['data']['start_id']
                    is_private = conv_data['data']['is_private']
                    
                    del user_conversations[user_id]
                    
                    # Start extraction
                    await extract_posts(bot, user_id, channel_entity, start_msg_id, count, is_private)
                    
                except ValueError:
                    await event.respond("❌ Invalid number! Enter a valid number:")
            
            # ===== SETTINGS FLOWS =====
            elif step == 'set_chat_id':
                try:
                    chat_id = int(event.text.strip())
                    settings = get_user_settings(user_id)
                    settings.target_chat_id = chat_id
                    await event.respond(
                        f"✅ **Target Chat Set Successfully!**\n\n"
                        f"Chat ID: `{chat_id}`\n\n"
                        f"All extracted posts will now be sent there directly.\n"
                        f"Make sure bot is admin in that channel!"
                    )
                    del user_conversations[user_id]
                except ValueError:
                    await event.respond("❌ Invalid ID! Must be a number. Try again:")
            
            elif step == 'replace_words':
                parts = event.text.split('|')
                if len(parts) == 2:
                    old_word = parts[0].strip()
                    new_word = parts[1].strip()
                    settings = get_user_settings(user_id)
                    settings.replace_words[old_word] = new_word
                    await event.respond(
                        f"✅ **Word Replacement Added!**\n\n"
                        f"'{old_word}' → '{new_word}'\n\n"
                        f"This will apply to all future extractions."
                    )
                    del user_conversations[user_id]
                else:
                    await event.respond(
                        "❌ Invalid format!\n\n"
                        "Use: old_word | new_word\n"
                        "Example: Harshit | MyBot\n\n"
                        "Try again:"
                    )
            
            elif step == 'remove_words':
                word = event.text.strip()
                if word:
                    settings = get_user_settings(user_id)
                    settings.remove_words.append(word)
                    await event.respond(
                        f"✅ **Word Added to Removal List!**\n\n"
                        f"Will remove: '{word}'\n\n"
                        f"This will apply to all future extractions."
                    )
                    del user_conversations[user_id]
                else:
                    await event.respond("❌ Please enter a valid word:")
            
            elif step == 'custom_caption':
                settings = get_user_settings(user_id)
                settings.custom_caption = event.text
                caption_preview = event.text[:100] + "..." if len(event.text) > 100 else event.text
                await event.respond(
                    f"✅ **Custom Caption Set!**\n\n"
                    f"Preview:\n{caption_preview}\n\n"
                    f"This will be added to all extracted posts."
                )
                del user_conversations[user_id]
            
            elif step == 'set_thumbnail':
                if event.photo or event.document:
                    settings = get_user_settings(user_id)
                    settings.thumbnail = event.photo or event.document
                    await event.respond(
                        "✅ **Thumbnail Set Successfully!**\n\n"
                        "This thumbnail will be used for all videos and documents."
                    )
                    del user_conversations[user_id]
                else:
                    await event.respond("❌ Please send an image file:")
        
        except Exception as e:
            logger.error(f"Message handler error: {e}")
            await event.respond(
                f"❌ **Error Occurred**\n\n"
                f"{str(e)}\n\n"
                f"Operation cancelled. Please try again."
            )
            if user_id in user_conversations:
                del user_conversations[user_id]
    
    # ==================== EXTRACTION LOGIC ====================
    
    async def extract_posts(bot, user_id, channel_entity, start_msg_id, count, is_private):
        """Main extraction logic with complete error handling"""
        try:
            active_extractions[user_id] = True
            
            # CRITICAL: For private channels, MUST use user session
            if is_private:
                if user_id not in user_sessions:
                    await bot.send_message(
                        user_id,
                        "❌ **Private Channel - Login Required!**\n\n"
                        "You must login first to access private channels.\n\n"
                        "Use /login command and try again!"
                    )
                    active_extractions[user_id] = False
                    return
                
                client = TelegramClient(StringSession(user_sessions[user_id]), API_ID, API_HASH)
                await client.connect()
                logger.info(f"User {user_id} using logged-in session")
                await bot.send_message(user_id, "✅ Using your logged-in account")
            else:
                client = bot
                logger.info(f"User {user_id} using bot session")
                await bot.send_message(user_id, "ℹ️ Using bot account for public channel")
            
            # Test channel access
            try:
                await bot.send_message(user_id, "🔍 Testing channel access...")
                test_msg = await client.get_messages(channel_entity, limit=1)
                
                if not test_msg or len(test_msg) == 0:
                    raise ValueError("Cannot access channel - check if it exists and you're a member")
                
                await bot.send_message(user_id, "✅ Channel access verified! Starting extraction...")
                
            except ChannelPrivateError:
                await bot.send_message(
                    user_id,
                    "❌ **Private Channel - No Access!**\n\n"
                    "Solutions:\n"
                    "1. Make sure you've joined the channel\n"
                    "2. Use /login with the account that's joined\n"
                    "3. Try /batch again"
                )
                active_extractions[user_id] = False
                if client != bot:
                    await client.disconnect()
                return
            
            except Exception as e:
                await bot.send_message(
                    user_id,
                    f"❌ **Cannot Access Channel!**\n\n"
                    f"Error: {str(e)}\n\n"
                    f"Possible reasons:\n"
                    f"• Channel doesn't exist\n"
                    f"• You're not a member\n"
                    f"• For private channels: Use /login first"
                )
                active_extractions[user_id] = False
                if client != bot:
                    await client.disconnect()
                return
            
            # Get settings
            settings = get_user_settings(user_id)
            target_chat = settings.target_chat_id or user_id
            
            # Test target chat permissions
            if target_chat != user_id:
                try:
                    test_msg = await bot.send_message(target_chat, "🧪 Testing permissions...")
                    await test_msg.delete()
                    await bot.send_message(user_id, f"✅ Target channel accessible")
                except Exception as perm_err:
                    await bot.send_message(
                        user_id,
                        f"❌ **Cannot Send to Target Channel!**\n\n"
                        f"Target: `{target_chat}`\n"
                        f"Error: {str(perm_err)}\n\n"
                        f"Solutions:\n"
                        f"• Add bot as ADMIN in that channel\n"
                        f"• Enable 'Post Messages' permission\n"
                        f"• Or use /settings to reset target (posts will come to DM)"
                    )
                    active_extractions[user_id] = False
                    if client != bot:
                        await client.disconnect()
                    return
            
            # Start extraction
            progress_msg = await bot.send_message(
                user_id,
                f"⚙️ **Extraction Started**\n\n"
                f"📊 Total Posts: {count}\n"
                f"🎯 Target: {'Your DM' if target_chat == user_id else 'Target Channel'}\n"
                f"⏳ Please wait...\n\n"
                f"This may take a few minutes for large batches."
            )
            
            extracted = 0
            failed = 0
            last_update = 0
            
            for i in range(count):
                # Check cancellation
                if not active_extractions.get(user_id):
                    await bot.send_message(user_id, "❌ **Extraction Cancelled by User!**")
                    break
                
                msg_id = start_msg_id + i
                
                try:
                    # Fetch message
                    message = await client.get_messages(channel_entity, ids=msg_id)
                    
                    # Handle different response types
                    if message is None:
                        logger.warning(f"Message {msg_id} is None")
                        failed += 1
                        continue
                    
                    if isinstance(message, list):
                        if len(message) == 0 or message[0] is None:
                            logger.warning(f"Message {msg_id} list is empty")
                            failed += 1
                            continue
                        message = message[0]
                    
                    # Check if message has content
                    if not message.text and not message.media:
                        logger.warning(f"Message {msg_id} has no content")
                        failed += 1
                        continue
                    
                    # Process caption
                    caption = message.text or ""
                    
                    # Apply word replacements
                    for old_word, new_word in settings.replace_words.items():
                        caption = caption.replace(old_word, new_word)
                    
                    # Remove unwanted words
                    for word in settings.remove_words:
                        caption = caption.replace(word, "")
                    
                    # Add custom caption
                    if settings.custom_caption:
                        if caption:
                            caption = f"{caption}\n\n{settings.custom_caption}"
                        else:
                            caption = settings.custom_caption
                    
                    # Send message with multiple fallback methods
                    sent_successfully = False
                    
                    try:
                        if message.media:
                            # Method 1: Try direct file send
                            try:
                                await bot.send_file(
                                    target_chat,
                                    message.media,
                                    caption=caption[:1024] if caption else None,
                                    thumb=settings.thumbnail,
                                    force_document=False
                                )
                                sent_successfully = True
                            except Exception as e1:
                                # Method 2: Download and re-upload
                                logger.warning(f"Direct send failed, trying download method: {e1}")
                                try:
                                    file_path = await client.download_media(message.media)
                                    if file_path and os.path.exists(file_path):
                                        await bot.send_file(
                                            target_chat,
                                            file_path,
                                            caption=caption[:1024] if caption else None,
                                            thumb=settings.thumbnail,
                                            force_document=False
                                        )
                                        sent_successfully = True
                                        os.remove(file_path)
                                except Exception as e2:
                                    logger.error(f"Download method also failed: {e2}")
                        
                        elif caption:
                            await bot.send_message(target_chat, caption)
                            sent_successfully = True
                        
                        else:
                            # Empty post - send placeholder
                            await bot.send_message(target_chat, f"📄 Post #{msg_id} (No content)")
                            sent_successfully = True
                        
                        if sent_successfully:
                            extracted += 1
                            logger.info(f"Successfully extracted message {msg_id}")
                        else:
                            failed += 1
                            logger.error(f"Failed to send message {msg_id}")
                        
                    except Exception as send_err:
                        failed += 1
                        error_msg = str(send_err)
                        logger.error(f"Send error for message {msg_id}: {error_msg}")
                        
                        # Show detailed error for first few failures
                        if failed <= 2:
                            await bot.send_message(
                                user_id,
                                f"⚠️ **Failed to Send Post #{failed}**\n\n"
                                f"Message ID: {msg_id}\n"
                                f"Error: {error_msg[:150]}\n\n"
                                f"Continuing with next posts..."
                            )
                    
                    # Update progress every 5 posts
                    if extracted - last_update >= 5:
                        try:
                            progress_percent = int((extracted + failed) / count * 100)
                            await progress_msg.edit(
                                f"⚙️ **Extraction in Progress**\n\n"
                                f"✅ Successfully Extracted: {extracted}\n"
                                f"❌ Failed: {failed}\n"
                                f"📊 Progress: {progress_percent}%\n"
                                f"⏳ Processing: {extracted + failed}/{count}"
                            )
                            last_update = extracted
                        except:
                            pass
                    
                    # Rate limiting
                    await asyncio.sleep(0.5)
                
                except Exception as e:
                    failed += 1
                    logger.error(f"Error processing message {msg_id}: {e}")
                    continue
            
            # Extraction complete
            active_extractions[user_id] = False
            
            success_rate = int((extracted / count) * 100) if count > 0 else 0
            
            final_msg = f"""
🎉 **Extraction Complete!**

✅ **Successfully Extracted:** {extracted}
❌ **Failed:** {failed}
📊 **Total Attempted:** {count}
📈 **Success Rate:** {success_rate}%

"""
            
            if success_rate >= 95:
                final_msg += "🌟 **Perfect!** Almost all posts extracted successfully!"
            elif success_rate >= 80:
                final_msg += "✨ **Great!** Most posts extracted successfully!"
            elif success_rate >= 50:
                final_msg += "💡 **Partial Success** - Some posts might be deleted or restricted"
            else:
                final_msg += "⚠️ **Low Success Rate** - Check if:\n• Messages exist in that range\n• You have proper access\n• Channel hasn't deleted those posts"
            
            await bot.send_message(user_id, final_msg)
            
            # Disconnect user client if used
            if client != bot:
                await client.disconnect()
        
        except Exception as e:
            active_extractions[user_id] = False
            logger.error(f"Fatal extraction error: {e}")
            await bot.send_message(
                user_id,
                f"❌ **Extraction Failed**\n\n"
                f"Error: {str(e)}\n\n"
                f"Please try again or contact support."
            )
    
    # ==================== CALLBACK HANDLERS ====================
    
    @bot.on(events.CallbackQuery)
    async def callback_handler(event):
        """Handle button callbacks"""
        user_id = event.sender_id
        data = event.data.decode()
        
        await event.answer()
        
        try:
            if data == "set_chat_id":
                await event.respond(
                    "📍 **Set Target Chat ID**\n\n"
                    "Send the channel/group ID where you want posts to be sent.\n\n"
                    "💡 Use /id command in your target channel to get the ID.\n\n"
                    "Example: -1001234567890"
                )
                user_conversations[user_id] = {'step': 'set_chat_id'}
            
            elif data == "replace_words":
                await event.respond(
                    "✏️ **Replace Words**\n\n"
                    "Format: old_word | new_word\n\n"
                    "✅ Example: Harshit | MyBot\n"
                    "✅ Example: Extracted by | Posted by\n\n"
                    "Send your replacement:"
                )
                user_conversations[user_id] = {'step': 'replace_words'}
            
            elif data == "remove_words":
                await event.respond(
                    "🗑️ **Remove Words**\n\n"
                    "Enter the word or phrase you want to remove from captions.\n\n"
                    "Example: Advertisement\n"
                    "Example: Join our channel\n\n"
                    "Send the word to remove:"
                )
                user_conversations[user_id] = {'step': 'remove_words'}
            
            elif data == "custom_caption":
                await event.respond(
                    "💬 **Set Custom Caption**\n\n"
                    "Send the caption text you want to add to all extracted posts.\n\n"
                    "This will be appended to existing captions.\n\n"
                    "Example:\n"
                    "📢 Follow @MyChannel for more!\n"
                    "🔗 Website: example.com"
                )
                user_conversations[user_id] = {'step': 'custom_caption'}
            
            elif data == "set_thumbnail":
                await event.respond(
                    "🖼️ **Set Custom Thumbnail**\n\n"
                    "Send an image file to use as thumbnail for all videos and documents.\n\n"
                    "💡 Recommended: Square image (1:1 ratio)"
                )
                user_conversations[user_id] = {'step': 'set_thumbnail'}
            
            elif data == "view_settings":
                settings = get_user_settings(user_id)
                
                target = f"`{settings.target_chat_id}`" if settings.target_chat_id else "❌ Not set (posts sent to DM)"
                
                caption_display = "❌ Not set"
                if settings.custom_caption:
                    caption_preview = settings.custom_caption[:50] + "..." if len(settings.custom_caption) > 50 else settings.custom_caption
                    caption_display = f"✅ Set\nPreview: {caption_preview}"
                
                replacements = "❌ None"
                if settings.replace_words:
                    replacements = "✅ Active:\n" + "\n".join([f"  • '{k}' → '{v}'" for k, v in settings.replace_words.items()])
                
                removals = "❌ None"
                if settings.remove_words:
                    removals = "✅ Active:\n" + "\n".join([f"  • '{w}'" for w in settings.remove_words])
                
                thumbnail = "✅ Set" if settings.thumbnail else "❌ Not set"
                
                settings_text = f"""
📊 **Your Current Settings**

📍 **Target Chat ID:**
{target}

💬 **Custom Caption:**
{caption_display}

✏️ **Word Replacements:**
{replacements}

🗑️ **Words to Remove:**
{removals}

🖼️ **Thumbnail:** {thumbnail}

💡 Use buttons below to modify settings.
"""
                await event.respond(settings_text)
            
            elif data == "reset_settings":
                user_settings[user_id] = UserSettings()
                await event.respond(
                    "🔄 **All Settings Reset Successfully!**\n\n"
                    "All customizations have been removed.\n"
                    "Back to default configuration."
                )
        
        except Exception as e:
            logger.error(f"Callback error: {e}")
            await event.respond(f"❌ **Error:** {str(e)}")
    
    # ==================== RUN BOT ====================
    
    logger.info("✅ Bot handlers registered successfully!")
    logger.info("🤖 Bot is now running and ready to serve!")
    await bot.run_until_disconnected()

async def main():
    """Main entry point"""
    try:
        logger.info("🚀 Starting Telegram Channel Extractor Bot...")
        
        # Start health check server
        await create_web_server()
        
        # Start bot
        await start_bot()
        
    except KeyboardInterrupt:
        logger.info("⚠️ Bot stopped by user")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        raise

if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("TELEGRAM CHANNEL EXTRACTOR BOT")
    logger.info("=" * 60)
    logger.info(f"API_ID: {'✅ Set' if API_ID else '❌ Missing'}")
    logger.info(f"API_HASH: {'✅ Set' if API_HASH else '❌ Missing'}")
    logger.info(f"BOT_TOKEN: {'✅ Set' if BOT_TOKEN else '❌ Missing'}")
    logger.info(f"PORT: {PORT}")
    logger.info("=" * 60)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n👋 Bot stopped gracefully!")
    except Exception as e:
        logger.error(f"\n💥 Failed to start bot: {e}")
        raise