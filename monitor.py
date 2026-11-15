#!/usr/bin/env python3
"""Yandex Station + Smart Plug -> Zabbix 8.2. Read-only monitoring.

Station: Yandex Glagol (unofficial protocol; Yandex Music OAuth).
Smart plug: official Yandex IoT API (OAuth scope iot:view).

No host-level packages. Designed for Docker with /data volume.
"""
from __future__ import annotations

import argparse
import asyncio
from getpass import getpass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import ssl
import struct
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen
from uuid import uuid4

try:
    import websockets
except ImportError:
    websockets = None

DATA = Path(os.environ.get('YANDEX_MONITOR_DATA_DIR', '/data'))
STATION_CONF = DATA / 'config.json'  # compatible with the previous monitor
STATION_COOKIE = DATA / '.session_id'  # Legacy file (not used by current OAuth Glagol mode)
STATION_OAUTH = DATA / '.station_music_token'
PLUG_CONF = DATA / 'plug.json'
PLUG_OAUTH = DATA / '.iot_view_token'
DEFAULT_STATION_IP = '192.168.1.55'
DEFAULT_STATION_HOST = 'Yandex Station Mini 2'
DEFAULT_PLUG_HOST = 'Yandex Smart Plug'
DEFAULT_ZABBIX = '127.0.0.1'
QUASAR_LIST = 'https://quasar.yandex.net/glagol/device_list'
QUASAR_TOKEN = 'https://quasar.yandex.net/glagol/token'
IOT_API = 'https://api.iot.yandex.net/v1.0'


def save_secret(path: Path, secret: str) -> None:
    DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(DATA, 0o700)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as out:
        out.write(secret.strip() + '\n')
    os.chmod(path, 0o600)


def save_config(path: Path, data: dict) -> None:
    save_secret(path, json.dumps(data, ensure_ascii=False, indent=2))


def read_secret(path: Path) -> str:
    return path.read_text(encoding='utf-8').strip()


def read_config(path: Path) -> dict:
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError('Конфигурация должна быть JSON-объектом')
    return data


def api_json(url: str, *, cookie: str | None = None, oauth: str | None = None, oauth_scheme: str = 'Bearer') -> dict:
    if bool(cookie) == bool(oauth):
        raise ValueError('Нужен ровно один способ авторизации')
    headers = {'Accept': 'application/json', 'User-Agent': 'TNAS-Yandex-Zabbix/2.0'}
    if cookie is not None:
        headers['Cookie'] = 'Session_id=' + cookie
    else:
        headers['Authorization'] = oauth_scheme + ' ' + oauth
    req = Request(url, headers=headers)
    # Transient cloud errors (especially TLS handshake timeouts) are retried.
    # HTTP 401/403 indicate bad permissions: do not retry those.
    for attempt in range(3):
        try:
            with urlopen(req, timeout=15) as response:
                result = json.load(response)
            break
        except HTTPError as error:
            if error.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(3 * (attempt + 1))
                continue
            raise RuntimeError(f'Яндекс API: HTTP {error.code} (проверь токен, срок действия и разрешения)') from None
        except (URLError, TimeoutError, OSError, ssl.SSLError) as error:
            if attempt < 2:
                time.sleep(3 * (attempt + 1))
                continue
            reason = getattr(error, 'reason', error)
            raise RuntimeError(f'Яндекс API недоступен после 3 попыток: {reason}') from None
    if not isinstance(result, dict):
        raise RuntimeError('Яндекс API вернул неожиданный формат ответа')
    if result.get('status') == 'error':
        raise RuntimeError(f'Яндекс API отклонил запрос (request_id: {result.get("request_id", "нет")})')
    return result


def choose_device(devices: list[dict], label: str) -> dict:
    if not devices:
        raise RuntimeError(f'В аккаунте не найдены устройства: {label}')
    print(f'\nДоступные устройства ({label}):')
    for index, device in enumerate(devices, start=1):
        print(f'  {index}. {device.get("name") or "Без названия"} — {device.get("type") or device.get("platform") or "тип не указан"}')
    if len(devices) == 1:
        print('Выбрано единственное найденное устройство')
        return devices[0]
    while True:
        selected = input('Номер устройства: ').strip()
        if selected.isdigit() and 1 <= int(selected) <= len(devices):
            return devices[int(selected) - 1]
        print('Неверный номер.')


