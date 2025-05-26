from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_socketio import SocketIO, emit
import http.client
import json
import gzip
import io
from datetime import datetime, timezone
import secrets
import string
import hashlib
import time
import os
import ssl
import threading
import queue

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
socketio = SocketIO(app, cors_allowed_origins="*")

# Global variables
monitoring_active = False
monitoring_thread = None
log_queue = queue.Queue()
current_config = {}

# Set expiration date (YYYY-MM-DD)
EXPIRATION_DATE = "2025-06-30"


def check_expiration():
    """Check if the program has expired."""
    current_date = datetime.now().strftime("%Y-%m-%d")
    if current_date > EXPIRATION_DATE:
        return False, f"Infocean's Program expired on {EXPIRATION_DATE}"
    return True, "Active"


# Default configuration (can be overridden by user input)
DEFAULT_CONFIG = {
    "API_KEY_ID": "15",
    "API_KEY": "Qchb9JDhxpluB7YdJvIGobBppZqsAuxEliBBC7U8RXMcqQzqPbbCZrvRPsHrG1lKU7BQ1HzjMJutZ8DzruFE521wxQCjBa08jK9DOouwaD63t1EIlr27zWK3XTll8tuq",
    "HOST": "api-dch.xdr.sg.paloaltonetworks.com",
    "ENDPOINT": "/public_api/v1/incidents/get_incidents"
}

LOG_FILE = "./logs/pa.json"


def generate_auth_headers(api_key_id, api_key):
    """Generate the proper authentication headers"""
    nonce = "".join([secrets.choice(string.ascii_letters + string.digits) for _ in range(64)])
    timestamp = int(datetime.now(timezone.utc).timestamp() * 1000)
    auth_key = f"{api_key}{nonce}{timestamp}".encode("utf-8")
    api_key_hash = hashlib.sha256(auth_key).hexdigest()

    return {
        "x-xdr-timestamp": str(timestamp),
        "x-xdr-nonce": nonce,
        "x-xdr-auth-id": str(api_key_id),
        "Authorization": api_key_hash,
        "Accept-Encoding": "gzip",
        "Content-Type": "application/json"
    }


