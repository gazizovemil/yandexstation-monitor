import io
import json
import socket
import threading
import unittest
from unittest.mock import patch

import monitor


class NormalizePlugTests(unittest.TestCase):
    def test_online_with_metering(self):
        raw = {
            'state': 'online', 'name': 'Обогреватель',
            'capabilities': [{
                'type': 'devices.capabilities.on_off',
                'state': {'instance': 'on', 'value': False},
            }],
            'properties': [
                {'type': 'devices.properties.float', 'state': {'instance': 'voltage', 'value': 229.5}},
                {'type': 'devices.properties.float', 'state': {'instance': 'power', 'value': 0}},
                {'type': 'devices.properties.float', 'state': {'instance': 'amperage', 'value': 0}},
            ],
        }
        value = monitor.normalize_plug(raw)
        self.assertEqual(value['online'], 1)
        self.assertEqual(value['on'], 0)
        self.assertEqual(value['voltage_v'], 229.5)
        self.assertEqual(value['power_w'], 0.0)
        self.assertEqual(value['current_a'], 0.0)

    def test_offline_does_not_invent_power_state(self):
        raw = {
            'state': 'offline', 'name': 'Обогреватель',
            'capabilities': [{'type': 'devices.capabilities.on_off', 'state': {'value': False}}],
            'properties': [{'type': 'devices.properties.float', 'state': {'instance': 'power', 'value': 0}}],
        }
        value = monitor.normalize_plug(raw)
        self.assertEqual(value['online'], 0)
        self.assertNotIn('on', value)
        self.assertNotIn('power_w', value)

    def test_invalid_status_rejected(self):
        with self.assertRaises(RuntimeError):
            monitor.normalize_plug({'state': 'unknown'})


class NormalizeStationTests(unittest.TestCase):
    def test_state(self):
        state = {
            'volume': 0.5,
            'playing': False,
            'aliceState': 'IDLE',
            'playerState': {'title': 'Someday', 'subtitle': 'Fraunhofer Diffraction', 'playerType': 'music_thin'},
        }
        result = monitor.normalize_station(state)
        self.assertEqual(result['volume'], 50)
        self.assertEqual(result['playing'], 0)
        self.assertEqual(result['title'], 'Someday')
        self.assertEqual(result['alice_state'], 'IDLE')

    def test_missing_values_stay_missing(self):
        result = monitor.normalize_station({})
        self.assertNotIn('volume', result)
        self.assertNotIn('playing', result)


class RetryTests(unittest.TestCase):
    def test_timeout_retried_and_succeeds(self):
        class Response:
            def __enter__(self):
                return io.BytesIO(b'{"devices": []}')
            def __exit__(self, *args):
                return False

        with patch.object(monitor, 'urlopen', side_effect=[TimeoutError('handshake timeout'), Response()]) as request, \
             patch.object(monitor.time, 'sleep') as sleep:
            result = monitor.api_json('https://api.iot.yandex.net/v1.0/user/info', oauth='local-test-token')
        self.assertEqual(result, {'devices': []})
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once_with(3)

    def test_http_403_is_not_retried(self):
        from urllib.error import HTTPError
        with patch.object(monitor, 'urlopen', side_effect=HTTPError('https://example.invalid', 403, 'Forbidden', {}, None)) as request, \
             patch.object(monitor.time, 'sleep') as sleep:
            with self.assertRaisesRegex(RuntimeError, 'HTTP 403'):
                monitor.api_json('https://api.iot.yandex.net/v1.0/user/info', oauth='local-test-token')
        request.assert_called_once()
        sleep.assert_not_called()


class ZabbixTests(unittest.TestCase):
    def test_sender_protocol(self):
        ready = threading.Event()
        received = []
        errors = []
        srv = socket.socket()
        srv.bind(('127.0.0.1', 0))
        port = srv.getsockname()[1]
        srv.listen(1)

        def server():
            try:
                ready.set()
                conn, _ = srv.accept()
                with conn:
                    header = monitor.recv_exact(conn, 13)
                    self.assertEqual(header[:5], b'ZBXD\x01')
                    length = int.from_bytes(header[5:], 'little')
                    received.append(json.loads(monitor.recv_exact(conn, length)))
                    reply = json.dumps({'response': 'success', 'info': 'processed: 1; failed: 0; total: 1; seconds spent: 0.001'}).encode()
                    conn.sendall(b'ZBXD\x01' + len(reply).to_bytes(8, 'little') + reply)
            except Exception as exc:
                errors.append(exc)
            finally:
                srv.close()

        worker = threading.Thread(target=server, daemon=True)
        worker.start()
        ready.wait(2)
        monitor.send_zabbix({'zabbix_server': '127.0.0.1', 'zabbix_port': port, 'zabbix_host': 'Yandex Smart Plug'},
                            'yandex.plug.state', {'online': 1, 'on': 0})
        worker.join(3)
        self.assertFalse(errors)
        self.assertEqual(received[0]['request'], 'sender data')
        self.assertEqual(received[0]['data'][0]['key'], 'yandex.plug.state')


if __name__ == '__main__':
    unittest.main()
