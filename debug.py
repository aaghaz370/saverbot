"""
Complete debug script - Run this to find exact problem
"""

import asyncio
import os
from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID = 20598098
API_HASH = 'c1727e40f8585b869cef73b828b2bf69'
BOT_TOKEN = '8481545345:AAEIB3zKphtr29h0232hykXuG_qIRllk1aQ'

# YOUR SESSION STRING (from successful login)
# You need to get this from the bot's user_sessions after login
USER_SESSION = "1BVtsOHkBuxHdRjFYIKh3ugoaEAhhhwMZfp_4R15FC0wxz0bfOUdi3ZfNRQ68caa45xnrUua5CykaONdQZYJdfr74OBrZEST_8FkAESB8si7-e6KKmb3SRMmnNIBkBCu6rfWGPZajkhb40yE2wELWyqQLPTJfm_C6lRGOtxhms1WRO2ei_XIZN0wXqsynZd6RKU9QY5hRt_4O1T3ooszN2i1pZdgq8sfhhtwiDDX4im1G-Sg4xb2-r4WsUXPkYQiTLxbECYLvjWzvjYtJ65Tp-QvXs7G0CgZvv4cBqxf4fgbveXvzMDUQ5b412ROWm6JsbfV99PzGZbkVK2we3t5O7A82dz9yRDg="  # Leave empty if you want to test with bot only

async def comprehensive_test():
    print("=" * 60)
    print("COMPREHENSIVE DEBUG TEST")
    print("=" * 60)
    
    # Test 1: Bot Access
    print("\n[TEST 1] Testing BOT access...")
    bot = TelegramClient('test_bot', API_ID, API_HASH)
    await bot.start(bot_token=BOT_TOKEN)
    
    # Your private channel
    # t.me/c/2342349151 → -1002342349151 (NOT -1001002342349151)
    channel_id = -1002342349151  # CORRECT conversion!
    msg_id = 1195
    
    print(f"Channel ID: {channel_id}")
    print(f"Message ID: {msg_id}")
    
    try:
        print("\n[BOT] Fetching message...")
        message = await bot.get_messages(channel_id, ids=msg_id)
        
        if not message:
            print("❌ BOT: Message is None")
        elif message.empty:
            print("❌ BOT: Message is empty")
        else:
            print("✅ BOT: Message found!")
            print(f"   - Text: {bool(message.text)}")
            print(f"   - Media: {bool(message.media)}")
            print(f"   - Media type: {type(message.media).__name__ if message.media else 'None'}")
            
            if message.text:
                print(f"   - Text preview: {message.text[:100]}")
    
    except Exception as e:
        print(f"❌ BOT ERROR: {e}")
        print(f"   Type: {type(e).__name__}")
    
    # Test 2: User Session Access
    if USER_SESSION:
        print("\n[TEST 2] Testing USER SESSION access...")
        user_client = TelegramClient(StringSession(USER_SESSION), API_ID, API_HASH)
        await user_client.connect()
        
        try:
            print("\n[USER] Fetching message...")
            message = await user_client.get_messages(channel_id, ids=msg_id)
            
            if not message:
                print("❌ USER: Message is None")
            elif isinstance(message, list):
                if len(message) == 0:
                    print("❌ USER: Empty list returned")
                else:
                    message = message[0]
                    print("✅ USER: Message found!")
                    print(f"   - Text: {bool(message.text)}")
                    print(f"   - Media: {bool(message.media)}")
                    print(f"   - Media type: {type(message.media).__name__ if message.media else 'None'}")
                    
                    # Try to send it
                    print("\n[USER] Trying to send to self...")
                    try:
                        me = await user_client.get_me()
                        if message.media:
                            await user_client.send_file(me.id, message.media)
                            print("✅ USER: Successfully sent media to self!")
                        elif message.text:
                            await user_client.send_message(me.id, message.text)
                            print("✅ USER: Successfully sent text to self!")
                    except Exception as send_err:
                        print(f"❌ USER SEND ERROR: {send_err}")
            else:
                print("✅ USER: Message found!")
                print(f"   - Text: {bool(message.text)}")
                print(f"   - Media: {bool(message.media)}")
                print(f"   - Media type: {type(message.media).__name__ if message.media else 'None'}")
        
        except Exception as e:
            print(f"❌ USER ERROR: {e}")
            print(f"   Type: {type(e).__name__}")
        
        await user_client.disconnect()
    
    # Test 3: Target Channel Access
    target_channel = -1003364187309
    print(f"\n[TEST 3] Testing TARGET CHANNEL access...")
    print(f"Target: {target_channel}")
    
    try:
        print("\n[BOT] Sending test message to target...")
        test_msg = await bot.send_message(target_channel, "🧪 Test message")
        print("✅ BOT: Successfully sent to target channel!")
        
        # Delete test message
        await test_msg.delete()
        print("✅ Test message deleted")
        
    except Exception as e:
        print(f"❌ TARGET CHANNEL ERROR: {e}")
        print(f"   Type: {type(e).__name__}")
        
        if 'admin' in str(e).lower() or 'permission' in str(e).lower():
            print("\n💡 SOLUTION: Bot is NOT admin in target channel!")
            print("   1. Go to your channel")
            print("   2. Add bot as admin")
            print("   3. Enable 'Post Messages' permission")
    
    # Test 4: Complete Flow Test
    if USER_SESSION:
        print("\n[TEST 4] Complete extraction flow...")
        user_client = TelegramClient(StringSession(USER_SESSION), API_ID, API_HASH)
        await user_client.connect()
        
        try:
            # Fetch from private channel
            message = await user_client.get_messages(channel_id, ids=msg_id)
            
            # Handle list response
            if isinstance(message, list):
                if len(message) > 0 and message[0]:
                    message = message[0]
                else:
                    print("❌ Empty message list")
                    message = None
            
            if message and (message.text or message.media):
                print("✅ Message fetched from private channel")
                
                # Send to target
                if message.media:
                    print("[BOT] Sending media to target...")
                    # Try download and reupload
                    file_path = await user_client.download_media(message.media)
                    if file_path:
                        await bot.send_file(target_channel, file_path, caption=message.text)
                        print("✅ Media sent successfully!")
                        if os.path.exists(file_path):
                            os.remove(file_path)
                
                elif message.text:
                    print("[BOT] Sending text to target...")
                    await bot.send_message(target_channel, message.text)
                    print("✅ Text sent successfully!")
            else:
                print("❌ No valid message to send")
        
        except Exception as e:
            print(f"❌ FLOW ERROR: {e}")
        
        await user_client.disconnect()
    
    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)
    
    await bot.disconnect()

if __name__ == "__main__":
    print("\n⚠️  IMPORTANT: If you have logged in via bot, you need to add")
    print("   your session string here to test user session access.\n")
    
    asyncio.run(comprehensive_test())