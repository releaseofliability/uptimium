from flask import Flask, render_template, jsonify
import yaml
import os
import time
import socket
import requests
import threading
import json
import pytz
from datetime import datetime, timedelta
from mcstatus import JavaServer
from typing import Dict, List, Any
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

app = Flask(__name__, static_folder='static')
app.config['TEMPLATES_AUTO_RELOAD'] = True

# Configuration paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, 'config.json')
MONITORS_FILE = os.path.join(BASE_DIR, 'monitors.yml')
STATUS_FILE = os.path.join(BASE_DIR, 'status.json')
HISTORY_FILE = os.path.join(BASE_DIR, 'history.json')

# Load app config
with open(CONFIG_FILE, 'r') as f:
    APP_CONFIG = json.load(f)

# Timezone
try:
    TIMEZONE = pytz.timezone(APP_CONFIG['app']['timezone'])
except:
    TIMEZONE = pytz.utc

# Initialize history if not exists
if not os.path.exists(HISTORY_FILE):
    with open(HISTORY_FILE, 'w') as f:
        json.dump({"history": {}}, f)

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
            with open(self.config_path, 'r') as f:
                config = yaml.safe_load(f) or {}
                
            monitors_config = config.get('monitors', {})
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
        """Load monitor history from file"""
        try:
            with open(HISTORY_FILE, 'r') as f:
                history_data = json.load(f)
                self.history = history_data.get('history', {}).get(self.id, [])
        except (FileNotFoundError, json.JSONDecodeError):
            self.history = []
    
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
        
        self.history.append(history_entry)
        
        self.history = self.history[-100:]
        
        self._update_uptime_stats()
        
        self._save_history()
    
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
        """Save history to file"""
        try:
            if os.path.exists(HISTORY_FILE):
                with open(HISTORY_FILE, 'r') as f:
                    history_data = json.load(f)
            else:
                history_data = {"history": {}}
            
            history_data['history'][self.id] = self.history
            
            with open(HISTORY_FILE, 'w') as f:
                json.dump(history_data, f, default=str)
        except Exception as e:
            print(f"Error saving history: {e}")

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
    status_data = {}
    
    for monitor_id, monitor in monitors.items():
        try:
            if not hasattr(monitor, 'config'):
                print(f"Missing config for monitor {monitor_id}")
                continue
                
            checked_monitor = check_monitor(monitor)
            
            status_data[monitor_id] = {
                'config': checked_monitor.config,
                'up': checked_monitor.status.get('up', False),
                'last_check': checked_monitor.status.get('last_check'),
                'response_time': checked_monitor.status.get('response_time', 0),
                'error': checked_monitor.status.get('error', ''),
                'uptime_24h': checked_monitor.status.get('uptime_24h', 0),
                'uptime_7d': checked_monitor.status.get('uptime_7d', 0),
                'total_checks': checked_monitor.status.get('total_checks', 0),
                'successful_checks': checked_monitor.status.get('successful_checks', 0)
            }
            
            if hasattr(checked_monitor, '_save_history'):
                checked_monitor._save_history()
            
            time.sleep(1)
            
        except Exception as e:
            print(f"Error updating status for {monitor_id}: {e}")
            import traceback
            traceback.print_exc()
    
    if status_data:
        try:
            with open(STATUS_FILE, 'w') as f:
                json.dump(status_data, f, indent=2)
        except Exception as e:
            print(f"Error saving status file: {e}")
    else:
        print("No monitor data to save")

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
        
        if os.path.exists(STATUS_FILE):
            with open(STATUS_FILE, 'r') as f:
                monitors = json.load(f)
        else:
            monitors = {}
        
        monitors_by_category = {}
        for category in categories:
            cat_id = category.get('id', '') if isinstance(category, dict) else category
            monitors_by_category[cat_id] = []
        monitors_by_category['uncategorized'] = []
        
        for monitor_id, monitor_data in monitors.items():
            category = monitor_data.get('config', {}).get('category', 'uncategorized')
            if category not in monitors_by_category:
                category = 'uncategorized'
            monitors_by_category[category].append((monitor_id, monitor_data))
        
        categories_with_monitors = []
        for category in categories:
            if isinstance(category, dict):
                cat_id = category.get('id', '')
                category['monitors'] = monitors_by_category.get(cat_id, [])
                categories_with_monitors.append(category)
            else:
                categories_with_monitors.append({
                    'id': category,
                    'name': category,
                    'monitors': monitors_by_category.get(category, [])
                })
        
        if monitors_by_category.get('uncategorized'):
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
        if os.path.exists(STATUS_FILE):
            with open(STATUS_FILE, 'r') as f:
                return jsonify(json.load(f))
        return jsonify({})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/monitor/<monitor_id>/history')
def api_monitor_history(monitor_id):
    """API endpoint for monitor history"""
    try:
        if not monitor_id or monitor_id == 'undefined':
            return jsonify({"error": "Invalid monitor ID"}), 400
            
        if not os.path.exists(HISTORY_FILE):
            return jsonify([])
            
        with open(HISTORY_FILE, 'r') as f:
            try:
                history_data = json.load(f)
                return jsonify(history_data.get('history', {}).get(monitor_id, []))
            except json.JSONDecodeError:
                return jsonify({"error": "Invalid history data"}), 500
                
    except Exception as e:
        app.logger.error(f"Error fetching history for {monitor_id}: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/api/categories')
def api_categories():
    """API endpoint for categories"""
    try:
        config = load_monitors()
        categories = config.get('categories', [])
        
        if isinstance(categories, dict):
            categories = [{"id": k, "name": v, "separator": True} for k, v in categories.items()]
            
        return jsonify(categories)
    except Exception as e:
        app.logger.error(f"Error in categories endpoint: {str(e)}")
        return jsonify({"error": "Failed to load categories"}), 500

def start_monitoring_thread():
    """Start the monitoring thread"""
    monitor_thread = threading.Thread(target=run_checks, daemon=True)
    monitor_thread.start()
    print("Monitoring thread started")
    return monitor_thread

if __name__ == '__main__':
    os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
    monitor_thread = start_monitoring_thread()
    app.run(
        host=APP_CONFIG['app'].get('host', '0.0.0.0'),
        port=APP_CONFIG['app'].get('port', 5000),
        debug=APP_CONFIG['app'].get('debug', False)
    )
