from flask import Flask, render_template, jsonify, request
import yaml
import os
import time
import socket
import logging
import requests
import threading
import json
import pytz
from datetime import datetime, timedelta
from mcstatus import JavaServer
from typing import Dict, List, Any
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS

app = Flask(__name__, static_folder='static')
app.config['TEMPLATES_AUTO_RELOAD'] = True
CORS(app)

def get_remote_address():
    """Get the real client IP, handling Cloudflare headers"""
    # Check for Cloudflare headers first
    cf_connecting_ip = request.headers.get('CF-Connecting-IP')
    if cf_connecting_ip:
        return cf_connecting_ip
    
    # Fall back to X-Forwarded-For if present
    if request.headers.getlist("X-Forwarded-For"):
        return request.headers.getlist("X-Forwarded-For")[0]
    
    # Default to remote_addr
    return request.remote_addr

def is_local_request():
    remote = get_remote_address()
    return remote in ('127.0.0.1', 'localhost', '::1')

def log_ratelimit_exceeded(request_limit):
    try:
        client_ip = get_remote_address()
        
        # Safely get limit string
        limit_str = str(getattr(request_limit, 'limit', request_limit))
        
        # Safely get reset time if available
        retry_after = None
        if hasattr(request_limit, 'reset_at') and hasattr(request_limit.reset_at, 'isoformat'):
            try:
                retry_after = request_limit.reset_at.isoformat()
            except (AttributeError, TypeError):
                pass
        
        app.logger.warning(f"Rate limit exceeded - Client IP: {client_ip}, Limit: {limit_str}")
        
        response_data = {
            "status": "error",
            "message": f"Rate limit exceeded: {limit_str}"
        }
        if retry_after:
            response_data["retry_after"] = retry_after
            
        return jsonify(response_data), 429
        
    except Exception as e:
        app.logger.error(f"Error in rate limit handler: {str(e)}")
        return jsonify({
            "status": "error",
            "message": "Rate limit exceeded"
        }), 429

# Application configuration
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, 'config.json')
MONITORS_FILE = os.path.join(BASE_DIR, 'config', 'monitors.yml')

# In-memory storage
STATUS_DATA = {}
HISTORY_DATA = {
    'history': {}  # Format: {monitor_id: [history_entries]}
}

# Configure trusted proxies for Flask
app.config['TRUSTED_PROXIES'] = [
    '127.0.0.1',
    '172.18.0.0/16',  # Docker network
    '10.0.0.0/8',    # Private networks
    '192.168.0.0/16', # Private networks
    'fc00::/7',       # IPv6 private networks
    '::1'             # IPv6 localhost
]

# Initialize rate limiter
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["30 per minute"],
    default_limits_exempt_when=is_local_request,
    storage_uri="memory://",
    on_breach=log_ratelimit_exceeded,
    headers_enabled=True  # Enable rate limit headers in response
)

# Configure logging
app.logger.setLevel('INFO')
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
app.logger.addHandler(handler)

print("Using in-memory storage for status and history")

# Load app config
try:
    with open(CONFIG_FILE, 'r') as f:
        APP_CONFIG = json.load(f)
except Exception as e:
    print(f"Error loading config.json: {e}")
    APP_CONFIG = {}

# Timezone
try:
    TIMEZONE = pytz.timezone(APP_CONFIG['app']['timezone'])
except:
    TIMEZONE = pytz.utc

class ConfigReloadHandler(FileSystemEventHandler):
    def __init__(self, manager):
        self.manager = manager
        self.last_modified = 0
    
    def on_modified(self, event):
        if event.src_path.endswith('monitors.yml'):
            current_time = time.time()
            if current_time - self.last_modified < 1.0:  # 1 second debounce
                return
            self.last_modified = current_time
            
            print(f"Detected changes in {event.src_path}, reloading configuration...")
            try:
                self.manager.load_config()
                print("Configuration reloaded successfully")
                update_status()
                print("Status updated with new configuration")
            except Exception as e:
                print(f"Error reloading configuration: {e}")
                import traceback
                traceback.print_exc()

