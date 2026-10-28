# 🤖 Beza Bot — Personal Telegram Sales & Inventory Manager

A production-ready personal Telegram bot for managing your business — track products, inventory, sales, COGS, gross profit, and financial reports, all from your phone.

---

## Features

- 📦 **Product management** — Add products with photos, SKU, category, selling price
- 📊 **FIFO inventory costing** — Multiple purchase batches at different costs; COGS always accurate
- 💰 **Fast sales recording** — Select product → quantity → confirm; receipt shows revenue, COGS, margin
- 📈 **Dashboard & reports** — Today / this week / this month summaries; top products by revenue or profit
- ⚠️ **Low-stock alerts** — Automatic notification after a sale drops stock below your threshold
- 📜 **Full audit trail** — Every stock change (purchase, sale, adjustment, damage) is recorded
- ↩️ **Sale cancellation** — Reverse any sale; inventory and financial figures are corrected automatically
- 🔎 **Product search** — Search by name, SKU, brand, or category
- 📤 **CSV export** — Export products, sales, and inventory movements for backup
- 🔒 **Single-user auth** — Only your Telegram user ID can interact with the bot

---

## Requirements

- Python 3.12+
- PostgreSQL 14+
- Docker + Docker Compose (recommended) **or** a local Python environment
- A Telegram account + bot token from @BotFather

---

## Quick Start (Docker — recommended)

### 1. Create a Telegram bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot`
3. Follow the prompts — give your bot a name and username
4. Copy the **bot token** (looks like `123456:ABCdef...`)

### 2. Find your Telegram user ID

1. Search for **@userinfobot** on Telegram
2. Send it `/start`
3. It will reply with your numeric user ID (e.g. `987654321`)

### 3. Configure the environment

```bash
cp .env.example .env
```

Edit `.env`:

```env
TELEGRAM_BOT_TOKEN=123456:ABCdef...   # from @BotFather
ALLOWED_TELEGRAM_USER_ID=987654321    # your numeric user ID
DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/beza
CURRENCY=ETB
TIMEZONE=Africa/Addis_Ababa
```

### 4. Start the bot

```bash
docker compose up -d
```

That's it! The first run automatically applies database migrations, then starts the bot. Open Telegram and send `/start` to your bot.

### Logs

```bash
docker compose logs -f bot
```

### Stop

```bash
docker compose down
```

---

## Local Development Setup

### 1. Create a virtual environment

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Mac/Linux:
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -e ".[dev]"
```

### 3. Configure `.env`

```bash
cp .env.example .env
# Edit .env with your bot token, user ID, and local DATABASE_URL
```

For local development, use:
```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/beza
```

### 4. Start PostgreSQL

If you have Docker:
```bash
docker compose up -d db
```

Or start your local PostgreSQL and create the database:
```sql
CREATE DATABASE beza;
```

### 5. Run database migrations

```bash
alembic upgrade head
```

### 6. Start the bot

```bash
python -m app
```

---

## Running Tests

Tests use an in-memory SQLite database — no PostgreSQL needed.

```bash
pytest tests/ -v
```

Or with coverage:
```bash
pytest tests/ -v --cov=app --cov-report=term-missing
```

---

## Using the Bot

### Main Menu

Send `/start` to open the main menu. All features are accessible via buttons — you never need to remember commands.

```
👋 Welcome to your Business Manager