def ask_zabbix(previous: dict | None, default_host: str) -> dict:
    previous = previous or {}
    server = input(f'Zabbix Server [{previous.get("zabbix_server", DEFAULT_ZABBIX)}]: ').strip() or previous.get('zabbix_server', DEFAULT_ZABBIX)
    port = previous.get('zabbix_port', 10051)
    host = input(f'Техническое имя хоста Zabbix [{previous.get("zabbix_host", default_host)}]: ').strip() or previous.get('zabbix_host', default_host)
    return {'zabbix_server': server, 'zabbix_port': int(port), 'zabbix_host': host}


def get_station_oauth_interactively() -> str:
    """Acquire a scoped music OAuth token by user-confirmed Device Flow.

    No account cookies or password are needed. The token can access music
    and Glagol APIs, so keep it private; it is not an iot:view-only token.
    """
    if STATION_OAUTH.is_file():
        answer = input('Ранее сохранён токен Станции. Использовать его? [Y/n]: ').strip().lower()
        if answer in ('', 'y', 'yes', 'д', 'да'):
            return read_secret(STATION_OAUTH)
    print('Авторизация Станции: Яндекс Музыка OAuth (Device Code).')
    print('Нужен тот же аккаунт Яндекса, к которому привязана колонка.')
    print('Для ручного ввода готового OAuth-токена нажми 1; для входа через код — Enter.')
    mode = input('Способ [Enter/1]: ').strip()
    if mode == '1':
        token = getpass('OAuth-токен Яндекс Музыки (ввод скрыт): ').strip()
        if not token:
            raise RuntimeError('Пустой OAuth-токен')
        return token
    try:
        from yandex_music import Client
    except ImportError:
        raise RuntimeError('В образе нет yandex-music. Выполни docker compose build --no-cache') from None
    print('Ожидается код подтверждения входа от Яндекса...')

    def on_code(code) -> None:
        print('\nОткрой на телефоне или компьютере:', code.verification_url, flush=True)
        print('Введи код:', code.user_code, flush=True)
        print('Подтверди доступ и вернись к терминалу.\n', flush=True)

    auth = Client().device_auth(on_code=on_code)
    token = getattr(auth, 'access_token', None)
    if not isinstance(token, str) or not token:
        raise RuntimeError('Яндекс не вернул OAuth access_token')
    return token


def setup_station() -> None:
    print('Настройка Станции по Glagol без Session_id. Используем OAuth Яндекс Музыки.')
    previous = read_config(STATION_CONF) if STATION_CONF.exists() else {}
    token = get_station_oauth_interactively()
    answer = api_json(QUASAR_LIST, oauth=token, oauth_scheme='OAuth')
    devices = [d for d in answer.get('devices', []) if isinstance(d, dict) and d.get('id') and d.get('platform')]
    station = choose_device(devices, 'Яндекс Станции')
    ip = input(f'IP Станции [{previous.get("station_ip", DEFAULT_STATION_IP)}]: ').strip() or previous.get('station_ip', DEFAULT_STATION_IP)
    conf = {
        'station_ip': ip,
        'device_id': station['id'],
        'platform': station['platform'],
        **ask_zabbix(previous, DEFAULT_STATION_HOST),
    }
    save_secret(STATION_OAUTH, token)
    save_config(STATION_CONF, conf)
    print('Станция настроена. Проверь: python /app/monitor.py probe station')


def setup_plug() -> None:
    print('Настройка розетки через официальный API Яндекса. Нужен OAuth-токен ТОЛЬКО с iot:view.')
    prev = read_config(PLUG_CONF) if PLUG_CONF.exists() else {}
    token = getpass('OAuth-токен с iot:view (ввод скрыт): ').strip()
    if not token:
        if not PLUG_OAUTH.exists():
            raise RuntimeError('Не задан OAuth-токен; сохранённого токена нет')
        token = read_secret(PLUG_OAUTH)
    response = api_json(IOT_API + '/user/info', oauth=token)
    devices = response.get('devices')
    if not isinstance(devices, list):
        raise RuntimeError('API не вернул массив devices: проверь разрешение iot:view')
    sockets = [d for d in devices if isinstance(d, dict) and d.get('id') and d.get('type') == 'devices.types.socket']
    plug = choose_device(sockets, 'умные розетки')
    defaults = dict(prev)
    if not defaults and STATION_CONF.exists():
        station_conf = read_config(STATION_CONF)
        defaults['zabbix_server'] = station_conf.get('zabbix_server', DEFAULT_ZABBIX)
        defaults['zabbix_port'] = station_conf.get('zabbix_port', 10051)
    zbx = ask_zabbix(defaults, DEFAULT_PLUG_HOST)
    new = {'device_id': plug['id'], 'name': plug.get('name') or DEFAULT_PLUG_HOST, **zbx}
    save_secret(PLUG_OAUTH, token)
    save_config(PLUG_CONF, new)
    print('Розетка настроена. Проверь: python /app/monitor.py probe plug')