class MonitorManager:
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.monitors: Dict[str, Monitor] = {}
        self.categories: Dict[str, Dict] = {}
        self._setup_file_watcher()
        self.load_config()
    
    def _setup_file_watcher(self):
        event_handler = ConfigReloadHandler(self)
        self.observer = Observer()
        self.observer.schedule(event_handler, path=self.config_path, recursive=False)
        self.observer.start()
        print(f"Watching for changes in: {self.config_path}")
    
    def __del__(self):
        if hasattr(self, 'observer'):
            self.observer.stop()
            self.observer.join()

    def load_config(self):
        """Load monitor configuration from YAML file and update monitors"""
        try:
            print(f"[DEBUG] Loading config from: {self.config_path}")
            print(f"[DEBUG] File exists: {os.path.exists(self.config_path)}")
            
            with open(self.config_path, 'r') as f:
                config_content = f.read()
                print(f"[DEBUG] File content: {config_content[:200]}...")
                config = yaml.safe_load(config_content) or {}
                
            print(f"[DEBUG] Parsed config: {config}")
            monitors_config = config.get('monitors', {})
            print(f"[DEBUG] Found {len(monitors_config)} monitors in config")
            categories_config = config.get('categories', {})
            print(f"Loaded configuration with {len(monitors_config)} monitors and {len(categories_config)} categories")
            
            self.monitors = {}
            for monitor_id, monitor_config in monitors_config.items():
                self.monitors[monitor_id] = Monitor(monitor_id, monitor_config)
                
            self.categories = {}
            for category in categories_config:
                if isinstance(category, dict):
                    self.categories[category.get('id', '')] = category
                else:
                    self.categories[category] = {'id': category, 'name': category}
                    
            return config
            
        except Exception as e:
            print(f"Error loading configuration: {e}")
            import traceback
            traceback.print_exc()
            return None

class Monitor:
    def __init__(self, monitor_id: str, config: dict):
        self.id = monitor_id
        self.config = config
        self.status = {
            'up': False,
            'last_check': None,
            'response_time': 0,
            'error': '',
            'uptime_24h': 0,
            'uptime_7d': 0,
            'total_checks': 0,
            'successful_checks': 0
        }
        self.history: List[Dict[str, Any]] = []
        self.load_history()
    
    def load_history(self):
        """Load monitor history from in-memory storage"""
        self.history = HISTORY_DATA.get('history', {}).get(self.id, [])
    
    def update_history(self, is_up: bool, response_time: float, error: str = ''):
        """Update monitor history with latest check"""
        now = datetime.now(TIMEZONE)
        timestamp = now.isoformat()
        
        self.status['last_check'] = timestamp
        self.status['up'] = is_up
        self.status['response_time'] = response_time
        self.status['error'] = error
        self.status['total_checks'] = self.status.get('total_checks', 0) + 1
        
        if is_up:
            self.status['successful_checks'] = self.status.get('successful_checks', 0) + 1
        
        history_entry = {
            'timestamp': timestamp,
            'up': is_up,
            'response_time': response_time,
            'error': error
        }
        
        # Update in-memory history
        if 'history' not in HISTORY_DATA:
            HISTORY_DATA['history'] = {}
            
        if self.id not in HISTORY_DATA['history']:
            HISTORY_DATA['history'][self.id] = []
            
        HISTORY_DATA['history'][self.id].append(history_entry)
        HISTORY_DATA['history'][self.id] = HISTORY_DATA['history'][self.id][-100:]  # Keep last 100 entries
        
        # Update local history for this monitor
        self.history = HISTORY_DATA['history'][self.id]
        
        self._update_uptime_stats()
    
    def _update_uptime_stats(self):
        """Calculate uptime statistics"""
        now = datetime.now(TIMEZONE)
        
        day_ago = now - timedelta(days=1)
        day_checks = [h for h in self.history if 
                     datetime.fromisoformat(h['timestamp']).replace(tzinfo=TIMEZONE) > day_ago]
        
        if day_checks:
            uptime = sum(1 for h in day_checks if h['up']) / len(day_checks) * 100
            self.status['uptime_24h'] = round(uptime, 2)
        
        week_ago = now - timedelta(days=7)
        week_checks = [h for h in self.history if 
                      datetime.fromisoformat(h['timestamp']).replace(tzinfo=TIMEZONE) > week_ago]
        
        if week_checks:
            uptime = sum(1 for h in week_checks if h['up']) / len(week_checks) * 100
            self.status['uptime_7d'] = round(uptime, 2)
    
    def _save_history(self):
        """Save history to memory"""
        if 'history' not in HISTORY_DATA:
            HISTORY_DATA['history'] = {}
        HISTORY_DATA['history'][self.id] = self.history

