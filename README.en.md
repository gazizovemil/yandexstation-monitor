# Yandex Station and Smart Plug → Zabbix

[Русская документация](README.md) · [Docker Hub](https://hub.docker.com/r/gazizovemil/yandexstation-monitor)

One Docker container for monitoring a Yandex Station (local Glagol) and Yandex Smart Plug (official cloud API) in Zabbix 8.2. No Home Assistant, host Python or SNMP required.

- Station: Glagol WebSocket on TCP 1961. Authorize using Yandex Music OAuth Device Code at https://ya.ru/device; Yandex's unofficial protocol may change.
- Plug: official `https://api.iot.yandex.net/v1.0` with read-only `iot:view` OAuth scope. Collect online/on status and available power/voltage/current readings.
- Send JSON using Zabbix sender/trapper over TCP 10051; two templates are included under `templates/`.
- Retries transient HTTPS/TLS timeouts, keeps each device independent, polls every five minutes after each completed cycle.

## Setup

Import both XML templates from `templates/`, create two Zabbix hosts named exactly `Yandex Station Mini 2` and `Yandex Smart Plug`, link templates, and configure Zabbix trapper allowed hosts to include your Docker gateway IP. The Station host needs an IP interface for optional ICMP/TCP checks, but not an agent.

For local development only (do not launch alongside a production Portainer stack):

```bash
docker compose build
docker compose run --rm yandexstation-monitor-dev python /app/monitor.py setup-station
docker compose run --rm yandexstation-monitor-dev python /app/monitor.py setup-plug
docker compose run --rm yandexstation-monitor-dev python /app/monitor.py probe all
```

Production Portainer YAML: [`deploy/portainer-stack.yml`](deploy/portainer-stack.yml). It preserves the existing configuration at `/Volume1/docker/yandexstation-monitor/data`. Never commit or publish that directory: it contains OAuth access tokens.

## Docker Hub releases

In GitHub repository settings, configure `DOCKERHUB_USERNAME` as repository variable (`gazizovemil`) and `DOCKERHUB_TOKEN` as repository secret with Docker Hub write permission. Pushing a `v1.0.1` Git tag builds and pushes `gazizovemil/yandexstation-monitor:1.0.1` and `:latest` via GitHub Actions. Ordinary branch pushes only run tests.

MIT license. This is an independent community project, not affiliated with Yandex or Zabbix.