def normalize_plug(raw: dict) -> dict:
    if raw.get('status') not in (None, 'ok'):
        raise RuntimeError('Яндекс API не подтвердил статус устройства')
    state = raw.get('state')
    if state not in ('online', 'offline'):
        raise RuntimeError(f'Неизвестный статус розетки: {state!r}')
    values: dict = {
        'online': int(state == 'online'),
        'name': str(raw.get('name') or 'Розетка'),
        'timestamp': int(time.time()),
    }
    # Offline does NOT mean Off. Keep them separate.
    if state == 'online':
        for cap in raw.get('capabilities') or []:
            if not isinstance(cap, dict) or cap.get('type') != 'devices.capabilities.on_off':
                continue
            if cap.get('retrievable') is False:
                continue
            s = cap.get('state')
            if isinstance(s, dict) and isinstance(s.get('value'), bool):
                values['on'] = int(s['value'])
                break
    for prop in raw.get('properties') or []:
        if not isinstance(prop, dict) or prop.get('retrievable') is False or state != 'online':
            continue
        if prop.get('type') != 'devices.properties.float':
            continue
        parameters = prop.get('parameters') or {}
        st = prop.get('state') or {}
        if not isinstance(parameters, dict) or not isinstance(st, dict):
            continue
        instance = st.get('instance') or parameters.get('instance')
        num = st.get('value')
        if not isinstance(num, (int, float)) or isinstance(num, bool):
            continue
        if instance == 'power':
            values['power_w'] = float(num)
        elif instance == 'voltage':
            values['voltage_v'] = float(num)
        elif instance == 'amperage':
            values['current_a'] = float(num)
        elif instance == 'electricity_meter':
            unit = parameters.get('unit')
            if unit == 'unit.kilowatt_hour':
                values['energy_kwh'] = float(num)
            elif unit == 'unit.watt_hour':
                values['energy_kwh'] = float(num) / 1000.0
    return values


def get_plug() -> tuple[dict, dict]:
    conf = read_config(PLUG_CONF)
    token = read_secret(PLUG_OAUTH)
    device_id = quote(str(conf['device_id']), safe='')
    response = api_json(IOT_API + '/devices/' + device_id, oauth=token)
    return conf, normalize_plug(response)


def station_token(conf: dict, music_oauth: str) -> str:
    query = urlencode({'device_id': conf['device_id'], 'platform': conf['platform']})
    response = api_json(QUASAR_TOKEN + '?' + query, oauth=music_oauth, oauth_scheme='OAuth')
    token = response.get('token')
    if not isinstance(token, str) or not token:
        raise RuntimeError('Quasar не вернул Glagol-токен')
    return token


async def station_state(ip: str, token: str) -> dict:
    if websockets is None:
        raise RuntimeError('Для Glagol нужна библиотека websockets внутри Docker')
    tls = ssl.create_default_context()
    # Only the local WSS speaker uses a self-signed TLS cert.
    tls.check_hostname = False
    tls.verify_mode = ssl.CERT_NONE
    async with websockets.connect(f'wss://{ip}:1961', ssl=tls, open_timeout=6, close_timeout=3) as ws:
        await ws.send(json.dumps({
            'conversationToken': token,
            'id': str(uuid4()),
            'sentTime': int(time.time() * 1000),
            'payload': {'command': 'ping'},
        }, separators=(',', ':')))
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            remaining = max(0.2, deadline - time.monotonic())
            try:
                message = json.loads(await asyncio.wait_for(ws.recv(), remaining))
            except asyncio.TimeoutError:
                break
            if not isinstance(message, dict):
                continue
            state = message.get('state')
            if isinstance(state, dict):
                return state
            payload = message.get('payload')
            if isinstance(payload, dict) and isinstance(payload.get('state'), dict):
                return payload['state']
        raise RuntimeError('Glagol не прислал состояние за 12 секунд')


def normalize_station(state: dict) -> dict:
    player = state.get('playerState')
    player = player if isinstance(player, dict) else {}
    extra = player.get('extra')
    extra = extra if isinstance(extra, dict) else {}
    data: dict = {'ok': 1, 'timestamp': int(time.time())}
    volume = state.get('volume')
    if isinstance(volume, (int, float)) and not isinstance(volume, bool):
        data['volume'] = round(max(0, min(1, volume)) * 100)
    if isinstance(state.get('playing'), bool):
        data['playing'] = int(state['playing'])
    data['title'] = str(player.get('title') or extra.get('title') or '')
    data['artist'] = str(player.get('subtitle') or extra.get('artist') or '')
    data['player_type'] = str(player.get('playerType') or 'unknown')
    data['alice_state'] = str(state.get('aliceState') or 'unknown')
    return data


