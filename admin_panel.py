import os
import asyncio
import aiohttp
from aiohttp import web
from aiohttp_session import setup as setup_session, get_session
from aiohttp_session.cookie_storage import EncryptedCookieStorage
import bcrypt
import json
from cryptography import fernet

# Local imports
import database as db

# These will be populated by main.py
BOT_INSTANCE = None
LOG_CACHE = None
active_websockets = set()

# --- Password Hashing (No changes) ---
def hash_password(plain_text_password: str) -> bytes:
    return bcrypt.hashpw(plain_text_password.encode('utf-8'), bcrypt.gensalt())

def check_password(plain_text_password: str, hashed_password: bytes) -> bool:
    return bcrypt.checkpw(plain_text_password.encode('utf-8'), hashed_password)

# --- Authentication Middleware (No changes) ---
@web.middleware
async def auth_middleware(request, handler):
    session = await get_session(request)
    # Allow access to static files, the login page, and the websocket without being logged in
    if request.path.startswith(('/static', '/login', '/ws/logs')):
        return await handler(request)
    
    if not session.get('authed'):
        return web.HTTPFound('/login')
        
    return await handler(request)

# --- WebSocket Log Broadcaster (No changes) ---
async def broadcast_log(html_log_entry: str):
    if not active_websockets:
        return
    
    message = json.dumps({'type': 'log', 'payload': html_log_entry})
    # Create a task to send messages to all clients
    tasks = [ws.send_str(message) for ws in active_websockets]
    await asyncio.gather(*tasks, return_exceptions=True)

# --- Route Handlers (No changes) ---
async def get_login(request: web.Request):
    return web.FileResponse('./templates/login.html')

async def post_login(request: web.Request):
    data = await request.post()
    password = data.get('password')
    admin_password = os.getenv('ADMIN_PANEL_PASSWORD')

    if password and admin_password and password == admin_password:
        session = await get_session(request)
        session['authed'] = True
        return web.HTTPFound('/')
    else:
        return web.HTTPFound('/login?error=1')

async def logout(request: web.Request):
    session = await get_session(request)
    session.pop('authed', None)
    return web.HTTPFound('/login')

