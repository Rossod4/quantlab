"""Paper trading: `Broker` ABC + adapters, rebalancer, reconciliation,
journal, and runner - see `plans/M08-paper-trading.md`.

No code path in this package reaches a live trading endpoint. Credentials
are read only from environment variables (`ALPACA_API_KEY`/
`ALPACA_SECRET_KEY`), never from code or config files (CLAUDE.md).
"""

from __future__ import annotations
