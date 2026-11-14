# ADR 0001: Architecture, Technology Stack and Phase 1 Scope

## Status
Accepted

## Context
Система предназначена для автономного высокоточного мониторинга цен на цифровые коллекционные предметы (CS2 скины и сопутствующие цифровые активы) на множестве маркетплейсов.

Требования системы:
1. Строгое соответствие ToS и безопасности: запрет обхода систем защиты, работа только через санкционированные API/токены.
2. Недопустимость искажения финансовых расчетов (использование `Decimal` вместо `float`).
3. Надежность и детерминированность обнаружения арбитражных спредов и аномалий: учет комиссий платформ (Steam, CSFloat, P2P), расчет Liquidity Score, учет 7-дневного Trade Lock.
4. Отказоустойчивость: Circuit Breaker, Provider Auto-Quarantine при дрейфе схем (Pydantic ValidationError), распределенный Token Bucket Rate Limiting.
5. Режим симуляции по умолчанию (`DRY_RUN=true`).

## Decision

### 1. Архитектурные слои (Clean Architecture)
- `core`: Доменные модели (`ItemIdentity`, `PricePoint`, `MarketAnomaly`), конфигурация (`pydantic-settings`), исключения.
- `providers`: Базовый абстрактный класс `BaseProvider`, реестр провайдеров, адаптеры к конкретным площадкам.
- `normalizer`: Преобразование сырых ответов провайдеров в канонические `PricePoint` со строгой валидацией типов (`Decimal`), таймстемпами UTC (`event_time` vs `fetched_at`) и базовой валютой USD.
- `analyzer`: 
  - `ItemMatchingEngine`: композитный хэш предмета на основе параметров (Paint Index, Seed, Float strata, Stickers hash, Phase).
  - `LiquidityEngine`: расчет реального объема, медианы и отсечение неликвидных позиций.
  - `AnomalyDetector`: расчет Z-score, скользящих средних, вычет матрицы комиссий и генерация сигналов.
- `alerts`: Движок дедупликации сигналов (fingerprint + Redis TTL), троттлинг и диспетчеризация (Console / Telegram / Webhook).
- `storage`: Абстракция репозиториев (в Phase 1 — SQLite через `aiosqlite`, в Phase 3 — TimescaleDB).

### 2. Технический стек Phase 1
- **Язык**: Python 3.11+
- **Типизация**: `mypy --strict`
- **Линтинг/Форматирование**: `ruff`
- **Валидация данных**: `pydantic v2` + `decimal.Decimal`
- **Сетевой клиент**: `httpx` (асинхронный, connection pooling) + `tenacity` для retry с exponential backoff и jitter
- **Логирование**: `structlog` (структурированный JSON с trace_id и correlation_id)
- **Тестирование**: `pytest`, `pytest-asyncio`, `hypothesis` (property-based), `respx` (HTTP mocking), `time-machine` (детерминированное время).

## Consequences
- Использование `Decimal` увеличивает потребление памяти незначительно, но исключает ошибки округления при расчете спредов и комиссий.
- Режим `DRY_RUN=true` гарантирует, что никакие боевые действия или спам-нотификации не выйдут наружу без явного аудита.
- Строгий `mypy` и `ruff` предотвращают деградацию кодовой базы на ранних этапах.