async def get_dashboard(request: web.Request):
    context = {'logs': reversed(LOG_CACHE)}
    with open('./templates/dashboard.html', 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    log_html = "".join([f"<div class='log-entry'>{item}</div>" for item in context['logs']])
    response_html = html_content.replace("{{ log_entries }}", log_html)
    return web.Response(text=response_html, content_type='text/html')

async def get_users(request: web.Request):
    query = request.query.get('q', '').lower()
    all_users_data = await db.get_all_users_combined()
    
    users_with_names = []
    for user_data in all_users_data:
        try:
            user = BOT_INSTANCE.get_user(user_data['user_id']) or await BOT_INSTANCE.fetch_user(user_data['user_id'])
            user_display = f"{user.name}#{user.discriminator}"
        except Exception:
            user_display = "Unknown User"

        if query and query not in user_display.lower() and query not in str(user_data['user_id']):
            continue

        users_with_names.append({
            'id': user_data['user_id'],
            'name': user_display,
            'ssc': user_data['ssc_balance'] or 0,
            'grr': user_data['grr_balance'] or 0,
        })
    
    context = {'users': users_with_names, 'query': query}
    with open('./templates/users.html', 'r', encoding='utf-8') as f:
        html_content = f.read()

    user_rows = ""
    for u in context['users']:
        user_rows += f"""
        <tr>
            <td>{u['id']}</td>
            <td>{u['name']}</td>
            <td><input type="number" class="coin-input" data-userid="{u['id']}" data-currency="ssc" value="{u['ssc']}"></td>
            <td><input type="number" class="coin-input" data-userid="{u['id']}" data-currency="grr" value="{u['grr']}"></td>
        </tr>
        """
    response_html = html_content.replace("{{ user_rows }}", user_rows).replace("{{ query }}", context['query'])
    return web.Response(text=response_html, content_type='text/html')

async def post_update_user(request: web.Request):
    try:
        data = await request.json()
        user_id = int(data['user_id'])
        ssc = int(data['ssc'])
        grr = int(data['grr'])
        await db.update_user_balances(user_id, ssc, grr)
        return web.json_response({'status': 'success'})
    except Exception as e:
        print(f"Error updating user: {e}")
        return web.json_response({'status': 'error', 'message': str(e)}, status=500)

async def get_shop(request: web.Request):
    guild = BOT_INSTANCE.get_guild(int(os.getenv('MAIN_GUILD_ID', 0)))
    if not guild:
        return web.Response(text="Error: Main Guild ID not found or bot is not in the guild.", status=500)
    
    items = await db.get_all_shop_items(guild.id)
    roles = {str(r.id): r.name for r in guild.roles}
    context = {'items': items, 'roles': roles, 'guild_id': guild.id}

    with open('./templates/shop.html', 'r', encoding='utf-8') as f:
        html_content = f.read()

    item_rows = ""
    for item in context['items']:
        role_name = context['roles'].get(str(item['role_id']), f"Unknown Role ID: {item['role_id']}")
        item_rows += f"""
        <tr data-itemid="{item['item_id']}">
            <td><input type="text" value="{item['name']}" data-field="name"></td>
            <td><input type="number" value="{item['cost']}" data-field="cost"></td>
            <td>{item['role_id']} ({role_name})</td>
            <td><input type="text" value="{item['image_url'] or ''}" data-field="image_url"></td>
            <td>{'Yes' if item['is_one_time_buy'] else 'No'}</td>
            <td>
                <button class="update-item">Update</button>
                <button class="delete-item">Delete</button>
            </td>
        </tr>
        """
    
    role_options = ""
    for role_id, role_name in context['roles'].items():
        role_options += f'<option value="{role_id}">{role_name}</option>'

    response_html = html_content.replace("{{ item_rows }}", item_rows).replace("{{ role_options }}", role_options)
    return web.Response(text=response_html, content_type='text/html')

async def post_shop_action(request: web.Request):
    try:
        data = await request.json()
        action = data.pop('action')
        guild_id = int(os.getenv('MAIN_GUILD_ID', 0))

        if action == 'add':
            await db.add_shop_item(
                guild_id=guild_id, name=data['name'], cost=int(data['cost']),
                role_id=int(data['role_id']), image_url=data.get('image_url'),
                one_time_buy=bool(data['one_time_buy'])
            )
        elif action == 'update':
            await db.update_shop_item(item_id=int(data['item_id']), updates=data)
        elif action == 'delete':
            await db.delete_shop_item(item_id=int(data['item_id']))
        else:
            raise ValueError("Invalid action")

        return web.json_response({'status': 'success'})
    except Exception as e:
        print(f"Shop action failed: {e}")
        return web.json_response({'status': 'error', 'message': str(e)}, status=500)

async def get_settings(request: web.Request):
    configs = await db.get_all_configs()
    context = {
        'cf_win_rate': float(configs.get('cf_win_rate', 0.31)) * 100,
        'bet_win_rate': float(configs.get('bet_win_rate', 0.29)) * 100,
    }
    with open('./templates/settings.html', 'r', encoding='utf-8') as f:
        html_content = f.read()

    response_html = (html_content
        .replace("{{ cf_win_rate }}", f"{context['cf_win_rate']:.2f}")
        .replace("{{ bet_win_rate }}", f"{context['bet_win_rate']:.2f}"))
    return web.Response(text=response_html, content_type='text/html')

async def post_update_settings(request: web.Request):
    try:
        data = await request.json()
        cf_rate = float(data['cf_win_rate']) / 100.0
        bet_rate = float(data['bet_win_rate']) / 100.0
        await db.set_config_value('cf_win_rate', str(cf_rate))
        await db.set_config_value('bet_win_rate', str(bet_rate))
        return web.json_response({'status': 'success'})
    except Exception as e:
        return web.json_response({'status': 'error', 'message': str(e)}, status=500)

async def websocket_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    active_websockets.add(ws)
    try:
        async for msg in ws:
            # We don't expect messages from client, but good to have a loop
            pass
    finally:
        active_websockets.remove(ws)
    return ws

# --- App Setup and Runner (CORRECTED) ---
async def start_admin_panel_server(bot_instance, log_cache):
    global BOT_INSTANCE, LOG_CACHE
    BOT_INSTANCE = bot_instance
    LOG_CACHE = log_cache
    
    # --- FIX IS HERE ---
    # 1. Create the application WITHOUT the middleware first
    app = web.Application() 
    
    # 2. Setup the session storage on the app. This adds the session middleware.
    fernet_key = fernet.Fernet.generate_key()
    f = fernet.Fernet(fernet_key)
    setup_session(app, EncryptedCookieStorage(f))

    # 3. NOW, add your custom middleware. It will run after the session middleware.
    app.middlewares.append(auth_middleware)
    # --- END FIX ---

    # Add routes and static files
    app.router.add_static('/static', path='./static', name='static')
    app.router.add_get('/login', get_login)
    app.router.add_post('/login', post_login)
    app.router.add_get('/logout', logout)
    
    app.router.add_get('/', get_dashboard)
    app.router.add_get('/users', get_users)
    app.router.add_post('/api/users/update', post_update_user)
    app.router.add_get('/shop', get_shop)
    app.router.add_post('/api/shop', post_shop_action)
    app.router.add_get('/settings', get_settings)
    app.router.add_post('/api/settings/update', post_update_settings)

    app.router.add_get('/ws/logs', websocket_handler)

    # Start the server
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 5000)
    try:
        await site.start()
        print(f"INFO: Admin Panel started on http://localhost:5000")
    except Exception as e:
        print(f"ERROR: Could not start Admin Panel server. {e}")