# Global monitor manager instance
monitor_manager = MonitorManager(MONITORS_FILE)

def load_monitors():
    """Load monitors configuration from monitor manager"""
    return {
        'monitors': monitor_manager.monitors,
        'categories': list(monitor_manager.categories.values())
    }

def save_monitors(monitors: dict, categories: dict):
    config = {
        'monitors': monitors,
        'categories': categories
    }
    os.makedirs(os.path.dirname(MONITORS_FILE), exist_ok=True)
    with open(MONITORS_FILE, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    load_monitors.cache_clear()

def check_http(monitor: Monitor) -> Monitor:
    """Check HTTP/HTTPS endpoint"""
    start_time = time.time()
    error = ''
    response_time = 0
    
    try:
        response = requests.get(
            monitor.config['url'],
            timeout=monitor.config.get('timeout', 10),
            verify=False,
            allow_redirects=True,
            headers={'User-Agent': 'Uptimium/1.0'}
        )
        response_time = (time.time() - start_time) * 1000  # ms
        is_up = response.status_code < 400
        if not is_up:
            error = f'HTTP {response.status_code}'
    except requests.exceptions.Timeout:
        error = 'Connection timeout'
        is_up = False
    except requests.exceptions.SSL_ERROR as e:
        error = 'SSL Error: ' + str(e)
        is_up = False
    except requests.exceptions.ConnectionError as e:
        error = 'Connection Error: ' + str(e)
        is_up = False
    except Exception as e:
        error = str(e)
        is_up = False
    
    monitor.update_history(is_up, response_time, error)
    return monitor

def check_tcp(monitor: Monitor) -> Monitor:
    """Check TCP port"""
    return _check_socket(monitor, socket.SOCK_STREAM)

def check_udp(monitor: Monitor) -> Monitor:
    """Check UDP port"""
    return _check_socket(monitor, socket.SOCK_DGRAM)

def _check_socket(monitor: Monitor, socket_type: int) -> Monitor:
    """Generic socket checker for both TCP and UDP"""
    host = monitor.config['host']
    port = int(monitor.config['port'])
    timeout = monitor.config.get('timeout', 10)
    start_time = time.time()
    error = ''
    response_time = 0
    is_up = False
    
    try:
        if socket_type == socket.SOCK_STREAM:  # TCP
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((host, port))
            sock.close()
            is_up = True
        else:  # UDP
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(timeout)
            # Send empty datagram to check if port is open
            sock.sendto(b'', (host, port))
            # Wait for response (some UDP services may respond to empty packets)
            try:
                data, _ = sock.recvfrom(1024)
                is_up = True
            except socket.timeout:
                # No response, but port might be open
                is_up = True
        
        response_time = (time.time() - start_time) * 1000  # ms
    except socket.timeout:
        error = 'Connection timeout'
    except ConnectionRefusedError:
        error = 'Connection refused'
    except Exception as e:
        error = str(e)
    finally:
        if 'sock' in locals():
            try:
                sock.close()
            except:
                pass
    
    monitor.update_history(is_up, response_time, error)
    return monitor

def check_minecraft(monitor: Monitor) -> Monitor:
    """Check Minecraft server status"""
    host = monitor.config.get('host')
    port = int(monitor.config.get('port', 25565))
    start_time = time.time()
    error = ''
    response_time = 0
    
    try:
        server = JavaServer(host, port)
        # Try to get server status with timeout
        server.status()
        response_time = (time.time() - start_time) * 1000  # ms
        is_up = True
    except Exception as e:
        error = str(e)
        is_up = False
    
    monitor.update_history(is_up, response_time, error)
    return monitor

def check_monitor(monitor: Monitor) -> Monitor:
    """Run appropriate check based on monitor type"""
    check_functions = {
        'http': check_http,
        'https': check_http,
        'tcp': check_tcp,
        'udp': check_udp,
        'minecraft': check_minecraft
    }
    
    monitor_type = monitor.config['type'].lower()
    check_func = check_functions.get(monitor_type)
    
    if not check_func:
        monitor.update_history(False, 0, f'Unsupported monitor type: {monitor_type}')
        return monitor
    
    try:
        return check_func(monitor)
    except Exception as e:
        monitor.update_history(False, 0, f'Check error: {str(e)}')
        return monitor

def update_status():
    monitors = monitor_manager.monitors

    for monitor_id, monitor in monitors.items():
        try:
            if not hasattr(monitor, 'config'):
                print(f"Missing config for monitor {monitor_id}")
                continue

            checked_monitor = check_monitor(monitor)

            # Update monitor status in memory
            checked_monitor.status.update({
                'up': checked_monitor.status.get('up', False),
                'last_check': checked_monitor.status.get('last_check'),
                'response_time': checked_monitor.status.get('response_time', 0),
                'error': checked_monitor.status.get('error', ''),
                'uptime_24h': checked_monitor.status.get('uptime_24h', 0),
                'uptime_7d': checked_monitor.status.get('uptime_7d', 0)
            })

            # Save history
            if hasattr(checked_monitor, '_save_history'):
                checked_monitor._save_history()

            time.sleep(1)

        except Exception as e:
            print(f"Error updating status for {monitor_id}: {e}")
            import traceback
            traceback.print_exc()

def run_checks():
    """Main monitoring loop"""
    while True:
        try:
            update_status()
            time.sleep(APP_CONFIG.get('check_interval', 60))
            
        except Exception as e:
            print(f"Error in monitoring loop: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(60)  # Wait a bit before retrying on errors

@app.route('/')
def index():
    """Main dashboard view"""
    try:
        config = load_monitors()
        categories = config.get('categories', [])
        
        category_map = {}
        for category in categories:
            if isinstance(category, dict):
                category_map[category.get('id', '')] = category
            else:
                category_map[category] = {'id': category, 'name': category}
        
        # Get monitors from in-memory storage
        monitors = {}
        for monitor_id, monitor in monitor_manager.monitors.items():
            monitors[monitor_id] = {
                'config': monitor.config,
                'up': monitor.status.get('up', False),
                'last_check': monitor.status.get('last_check'),
                'response_time': monitor.status.get('response_time', 0),
                'error': monitor.status.get('error', ''),
                'uptime_24h': monitor.status.get('uptime_24h', 0),
                'uptime_7d': monitor.status.get('uptime_7d', 0)
            }
        
        monitors_by_category = {}
        
        # Group monitors by category
        for monitor_id, monitor_data in monitors.items():
            category_id = monitor_data['config'].get('category')
            if category_id not in monitors_by_category:
                monitors_by_category[category_id] = []
            
            monitor_data['id'] = monitor_id
            monitors_by_category[category_id].append(monitor_data)
        
        # Create categories list with monitors
        categories_with_monitors = []
        
        # Add categorized monitors first
        for category_id, category in category_map.items():
            if category_id in monitors_by_category:
                categories_with_monitors.append({
                    'id': category_id,
                    'name': category.get('name', category_id),
                    'monitors': monitors_by_category[category_id]
                })
        
        # Add uncategorized monitors
        if 'uncategorized' in monitors_by_category:
            categories_with_monitors.append({
                'id': 'uncategorized',
                'name': 'Uncategorized',
                'monitors': monitors_by_category['uncategorized']
            })
        
        return render_template(
            'index.html',
            monitors=monitors,
            categories=categories_with_monitors,
            app_config=APP_CONFIG
        )
    except Exception as e:
        print(f"Error in index route: {e}")
        # Return a simple error response since we don't have error.html
        return f"Error loading dashboard: {str(e)}", 500

@app.route('/api/status')
def api_status():
    """API endpoint for monitor status"""
    try:
        status_data = {}
        for monitor_id, monitor in monitor_manager.monitors.items():
            status_data[monitor_id] = {
                'config': monitor.config,
                'up': monitor.status.get('up', False),
                'last_check': monitor.status.get('last_check'),
                'response_time': monitor.status.get('response_time', 0),
                'error': monitor.status.get('error', ''),
                'uptime_24h': monitor.status.get('uptime_24h', 0),
                'uptime_7d': monitor.status.get('uptime_7d', 0)
            }
        return jsonify(status_data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/monitor/<monitor_id>/history')
@limiter.limit("30 per minute")
def api_monitor_history(monitor_id):
    """API endpoint for monitor history"""
    try:
        if not monitor_id or monitor_id == 'undefined':
            return jsonify({"error": "Invalid monitor ID"}), 400
            
        history = HISTORY_DATA.get('history', {}).get(monitor_id, [])
        return jsonify(history)
                
    except Exception as e:
        app.logger.error(f"Error fetching history for {monitor_id}: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/api/categories')
@limiter.limit("60 per minute")
def api_categories():
    """API endpoint for categories"""
    try:
        categories = []
        for cat in monitor_manager.categories:
            category = monitor_manager.categories[cat].copy()
            category['id'] = cat
            categories.append(category)
        return jsonify(categories)
    except Exception as e:
        app.logger.error(f"Error getting categories: {str(e)}")
        return jsonify({"error": "Failed to load categories"}), 500

@app.route('/api/availability')
@limiter.limit("60 per minute")
def api_availability():
    """API endpoint for quick service availability check"""
    try:
        result = {
            'status': 'ok',
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'services': {}
        }
        
        for monitor_id, monitor in monitor_manager.monitors.items():
            result['services'][monitor_id] = {
                'name': monitor.config.get('name', monitor_id),
                'status': 'up' if monitor.status.get('up') else 'down',
                'last_check': monitor.status.get('last_check'),
                'response_time': monitor.status.get('response_time'),
                'type': monitor.config.get('type')
            }
            
            # If any service is down, set overall status to 'degraded'
            if not monitor.status.get('up'):
                result['status'] = 'degraded'
                
        return jsonify(result)
    except Exception as e:
        app.logger.error(f"Error in availability check: {str(e)}")
        return jsonify({
            'status': 'error',
            'error': 'Failed to check service availability',
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }), 500

def start_monitoring_thread():
    """Start the monitoring thread"""
    print("Starting monitoring thread...")
    monitor_thread = threading.Thread(target=run_checks, daemon=True)
    monitor_thread.start()
    print("Monitoring thread started")
    print("Running initial check...")
    update_status()
    return monitor_thread

# Start monitoring thread when the module is imported
monitor_thread = start_monitoring_thread()

if __name__ == '__main__':
    app.run(
        host=APP_CONFIG['app'].get('host', '0.0.0.0'),
        port=APP_CONFIG['app'].get('port', 5000),
        debug=APP_CONFIG['app'].get('debug', False)
    )