def get_station() -> tuple[dict, dict]:
    conf = read_config(STATION_CONF)
    music_oauth = read_secret(STATION_OAUTH)
    token = station_token(conf, music_oauth)
    state = asyncio.run(station_state(str(conf.get('station_ip', DEFAULT_STATION_IP)), token))
    return conf, normalize_station(state)


def recv_exact(sock: socket.socket, length: int) -> bytes:
    buffer = bytearray()
    while len(buffer) < length:
        chunk = sock.recv(length - len(buffer))
        if not chunk:
            raise RuntimeError('Zabbix закрыл соединение')
        buffer.extend(chunk)
    return bytes(buffer)


def send_zabbix(conf: dict, key: str, data: dict) -> None:
    payload = {'request': 'sender data', 'data': [{
        'host': conf['zabbix_host'],
        'key': key,
        'value': json.dumps(data, ensure_ascii=False, separators=(',', ':')),
    }]}
    raw = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    address = conf.get('zabbix_server') or DEFAULT_ZABBIX
    port = int(conf.get('zabbix_port', 10051))
    with socket.create_connection((address, port), timeout=8) as sock:
        sock.settimeout(8)
        sock.sendall(b'ZBXD\x01' + struct.pack('<Q', len(raw)) + raw)
        header = recv_exact(sock, 13)
        if header[:5] != b'ZBXD\x01':
            raise RuntimeError('Неправильный заголовок ответа Zabbix')
        length = struct.unpack('<Q', header[5:])[0]
        if length > 1048576:
            raise RuntimeError('Слишком большой ответ Zabbix')
        answer = json.loads(recv_exact(sock, length))
    if answer.get('response') != 'success' or 'failed: 0' not in answer.get('info', ''):
        raise RuntimeError('Zabbix отклонил данные. Проверь имя хоста, ключ и доступность trapper item')


def get_modes(choice: str) -> list[str]:
    configured = []
    if STATION_CONF.is_file() and STATION_OAUTH.is_file():
        configured.append('station')
    if PLUG_CONF.is_file() and PLUG_OAUTH.is_file():
        configured.append('plug')
    if choice == 'all':
        if not configured:
            raise RuntimeError('Ни одно устройство не настроено')
        return configured
    if choice not in configured:
        raise RuntimeError(f'Устройство {choice} ещё не настроено')
    return [choice]


def once(mode: str, *, send: bool) -> int:
    failures = 0
    for device in get_modes(mode):
        try:
            conf, state = get_station() if device == 'station' else get_plug()
            if send:
                key = 'yandex.station.state' if device == 'station' else 'yandex.plug.state'
                send_zabbix(conf, key, state)
                print(f'{device}: данные доставлены в Zabbix ({conf["zabbix_host"]})', flush=True)
            else:
                print(device + ': ' + json.dumps(state, ensure_ascii=False, indent=2), flush=True)
        except Exception as error:
            # Do not print access tokens, cookies, API response bodies or auth headers.
            print(f'{device}: ERROR: {error}', file=sys.stderr, flush=True)
            failures += 1
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description='Yandex Station + Smart Plug monitor for Zabbix')
    parser.add_argument('command', choices=['setup-station', 'setup-plug', 'probe', 'run', 'loop'])
    parser.add_argument('device', nargs='?', choices=['station', 'plug', 'all'], default='all')
    args = parser.parse_args()
    try:
        if args.command == 'setup-station':
            setup_station()
            return 0
        if args.command == 'setup-plug':
            setup_plug()
            return 0
        if args.command in ('probe', 'run'):
            return once(args.device, send=args.command == 'run')
        if args.command == 'loop':
            print('monitor: цикл запущен, опрос каждые 300 секунд после завершения предыдущего', flush=True)
            while True:
                start = time.monotonic()
                started_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
                print(f'monitor: начало цикла UTC {started_at}', flush=True)
                try:
                    status = once('all', send=True)
                    print(f'monitor: цикл завершён, status={status}, elapsed={time.monotonic()-start:.1f}s', flush=True)
                except Exception as error:
                    print(f'monitor: ERROR: {error}', file=sys.stderr, flush=True)
                time.sleep(300)
    except KeyboardInterrupt:
        return 130
    except (RuntimeError, OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
