# ADR 0003: TimescaleDB Storage, Per-Source Circuit Breaker, and Containerization

## Status
Accepted

## Context
В Phase 3 система масштабируется для промышленной непрерывной эксплуатации:
1. Локального SQLite недостаточно для хранения миллионов тиков цен и расчета continuous aggregates (1-мин / 1-час свечи). Необходима TimescaleDB (гипертаблицы на базе PostgreSQL).
2. При сбоях или деградации внешних бирж система должна изолировать нестабильный источник с помощью Circuit Breaker (предохранителя), предотвращая каскадные сбои и перегрузку очередей.
3. Развертывание должно быть воспроизводимым через Docker Compose v2 с четкими лимитами ресурсов (CPU/Memory) и Healthchecks.

## Decision

### 1. Per-Source Circuit Breaker (`src/collectibles/core/circuit_breaker.py`)
- Реализация конечного автомата состояний:
  - `CLOSED`: штатный режим, все запросы проходят.
  - `OPEN`: при превышении порога ошибок ($M$ ошибок подряд или $X\%$ за окно времени) запросы мгновенно отклоняются (`CircuitOpenError`) без совершения сетевых вызовов на время `recovery_timeout`.
  - `HALF_OPEN`: по истечении таймаута пропускается пробный запрос. При успехе состояние сбрасывается в `CLOSED`, при ошибке — возвращается в `OPEN`.
- Интеграция с логированием `structlog` и метриками отказоустойчивости.

### 2. TimescaleDB Time-Series Схема
- Гипертаблица `price_points_hyper` с партиционированием по `event_time` (размер чанка — 7 дней).
- Политика сжатия (compression policy) для данных старше 14 дней.
- Retention-политика: удаление сырых тиков старше 30 дней с сохранением continuous aggregates (1-мин, 1-час, 1-день).

### 3. Docker Compose & Enterprise Infrastructure
- `timescaledb`: образ `timescale/timescaledb:latest-pg16` с healthcheck `pg_isready`.
- `redis`: образ `redis:7-alpine` с AOF-персистентностью.
- `app`: многоэтапный Dockerfile (multi-stage build) на базе `python:3.11-slim`, запуск от непривилегированного пользователя `appuser`.

## Consequences
- Автоматическая изоляция упавших внешних маркетплейсов защищает внутренние очереди и пул соединений.
- Хранение цен в гипертаблицах обеспечивает субсекундные аналитические выборки по миллионам записей.