[💰 New Sale]    [➕ Add Stock]
[📦 Inventory]   [📊 Dashboard]
[📈 Reports]     [🔎 Search]
[📦 Add Product] [⚙️ Settings]
```

### Adding a Product

1. Tap **📦 Add Product**
2. Send a product **photo** (or type "Skip")
3. Enter: name → SKU (optional) → category (optional) → selling price → low-stock level

### Adding Stock

1. Tap **➕ Add Stock**
2. Select the product
3. Enter: quantity → purchase cost per unit → supplier (optional) → note (optional)
4. Review and confirm

Each stock receipt creates a FIFO inventory batch. Historical COGS is always calculated from the exact batch cost.

### Recording a Sale

1. Tap **💰 New Sale**
2. Select the product
3. Enter the quantity
4. Confirm the selling price (or type a different one)
5. Review the receipt — Revenue, COGS, Gross Profit, Margin — and confirm

After confirmation, you'll see a low-stock alert if the product fell below its threshold.

### Dashboard

Tap **📊 Dashboard** to see:
- Today's and this month's sales, revenue, COGS, gross profit, and margin
- Inventory summary: products, units, cost value, retail value
- Number of low-stock products

Use the period buttons to switch between Today / This Week / This Month.

### Reports

Tap **📈 Reports** for:
- **Period Summary** — today and this month side by side
- **Top Products** — ranked by revenue (sorted by units sold, revenue, or profit)
- **Recent Sales** — last 10 sales with status and financials
- **Export** — download CSV files

### Inventory Screen

Tap **📦 Inventory** to browse all products with stock status:
- 🟢 Healthy stock
- 🟡 Low stock (at or below threshold)
- 🔴 Out of stock

Tap any product to see its detail screen with photo, stock levels, batch costs, and this month's performance.

### Adjusting Stock

From a product detail screen, tap **⚙️ Adjust Stock** to:
- Add units found (e.g. `+3`)
- Remove damaged/lost units (e.g. `-2`)

All adjustments are audited with a reason and timestamp.

### Cancelling a Sale

From **📈 Reports → Recent Sales**, tap a sale to view it, then cancel it. The inventory is automatically restored and financial figures are reversed.

### Search

Tap **🔎 Search** or use `/search <term>` to find products by name, SKU, brand, or category.

### Natural Language Input

You can also type naturally (no LLM required — this is rule-based):

> "Bought 20 black shirts for 400 each"

> "Sold 3 black shirts"

The bot will parse your intent and show a confirmation before making any changes.

---

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Open the main menu |
| `/help` | Show help |
| `/dashboard` | Business dashboard |
| `/products` | Inventory list |
| `/stock` | Inventory list |
| `/sell` | Record a sale |
| `/addstock` | Receive stock |
| `/reports` | Reports menu |
| `/search <term>` | Search products |
| `/settings` | Settings |
| `/cancel` | Cancel current operation |

---

## CSV Export

From **Reports → Export**, download:

- **products.csv** — all products with prices and thresholds
- **sales.csv** — all sale items with revenue, COGS, gross profit
- **movements.csv** — full inventory movement audit trail

---

## Settings

Tap **⚙️ Settings** to change:
- **Currency** — default `ETB`; any 3-letter code works
- **Timezone** — default `Africa/Addis_Ababa`; any IANA tz name
- **Low-stock alerts** — on/off

---

## Backup & Data Safety

- All data is in PostgreSQL — **never deleted**, only archived/cancelled
- Use CSV export for a spreadsheet backup
- For a full database backup:
  ```bash
  docker exec beza-bot-db-1 pg_dump -U postgres beza > backup.sql
  ```

---

## Deployment Options

### Option A: Docker on a VPS (recommended)

1. Copy the project to your server
2. Set up `.env`
3. Run `docker compose up -d`
4. Use a process manager like `systemd` or Docker restart policies

### Option B: Systemd service (bare metal)

Create `/etc/systemd/system/beza-bot.service`:
```ini
[Unit]
Description=Beza Business Bot
After=network.target postgresql.service

[Service]
Type=simple
WorkingDirectory=/path/to/beza-bot
EnvironmentFile=/path/to/beza-bot/.env
ExecStart=/path/to/beza-bot/.venv/bin/python -m app
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
systemctl enable --now beza-bot
```

---

## Project Structure

```
beza-bot/
├── app/
│   ├── main.py              # Bot bootstrap & polling
│   ├── __main__.py          # Entry point: python -m app
│   ├── bot/
│   │   ├── handlers.py      # Command handlers (/start, /sell, ...)
│   │   ├── callbacks.py     # Inline button handlers
│   │   ├── flows.py         # FSM conversational flows
│   │   ├── keyboards.py     # All inline/reply keyboards
│   │   ├── text.py          # Message text builders
│   │   ├── middleware.py    # Auth + error handling
│   │   ├── helpers.py       # Product picker, inventory grid
│   │   └── states.py        # FSM state groups
│   ├── config/
│   │   └── settings.py      # Pydantic settings from .env
│   ├── database/
│   │   ├── models/
│   │   │   ├── models.py    # SQLAlchemy ORM models
│   │   │   └── enums.py     # MovementType, SaleStatus, PaymentMethod
│   │   └── session.py       # Async engine + session factory
│   ├── services/
│   │   ├── fifo_service.py      # FIFO engine (consume, revert)
│   │   ├── inventory_service.py # add_purchase, apply_adjustment
│   │   ├── product_service.py   # CRUD + search + photo
│   │   ├── sales_service.py     # record_sale, cancel_sale
│   │   ├── reporting_service.py # Dashboard, top products, period summaries
│   │   ├── nlp_service.py       # Rule-based natural language parsing
│   │   ├── settings_service.py  # Runtime settings (currency, timezone)
│   │   └── exceptions.py        # Domain exceptions
│   └── utils/
│       ├── formatting.py    # money(), pct(), format_date(), stock_emoji()
│       └── export.py        # CSV export functions
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── 001_initial_schema.py
├── tests/
│   ├── conftest.py          # SQLite in-memory DB fixture
│   ├── test_fifo.py         # FIFO engine tests
│   ├── test_inventory.py    # Inventory service tests
│   ├── test_sales.py        # Sales service tests
│   └── test_reporting.py    # Reporting tests
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── pyproject.toml
└── README.md
```

---

## Accounting Definitions

| Term | Definition |
|------|-----------|
| **Revenue** | Actual selling price × quantity sold |
| **COGS** | FIFO purchase cost of inventory sold |
| **Gross Profit** | Revenue − COGS |
| **Gross Margin** | Gross Profit ÷ Revenue × 100 |
| **Inventory Cost Value** | Σ (remaining qty × batch unit cost) |
| **Inventory Retail Value** | Σ (remaining qty × current selling price) |

> ⚠️ Gross Profit ≠ Net Profit. This system tracks gross profit only. Expenses (rent, transport, etc.) are not yet included.
