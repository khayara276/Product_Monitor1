import json
import time
import random
import threading
import queue
import os
import requests 
import sqlite3
import concurrent.futures
import sys
import subprocess
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Check for stealth library
try:
    from curl_cffi import requests as crequests
except ImportError:
    print("❌ curl_cffi missing! Install it.")
    sys.exit(1)

from DrissionPage import ChromiumPage, ChromiumOptions

# ==========================================
# ⚙️ CONFIGURATION (ENV VARS)
# ==========================================
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')
COOKIES_JSON = os.getenv('COOKIES_JSON') 

DB_PATH = os.path.join('data', 'shein_products.db')

HEADLESS_MODE = True 

# 🔥 TURBO MODE CONFIGURATION
# 50 Threads + Polymorphic Rotation = Max Speed
NUM_THREADS = 50         
BATCH_SIZE = 50         
CYCLE_DELAY = 0.1       

PRIORITY_SIZES = ["XS", "S", "M", "L", "XL", "XXL", "28", "30", "32", "34", "36"]

# Massive list of fingerprints to rotate (Confuse the firewall)
BROWSER_FINGERPRINTS = [
    "chrome100", "chrome110", "chrome119", "chrome120", "chrome124",
    "edge99", "edge101", 
    "safari15_3", "safari17_0"
]

# ==========================================
# 🛠️ UTILITY FUNCTIONS
# ==========================================

def send_telegram(message, image_url=None, button_url=None):
    if not TELEGRAM_TOKEN or not CHAT_ID: return
    try:
        payload = {
            "chat_id": CHAT_ID,
            "parse_mode": "HTML",
            "disable_web_page_preview": False
        }
        if button_url:
            payload["reply_markup"] = json.dumps({
                "inline_keyboard": [[{"text": "🛍️ BUY NOW", "url": button_url}]]
            })
        if image_url:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
            payload["photo"] = image_url
            payload["caption"] = message
        else:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            payload["text"] = message
        requests.post(url, data=payload, timeout=10)
    except Exception: pass

# ==========================================
# 🚀 DB MONITOR CLASS (TURBO EDITION)
# ==========================================

