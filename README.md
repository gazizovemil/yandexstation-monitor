# Yandex Station + Smart Plug → Zabbix

[English README](README.en.md) · [Docker Hub](https://hub.docker.com/r/gazizovemil/yandexstation-monitor)

**Один Docker-контейнер для мониторинга Яндекс Станции и умной розетки в Zabbix.** Не требует Home Assistant, SNMP на устройствах и установки Python в систему TNAS.

> Пример развёртывания проверен на TerraMaster TNAS с Zabbix 8.2, Станцией Мини 2 (`yandexmini_2`, YNDX-00020) и розеткой «Обогреватель». Поддержка других моделей зависит от Glagol и возможностей API.

## Возможности

| Показатель | Яндекс Станция | Умная розетка |
|---|---|---|
| Доступность | локальный Glagol, ICMP, TCP 1961 | облачный `online` |
| Включено / выключено | — | `on` |
| Громкость | `volume`, % | — |
| Воспроизведение | `playing`, `player_type` | — |
| Трек, исполнитель | `title`, `artist` | — |
| Состояние Алисы | `alice_state` | — |
| Напряжение, мощность, ток | — | `voltage_v`, `power_w`, `current_a` |
| Счётчик энергии | — | `energy_kwh` (если доступен) |

Станция: неофициальный Glagol через локальный WebSocket `wss://IP:1961`; авторизация через отдельный OAuth Яндекс Музыки (Device Code), облачный токен Quasar. Розетка: официальный Yandex Smart Home API с OAuth `iot:view`, только чтение. При временных ошибках HTTPS 1.0.1 повторяет запросы дважды.

> У розетки `online=1, on=0` означает: доступна, но выключена. Если она не в сети, состояние питания и измерения **не заменяются нулями**.

## Файлы репозитория

```text
monitor.py                      Сбор данных, OAuth и Zabbix sender
Dockerfile                      Python + зависимости внутри образа
compose.yaml                    Локальная тестовая сборка (НЕ production)
deploy/portainer-stack.yml      Готовый стек для Portainer
.github/workflows/tests.yml     Проверки на push/PR
.github/workflows/dockerhub.yml Публикация Docker Hub по тегам
templates/                      2 XML-шаблона для Zabbix 8.2
tests/                          Проверки без реальных OAuth-токенов
```

## Установка в Zabbix 8.2

1. Импортируй XML из `templates/` через **Data collection → Templates → Import**.
2. Создай хосты с точными техническими именами `Yandex Station Mini 2` и `Yandex Smart Plug`.
3. Привяжи соответствующие шаблоны. Станции нужен Agent-интерфейс с её IP **для простых сетевых проверок**, без установленного агента. Розетке интерфейс не нужен.
4. Убедись, что Zabbix Server доступен на TCP 10051, а trapper-ключи `yandex.station.state` и `yandex.plug.state` включены.
5. В **Allowed hosts** у trapper-элементов укажи реальный адрес источника; в примерной Docker-сети это `172.25.0.1` (шлюз сети Zabbix). При использовании макроса шаблона можно задать `{$TRAPPER.ALLOWED_HOSTS}` = `127.0.0.1,::1,172.25.0.1` для каждого хоста. Не копируй адрес, если у твоего Zabbix другая сеть.

## Авторизация устройств — один раз

Для нового NAS размести файлы проекта в отдельной папке и запусти тестовую сборку. **Не запускай локальную сборку параллельно с работающим Portainer Stack.**

```bash
docker compose build
docker compose run --rm yandexstation-monitor-dev python /app/monitor.py setup-station
docker compose run --rm yandexstation-monitor-dev python /app/monitor.py setup-plug
docker compose run --rm yandexstation-monitor-dev python /app/monitor.py probe all
```

- **Станция:** подтверди Device Code на `https://ya.ru/device`, выбери нужную колонку и IP. `Session_id` из браузера не нужен.
- **Розетка:** создай приложение на https://oauth.yandex.ru с правом `iot:view` (не `iot:control`), получи OAuth-токен и введи при `setup-plug`. Скрипт предложит выбрать розетку из аккаунта.
- **Zabbix:** адрес сервера `127.0.0.1` работает, если TCP 10051 опубликован на хосте TNAS; в иных условиях укажи доступный адрес. Технические имена хостов должны точно совпадать с Zabbix.

Проверка отправки:

```bash
docker compose run --rm yandexstation-monitor-dev python /app/monitor.py run all
```

Секреты лежат **только в каталоге `data/`**, который игнорируют Git и Docker Build. Не коммить его.

## Portainer (рабочий TNAS)

Готовый стек: [`deploy/portainer-stack.yml`](deploy/portainer-stack.yml). Его образ — `gazizovemil/yandexstation-monitor:1.0.1`.

У пользователя этого проекта уже настроена авторизация и создан каталог данных:

```text
/Volume1/docker/yandexstation-monitor/data/
```

Поэтому **не удаляй этот каталог при переносе**. При обновлении версии образа в существующем Portainer Stack просто поменяй `:1.0.0` на `:1.0.1` и нажми **Update the stack / Re-pull image**, когда версия `1.0.1` уже появилась в Docker Hub. Новый стек с тем же именем контейнера запускать нельзя.

Для диагностики работающего контейнера:

```bash
docker exec yandexstation-monitor python /app/monitor.py probe all
docker exec yandexstation-monitor python /app/monitor.py run all
docker logs --since 20m --timestamps yandexstation-monitor
```

Монитор опрашивает устройства каждые **300 секунд после окончания предыдущего цикла**. Ошибка одного устройства не мешает опросу второго. После кратковременной ошибки Яндекс API 1.0.1 предпринимает до 3 попыток с паузами 3 и 6 секунд.

## Публикация нового релиза

Репозиторий: `gazizovemil/yandexstation-monitor`; Docker Hub: `gazizovemil/yandexstation-monitor`.

Создай в GitHub репозитории в **Settings → Secrets and variables → Actions**:

- **Repository variable** `DOCKERHUB_USERNAME` = `gazizovemil`
- **Repository secret** `DOCKERHUB_TOKEN` = Docker Hub Personal Access Token с правом записи в репозиторий образа

Только Git-тег запускает публикацию. Обычный push в `main` выполняет тесты и **не меняет Docker Hub**.

```bash
git tag -a v1.0.1 -m "Release 1.0.1"
git push origin v1.0.1
```

Появятся образы `gazizovemil/yandexstation-monitor:1.0.1` и `:latest` для `linux/amd64` и `linux/arm64`. Версия `1.0.0` не перезаписывается.

## Безопасность

- Не коммить `data/`, OAuth-токены, cookie, `.env` и файлы с локальными параметрами.
- Не публикуй OAuth-токены в Issues и журналах GitHub Actions.
- Не изменяй порт `1961` и IP Станции без проверки доступности.
- Локальный Glagol — **неофициальный** API. При изменении его протокола обновление может потребоваться независимо от кода проекта.

Подробности: [SECURITY.md](SECURITY.md). История изменений: [CHANGELOG.md](CHANGELOG.md). Лицензия: [MIT](LICENSE).
