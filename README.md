# Чемпионат Азии по настольному теннису — Ташкент 2026 (GitHub Pages + Auto-Update)

Готовый репозиторий для публикации интерактивной сетки и счёта матчей на **GitHub Pages** с автоматическим обновлением данных через **GitHub Actions**.

## Структура файлов
- `index.html` — дашборд сетки и результатов (автоматически опрашивает `./data.json` каждые 60 секунд без перезагрузки страницы).
- `data.json` — файл данных с сеткой (`brackets`) и списком матчей (`matches`).
- `.github/workflows/update_scores.yml` — воркфлоу GitHub Actions, который запускается каждые 10 минут по расписанию (`cron: '*/10 * * * *'`) или вручную кнопкой **Run workflow**.
- `scripts/fetch_ittf.py` — Python-скрипт на базе Playwright, который открывает [официальный протокол ITTF (TTE3474)](https://results.ittf.com/ittf-web-results/html/TTE3474/results.html) и обновляет `data.json`.

## Как запустить за 3 шага
1. Создайте новый публичный репозиторий на GitHub и загрузите в него содержимое этого архива.
2. Перейдите в **Settings → Pages** и в разделе **Build and deployment** выберите `Deploy from a branch` → ветка `main` (`/root`).
3. Перейдите в **Settings → Actions → General** и в разделе **Workflow permissions** выберите `Read and write permissions`, чтобы GitHub Actions мог сохранять обновлённый `data.json` в репозиторий.
