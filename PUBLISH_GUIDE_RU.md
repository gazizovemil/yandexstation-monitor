# Первое размещение на GitHub — точные команды для TNAS

> **Важно:** это отдельная папка с исходниками, а не твой работающий каталог `/Volume1/docker/yandexstation-monitor/data`. Не удаляй контейнер `yandexstation-monitor` из Portainer.

## 1. Создай репозиторий на GitHub

Перейди на https://github.com/new. Войди как **gazizovemil**. Имя репозитория: **yandexstation-monitor**. Выбери `Public` (или `Private`, если пока не хочешь публиковать исходники). **Не добавляй** README, `.gitignore` и License через веб-интерфейс: они уже включены в архив.

Ожидаемый URL после создания:

https://github.com/gazizovemil/yandexstation-monitor

## 2. Скопируй архив на TNAS

Распакуй проект целиком в **новый** каталог:

```text
/Volume1/docker/yandexstation-monitor-github/
```

Каталог `data/` с токенами остаётся в прежнем месте `/Volume1/docker/yandexstation-monitor/data`. В git-репозиторий его **не копировать**.

## 3. Первый git push

На TNAS:

```bash
cd /Volume1/docker/yandexstation-monitor-github

git init -b main
git config user.name "gazizovemil"
git config user.email "56061753+gazizovemil@users.noreply.github.com"

git add .
git status --short
git ls-files | grep -E '(^|/)(data/|\.station_music_token$|\.iot_view_token$|\.session_id$|config\.json$|plug\.json$)' && echo 'ОШИБКА: НАЙДЕНЫ СЕКРЕТЫ!' || echo 'Секреты не найдены'

git commit -m "Initial release: Yandex Station and Smart Plug Zabbix monitor"
git remote add origin https://github.com/gazizovemil/yandexstation-monitor.git
git push -u origin main
```

Если `git push` попросит пароль GitHub, используй **GitHub Personal Access Token**, а не пароль аккаунта, или ранее настроенный Git Credential Manager. Вариант с `gh`: `gh auth login`, затем `gh auth setup-git` (если GitHub CLI установлен).

## 4. Настрой GitHub Actions → Docker Hub

Открой https://github.com/gazizovemil/yandexstation-monitor/settings/secrets/actions

- В **Variables** создай `DOCKERHUB_USERNAME` со значением `gazizovemil`.
- В **Secrets** создай `DOCKERHUB_TOKEN` и вставь Docker Hub Personal Access Token с разрешением **Read/Write** в `gazizovemil/yandexstation-monitor`.

Токен можно создать здесь: https://app.docker.com/settings/personal-access-tokens

Не вставляй токены в Git, Compose, командную строку с аргументами или чат.

## 5. Автоматически опубликуй 1.0.1 в Docker Hub

```bash
cd /Volume1/docker/yandexstation-monitor-github

git tag -a v1.0.1 -m "Yandex monitor 1.0.1"
git push origin v1.0.1
```

Открой https://github.com/gazizovemil/yandexstation-monitor/actions и дождись успешного `Publish to Docker Hub`. Получишь:

- https://hub.docker.com/r/gazizovemil/yandexstation-monitor/tags
- `gazizovemil/yandexstation-monitor:1.0.1`
- `gazizovemil/yandexstation-monitor:latest`

Существующий `:1.0.0` **не меняется**.

## 6. Обнови уже работающий Portainer Stack

Открой **Portainer → Stacks → yandexstation-monitor → Editor**.

Измени только строку `image`:

```yaml
image: gazizovemil/yandexstation-monitor:1.0.1
```

Нажми `Update the stack`, включи `Re-pull image`, если есть такая опция. **Не создавай второй стек** с тем же `container_name`. Существующий bind mount `/Volume1/docker/yandexstation-monitor/data:/data` оставь неизменным.

Проверка:

```bash
docker inspect yandexstation-monitor --format '{{.Config.Image}}'
docker logs --tail=30 -f yandexstation-monitor
docker exec yandexstation-monitor python /app/monitor.py probe all
```

## 7. Публикация следующих изменений

```bash
cd /Volume1/docker/yandexstation-monitor-github

git add .
git commit -m "Update monitoring and templates"
git push origin main
```

Обычный `push main` не создаёт новый образ. Для публикации версии после изменения кода создай **новый** Git-тег, например `v1.0.2`, и отправь его на GitHub.