class DBStockMonitor:
    def __init__(self):
        self.browser = None
        self.running = True
        self.batch_queue = queue.Queue()
        self.stock_cache = {} 
        self.ignore_list = set() 
        self.total_products = 0
        self.processed_count = 0
        self.lock = threading.Lock()
        
        # Adaptive Speed Control
        self.error_streak = 0
        self.consecutive_success = 0
        
        # Always prefer Python mode for speed
        self.use_python_mode = True 
        
        self.init_database()

    def init_database(self):
        if not os.path.exists('data'): os.makedirs('data')
        
        if os.path.exists(DB_PATH):
            try:
                with open(DB_PATH, 'rb') as f:
                    header = f.read(100)
                
                if b'version https://git-lfs.github.com/spec/v1' in header:
                    print("⚠️ LFS Pointer detected! Pulling DB...", flush=True)
                    try:
                        subprocess.run(["git", "lfs", "pull"], check=True)
                        print("✅ LFS Pull Successful!", flush=True)
                    except Exception:
                        print("❌ LFS Pull Failed. Ensure workflow has 'lfs: true'.", flush=True)
                        sys.exit(1)

                with open(DB_PATH, 'rb') as f:
                    header = f.read(16)
                if b'SQLite format 3' not in header:
                    print("❌ FATAL: Invalid DB file.", flush=True)
                    sys.exit(1)
                    
            except Exception as e:
                print(f"⚠️ DB Check Error: {e}", flush=True)
                sys.exit(1)

        conn = sqlite3.connect(DB_PATH)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS products (
                product_id TEXT PRIMARY KEY,
                product_name TEXT,
                price INTEGER,
                url TEXT,
                image_url TEXT,
                last_updated TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()

    def get_clean_image_url(self, raw_url):
        if not raw_url: return None
        try:
            clean_url = re.sub(r'_\d+x\d+', '', raw_url).replace('_thumbnail', '')
            if 'ajio.com' in clean_url: clean_url = clean_url.split('?')[0]
            return clean_url
        except: return raw_url

    def get_browser_options(self, port):
        co = ChromiumOptions()
        co.set_local_port(port)
        co.set_argument('--no-sandbox')
        co.set_argument('--headless=new') 
        co.set_argument('--disable-gpu')
        co.set_argument('--disable-blink-features=AutomationControlled') 
        co.set_argument('--blink-settings=imagesEnabled=false')
        return co

    def init_browser(self):
        if self.browser: return True
        print("🚀 Initializing Backup Browser...", flush=True)
        try:
            port = random.randint(40000, 50000)
            co = self.get_browser_options(port)
            self.browser = ChromiumPage(co)
            return True
        except Exception:
            return False

    def get_all_products(self):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT product_id, product_name FROM products")
        rows = cursor.fetchall()
        conn.close()
        return [row for row in rows if row[0] not in self.ignore_list]

    # --- TURBO FETCHING ENGINE ---
    def hybrid_fetch_batch(self, pids):
        # Only slow down if we hit MAJOR blocks
        if self.error_streak > 10:
            time.sleep(1) # Brief cool down
            
        if self.use_python_mode:
            return self.fetch_batch_stealth(pids)
        else:
            return self.fetch_batch_browser(pids)

    def fetch_batch_stealth(self, pids):
        results = []
        forbidden_count = 0
        
        def fetch_one(pid):
            # 🔥 TURBO: Micro-delay only (0.01s - 0.1s)
            # This is extremely fast but relies on fingerprint rotation to stay safe
            time.sleep(random.uniform(0.01, 0.1))
            
            try:
                fingerprint = random.choice(BROWSER_FINGERPRINTS)
                url = f"https://sheinindia.ajio.com/api/p/{pid}?fields=SITE"
                
                res = crequests.get(
                    url, 
                    impersonate=fingerprint,
                    headers={
                        'Referer': 'https://sheinindia.ajio.com/',
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Cache-Control': 'no-cache'
                    },
                    timeout=5 # Fail fast
                )
                
                if res.status_code == 200:
                    return {'id': pid, 'status': 200, 'data': res.json()}
                elif res.status_code == 403:
                    return {'id': pid, 'status': 403}
                return {'id': pid, 'status': 'ERR'}
            except:
                return {'id': pid, 'status': 'ERR'}

        with concurrent.futures.ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
            future_to_pid = {executor.submit(fetch_one, pid): pid for pid in pids}
            for future in concurrent.futures.as_completed(future_to_pid):
                res = future.result()
                results.append(res)
                if res['status'] == 403: forbidden_count += 1

        # Turbo Logic: Higher tolerance for errors before switching
        if forbidden_count > 5:
            self.error_streak += 1
            self.consecutive_success = 0
            print(f"   ⚠️ 403 Spike ({forbidden_count}).", flush=True)
            if self.error_streak > 5:
                # Only switch if persistently blocked
                print("   🔻 Switching to Slow Mode...", flush=True)
                self.use_python_mode = False
        else:
            self.consecutive_success += 1
            if self.consecutive_success > 3:
                self.error_streak = 0
        
        return results

    def fetch_batch_browser(self, pids):
        if not self.browser: self.init_browser()
        try:
            pid_list_str = json.dumps(pids)
            js_code = f"""
                const pids = {pid_list_str};
                const wait = (ms) => new Promise(resolve => setTimeout(resolve, ms));
                async function fetchAll() {{
                    const results = [];
                    for (const pid of pids) {{
                        await wait(100); // 0.1s delay in browser (Faster)
                        try {{
                            const res = await fetch(`https://sheinindia.ajio.com/api/p/${{pid}}?fields=SITE`);
                            if(res.status === 403) {{ results.push({{id: pid, status: 403}}); break; }}
                            if(res.ok) {{
                                const data = await res.json();
                                results.push({{id: pid, status: 200, data: data}});
                            }} else {{ results.push({{id: pid, status: 'ERR'}}); }}
                        }} catch(e) {{ results.push({{id: pid, status: 'ERR'}}); }}
                    }}
                    return JSON.stringify(results);
                }}
                return fetchAll();
            """
            result_str = self.browser.latest_tab.run_js(js_code, timeout=60)
            if result_str: 
                results = json.loads(result_str)
                # Try to switch back to Turbo Mode ASAP
                if len(results) > 0 and not any(r['status'] == 403 for r in results):
                     self.use_python_mode = True
                return results
        except: pass
        return []

    def worker_loop(self):
        while self.running:
            try:
                try:
                    batch_items = self.batch_queue.get(timeout=1)
                except queue.Empty:
                    continue 

                try:
                    pids = [item[0] for item in batch_items]
                    name_map = {item[0]: item[1] for item in batch_items}
                    
                    results = self.hybrid_fetch_batch(pids)
                    
                    if results:
                        for res in results:
                            if res.get('status') == 200 and res.get('data'):
                                self.process_product(res['id'], res['data'], name_map.get(res['id']))
                    
                    with self.lock:
                        self.processed_count += len(batch_items)
                        pct = (self.processed_count / self.total_products) * 100 if self.total_products else 0
                        mode_icon = "⚡" if self.use_python_mode else "🐢"
                        if self.processed_count % 200 < BATCH_SIZE: 
                            print(f"   {mode_icon} Turbo: {self.processed_count}/{self.total_products} ({pct:.1f}%)", end='\r', flush=True)

                finally:
                    self.batch_queue.task_done()
                    time.sleep(0.01)

            except Exception: pass

    def process_product(self, pid, data, old_name):
        try:
            if pid in self.ignore_list: return

            name = data.get('productRelationID', data.get('name', old_name or 'Unknown'))
            price_obj = data.get('offerPrice') or data.get('price')
            price_val = f"₹{int(price_obj.get('value'))}" if price_obj and price_obj.get('value') else "N/A"

            current_stock = {}
            for v in data.get('variantOptions', []):
                qs = v.get('variantOptionQualifiers', [])
                size = next((q['value'] for q in qs if q['qualifier'] == 'size'), 
                       next((q['value'] for q in qs if q['qualifier'] == 'standardSize'), None))
                if size:
                    status = v.get('stock', {}).get('stockLevelStatus', '')
                    qty = v.get('stock', {}).get('stockLevel', 0)
                    if status in ['inStock', 'lowStock']: current_stock[size] = qty
                    else: current_stock[size] = 0

            current_sig = ",".join([f"{k}:{v}" for k, v in sorted(current_stock.items())])
            last_sig = self.stock_cache.get(pid)
            
            found_priority = []
            for size, qty in current_stock.items():
                if qty > 0 and size.upper() in PRIORITY_SIZES:
                    found_priority.append(f"{size} ({qty})")

            should_alert = False
            status_msg = ""
            
            if current_sig != last_sig:
                if found_priority:
                    if not last_sig: 
                        status_msg = f"🔥 <b>TRACKING STARTED</b>"
                        should_alert = True
                    else:
                        status_msg = f"⚡ <b>STOCK UPDATE</b>"
                        should_alert = True
                self.stock_cache[pid] = current_sig

            if should_alert:
                raw_img_url = data.get('selected', {}).get('modelImage', {}).get('url')
                if not raw_img_url and 'images' in data and data['images']: raw_img_url = data['images'][0].get('url')
                hd_img_url = self.get_clean_image_url(raw_img_url)
                buy_url = f"https://www.sheinindia.in/p/{pid}"
                
                priority_text = ", ".join(found_priority)
                all_sizes_text = "\n".join([f"{'✅' if q>0 else '❌'} {s}: {q}" for s, q in current_stock.items()])

                msg = (
                    f"{status_msg}\n\n"
                    f"👚 <b>{name}</b>\n"
                    f"💰 <b>{price_val}</b>\n\n"
                    f"🎯 <b>Priority Found:</b> {priority_text}\n\n"
                    f"📏 <b>Full Stock:</b>\n<pre>{all_sizes_text}</pre>\n\n"
                    f"🔗 <a href='{buy_url}'>Check on Shein</a>"
                )
                print(f"🔔 Alert Sent: {name}", flush=True)
                send_telegram(msg, image_url=hd_img_url, button_url=buy_url)
                self.ignore_list.add(pid)

        except Exception as e: pass

    def auto_cleaner(self):
        while self.running:
            wait_time = 6 * 3600 
            print(f"\n⏰ Cleaner scheduled in 6 hours...", flush=True)
            time.sleep(wait_time)
            with self.lock:
                self.ignore_list.clear()
                self.stock_cache.clear()
                print(f"\n🧹 Cache Cleared!", flush=True)

    def start(self):
        print("="*60, flush=True)
        print("🚀 SHEIN MONITOR: TURBO SPEED EDITION", flush=True)
        print(f"📦 Batch Size: {BATCH_SIZE} | Workers: {NUM_THREADS}", flush=True)
        print("="*60, flush=True)

        threading.Thread(target=self.auto_cleaner, daemon=True).start()

        print(f"\n🧵 Launching {NUM_THREADS} Turbo Workers...", flush=True)
        for _ in range(NUM_THREADS):
            t = threading.Thread(target=self.worker_loop, daemon=True)
            t.start()

        cycle = 0
        try:
            while True:
                cycle += 1
                all_products = self.get_all_products()
                self.total_products = len(all_products)
                self.processed_count = 0
                
                print(f"\n🔄 Cycle #{cycle}: Scanning {self.total_products} products...", flush=True)
                
                if self.total_products == 0:
                    print("⚠️ DB is empty.", flush=True)
                    time.sleep(60); continue

                for i in range(0, len(all_products), BATCH_SIZE):
                    batch = all_products[i:i + BATCH_SIZE]
                    self.batch_queue.put(batch)
                
                self.batch_queue.join()
                
                print(f"\n✅ Cycle Complete! Restarting...", flush=True)
                time.sleep(CYCLE_DELAY)
                
        except KeyboardInterrupt:
            self.running = False
            if self.browser: self.browser.quit()

if __name__ == "__main__":
    monitor = DBStockMonitor()
    monitor.start()
