# Autonomous Digital Collectibles Monitoring System

Enterprise-grade, asynchronous monitoring and anomaly detection engine for digital collectibles and in-game assets (CS2 skins).

## Key Principles & Architecture
- **Fail-Safe & Deterministic:** 100% reproducible statistical calculations using `decimal.Decimal` (no floating-point rounding errors).
- **Domain Specifics:** Native support for CS2 wear buckets, float thresholds, sticker values, and platform fee matrices.
- **Safety & ToS Compliance:** Operates strictly via documented B2B/Partner APIs with distributed rate limiting and circuit breakers. Obeying anti-fraud, KYC, and Cloudflare rules.
- **Default Simulation:** `DRY_RUN=true` by default. Live alerts require explicit gate clearance.

## Quickstart
```bash
python -m venv .venv
.\.venv\Scripts\pip install -e ".[dev]"
.\.venv\Scripts\pytest
.\.venv\Scripts\ruff check .
.\.venv\Scripts\mypy src
```
