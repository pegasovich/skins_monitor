# ADR 0002: Network Layer, Token Bucket Rate Limiting and Liquidity/Wash-Trading Engine

## Status
Accepted

## Context
В Phase 2 система переходит от абстрактных моделей к интеграции с официальными контрактами внешних маркетплейсов (CSFloat, Skinport, Steam). 
Ключевые вызовы:
1. Строгое соблюдение лимитов запросов (Rate Limits) поставщиков данных для исключения блокировок (HTTP 429).
2. Обработка заголовка `Retry-After` при возникновении временных ограничений.
3. Устойчивость к сбоям сети (retries с экспоненциальным backoff и jitter).
4. Защита от манипуляций объемом (Wash Trading) и расчет метрик реальной ликвидности (VWAP, Median, Volume Thresholds).

## Decision

### 1. Сетевой клиент (`ResilientHttpClient`)
- Построен на базе `httpx.AsyncClient` с ограничением пула соединений (`Limits(max_keepalive_connections=20, max_connections=50)`).
- Встроенный перехват HTTP 429: парсинг заголовка `Retry-After` (в секундах или HTTP-date) с принудительной паузой.
- Экспоненциальный backoff с полным джиттером (`tenacity`) строго для идемпотентных GET-запросов.
- Запрет небезопасных методов или обходов защиты.

### 2. Token Bucket Rate Limiter
- Алгоритм Token Bucket с атомарным пополнением токенов.
- Двойной режим работы:
  - Redis-based (для распределенного развертывания).
  - In-Memory fallback (для автономного режима или локальных тестов).
- Конфигурация rate limits на каждый источник отдельно:
  - CSFloat: 1 запрос / сек (conservative limit для публичных/стандартных ключей).
  - Skinport: 2 запроса / сек.

### 3. Liquidity Engine & Wash Trading Filter
- Расчет метрик:
  - `Volume Weighted Average Price (VWAP) = sum(Price_i * Volume_i) / sum(Volume_i)`
  - `Median Sale Price` (устойчивая к выбросам).
  - `Lowest Listing Price` vs `Historical Median`.
- **Wash-Trading Protection Rule:**
  - Если цена сделки отклоняется более чем на 3.0 стандартных отклонения ($Z > 3$) от исторической медианы, а суточный объем сделок для данного предмета $\le 2$, сделка помечается как `SUSPICIOUS_VOLUME_ANOMALY` и блокируется от генерации арбитражных сигналов.

## Consequences
- Система гарантирует отсутствие всплесков трафика (traffic bursts), вызывающих баны по IP.
- Защита от «нарисованных» цен и скам-пампов неликвидных скинов.