def write_to_log_file(data, log_file: str):
    """Write data to log file with timestamp"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not isinstance(data, str):
        data = json.dumps(data, indent=2)

    log_entry = f"[{timestamp}] {data}\n"
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    with open(log_file, "a") as f:
        f.write(log_entry)


def build_payload_from_config(config):
    """Build API payload from web configuration"""
    payload = {
        "request_data": {
            "search_from": int(config.get('search_from', 0)),
            "search_to": int(config.get('search_to', 100)),
            "sort": {
                "field": config.get('sort_field', 'incident_id'),
                "keyword": config.get('sort_order', 'desc')
            }
        }
    }

    filters = []

    # Severity filter
    if config.get('severity_filter') and config['severity_filter'] != 'all':
        severities = [int(s) for s in config['severity_filter'].split(',') if s.isdigit()]
        if severities:
            filters.append({
                "field": "severity",
                "operator": "in",
                "value": severities
            })

    # Status filter
    if config.get('status_filter') and config['status_filter'] != 'all':
        status_map = {
            "1": "new",
            "2": "under_investigation",
            "3": "resolved_threat_handled",
            "4": "resolved_known_issue",
            "5": "resolved_duplicate",
            "6": "resolved_false_positive",
            "7": "resolved_other"
        }
        statuses = [status_map[s] for s in config['status_filter'].split(',') if s in status_map]
        if statuses:
            filters.append({
                "field": "status",
                "operator": "in",
                "value": statuses
            })

    # Time filter
    if config.get('time_filter') and config['time_filter'] != 'all':
        current_time = datetime.now()
        time_ranges = {
            "1": 1,  # 1 hour
            "2": 24,  # 24 hours
            "3": 168,  # 7 days
            "4": 720,  # 30 days
        }

        if config['time_filter'] in time_ranges:
            hours_back = time_ranges[config['time_filter']]
            start_time = current_time.timestamp() - (hours_back * 3600)
            start_timestamp = int(start_time * 1000)

            filters.append({
                "field": "creation_time",
                "operator": "gte",
                "value": start_timestamp
            })

    # Host filter
    if config.get('host_filter') and config['host_filter'] != 'all':
        hosts = [h.strip() for h in config['host_filter'].split(',') if h.strip()]
        if hosts:
            filters.append({
                "field": "hosts",
                "operator": "in",
                "value": hosts
            })

    # Description filter
    if config.get('description_filter') and config['description_filter'] != 'all':
        filters.append({
            "field": "description",
            "operator": "contains",
            "value": [config['description_filter']]
        })

    if filters:
        payload["request_data"]["filters"] = filters

    return payload


def monitoring_worker(config):
    """Background worker for monitoring incidents"""
    global monitoring_active

    # Extract API credentials from config
    api_key_id = config.get('api_key_id', DEFAULT_CONFIG['API_KEY_ID'])
    api_key = config.get('api_key', DEFAULT_CONFIG['API_KEY'])
    host = config.get('host', DEFAULT_CONFIG['HOST'])
    endpoint = config.get('endpoint', DEFAULT_CONFIG['ENDPOINT'])

    payload = build_payload_from_config(config)
    interval = int(config.get('polling_interval', 60))
    processed_logs = set()

    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    while monitoring_active:
        try:
            # Emit status update
            socketio.emit('status_update', {
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'message': f'Polling {host} for incidents...',
                'type': 'info'
            })

            conn = http.client.HTTPSConnection(host, context=ssl_context)
            headers = generate_auth_headers(api_key_id, api_key)

            conn.request("POST", endpoint, body=json.dumps(payload), headers=headers)
            res = conn.getresponse()

            data = res.read()
            if res.getheader('Content-Encoding') == 'gzip':
                with gzip.GzipFile(fileobj=io.BytesIO(data)) as f:
                    response = json.loads(f.read().decode('utf-8'))
            else:
                response = json.loads(data.decode('utf-8'))

            # Check for duplicates
            log_hash = hashlib.sha256(json.dumps(response).encode('utf-8')).hexdigest()
            if log_hash not in processed_logs:
                processed_logs.add(log_hash)

                # Write to log file
                write_to_log_file(response, LOG_FILE)

                # Emit new incident data
                if 'reply' in response and 'incidents' in response['reply']:
                    incidents = response['reply']['incidents']
                    incident_count = len(incidents)

                    socketio.emit('new_incidents', {
                        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'count': incident_count,
                        'incidents': incidents[:10],  # Send first 10 incidents
                        'response_status': res.status
                    })

                    socketio.emit('status_update', {
                        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'message': f'Found {incident_count} incidents',
                        'type': 'success'
                    })
                else:
                    socketio.emit('status_update', {
                        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'message': 'No incidents found',
                        'type': 'warning'
                    })
            else:
                socketio.emit('status_update', {
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'message': 'Duplicate log detected, skipping...',
                    'type': 'info'
                })

            conn.close()

        except Exception as e:
            error_msg = f"Error during API call: {str(e)}"
            socketio.emit('status_update', {
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'message': error_msg,
                'type': 'error'
            })
            write_to_log_file(error_msg, LOG_FILE)

        # Wait for next interval
        for i in range(interval):
            if not monitoring_active:
                break
            time.sleep(1)


@app.route('/')
def index():
    """Main dashboard page"""
    is_valid, status = check_expiration()
    return render_template('index.html',
                           expiration_status=status,
                           is_valid=is_valid,
                           monitoring_active=monitoring_active)


@app.route('/config')
def config():
    """Configuration page"""
    return render_template('config.html', default_config=DEFAULT_CONFIG)


@app.route('/monitor')
def monitor():
    """Real-time monitoring page"""
    return render_template('monitor.html', config=current_config)


@app.route('/api/start_monitoring', methods=['POST'])
def start_monitoring():
    """Start monitoring with given configuration"""
    global monitoring_active, monitoring_thread, current_config

    is_valid, status = check_expiration()
    if not is_valid:
        return jsonify({'success': False, 'message': status})

    if monitoring_active:
        return jsonify({'success': False, 'message': 'Monitoring already active'})

    config = request.json
    current_config = config

    # Validate required API credentials
    required_fields = ['api_key_id', 'api_key', 'host']
    missing_fields = [field for field in required_fields if not config.get(field)]

    if missing_fields:
        return jsonify({
            'success': False,
            'message': f'Missing required fields: {", ".join(missing_fields)}'
        })

    monitoring_active = True
    monitoring_thread = threading.Thread(target=monitoring_worker, args=(config,))
    monitoring_thread.daemon = True
    monitoring_thread.start()

    return jsonify({'success': True, 'message': 'Monitoring started'})


@app.route('/api/stop_monitoring', methods=['POST'])
def stop_monitoring():
    """Stop monitoring"""
    global monitoring_active

    monitoring_active = False
    return jsonify({'success': True, 'message': 'Monitoring stopped'})


@app.route('/api/test_connection', methods=['POST'])
def test_connection():
    """Test API connection with provided credentials"""
    try:
        data = request.json or {}

        # Use provided credentials or defaults
        api_key_id = data.get('api_key_id', DEFAULT_CONFIG['API_KEY_ID'])
        api_key = data.get('api_key', DEFAULT_CONFIG['API_KEY'])
        host = data.get('host', DEFAULT_CONFIG['HOST'])
        endpoint = data.get('endpoint', DEFAULT_CONFIG['ENDPOINT'])

        # Validate required fields
        if not all([api_key_id, api_key, host]):
            return jsonify({
                'success': False,
                'message': 'Missing required API credentials (API Key ID, API Key, or Host)'
            })

        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        conn = http.client.HTTPSConnection(host, context=ssl_context, timeout=10)
        headers = generate_auth_headers(api_key_id, api_key)

        test_payload = {
            "request_data": {
                "search_from": 0,
                "search_to": 1
            }
        }

        conn.request("POST", endpoint, body=json.dumps(test_payload), headers=headers)
        res = conn.getresponse()
        response_data = res.read()
        conn.close()

        # Try to parse response
        try:
            if res.getheader('Content-Encoding') == 'gzip':
                with gzip.GzipFile(fileobj=io.BytesIO(response_data)) as f:
                    parsed_response = json.loads(f.read().decode('utf-8'))
            else:
                parsed_response = json.loads(response_data.decode('utf-8'))

            # Check if response indicates success
            if res.status == 200:
                return jsonify({
                    'success': True,
                    'message': f'Connection successful! Server responded with status {res.status}',
                    'status_code': res.status,
                    'response_preview': str(parsed_response)[:200] + '...' if len(str(parsed_response)) > 200 else str(
                        parsed_response)
                })
            else:
                return jsonify({
                    'success': False,
                    'message': f'Server responded with status {res.status}. Check your credentials.',
                    'status_code': res.status,
                    'response_preview': str(parsed_response)[:200] + '...' if len(str(parsed_response)) > 200 else str(
                        parsed_response)
                })
        except json.JSONDecodeError:
            return jsonify({
                'success': False,
                'message': f'Invalid response format from server (Status: {res.status})',
                'status_code': res.status
            })

    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Connection failed: {str(e)}'
        })


@app.route('/api/get_logs')
def get_logs():
    """Get recent log entries"""
    try:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, 'r') as f:
                lines = f.readlines()
                # Return last 50 lines
                recent_lines = lines[-50:] if len(lines) > 50 else lines
                return jsonify({
                    'success': True,
                    'logs': [line.strip() for line in recent_lines]
                })
        else:
            return jsonify({
                'success': True,
                'logs': []
            })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        })


@app.route('/api/monitoring_status')
def monitoring_status():
    """Get current monitoring status"""
    return jsonify({
        'active': monitoring_active,
        'config': current_config if monitoring_active else {}
    })


@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    emit('status_update', {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'message': 'Connected to monitoring service',
        'type': 'info'
    })


@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    print('Client disconnected')


if __name__ == '__main__':
    # Create logs directory if it doesn't exist
    os.makedirs('logs', exist_ok=True)

    print("=== Palo Alto XDR Web Monitor ===")
    print("Starting web application on http://localhost:5050")
    print("Press Ctrl+C to stop")

    # Fix for the Werkzeug error - use allow_unsafe_werkzeug=True
    socketio.run(app, host='0.0.0.0', port=5001, debug=False, allow_unsafe_werkzeug=True)
