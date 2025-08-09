# TastyTrade SDK

A high-performance Python SDK for the TastyTrade Open API, providing programmatic access to trading operations and real-time market data with advanced analytics capabilities.

![Sample Technical Analysis Chart](src/devtools/images/sample_chart.png)

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python Versions](https://img.shields.io/badge/python-3.11%2B-blue)
![Status](https://img.shields.io/badge/status-beta-yellow)

## 🚀 Features

### Core Trading Features
- Trade execution and position management
- Advanced order types support
- Real-time position monitoring
- Options chain data access
- Risk metrics tracking
- Support for stocks and options (futures and crypto planned)

### 📊 Real-Time Data Processing
- High-performance DXLink client:
  - Handles WebSocket connection management
  - Real-time market data stream processing
  - Event normalization and type safety
  - Advanced subscription management
  - Automatic reconnection and error handling
- Robust data pipeline:
  - Telegraf as data routing backbone:
    - Receives processed events from DXLink client
    - Writes to InfluxDB for time-series storage
    - Streams to Kafka for real-time distribution *(in development)*
    - Provides system metrics and monitoring
  - InfluxDB for historical analysis
  - ~~Kafka~~ Redis for scalable event distribution
- Event processing and analytics:
  - Real-time technical indicators
  - Custom data transformations
  - Configurable event processors
  - Fault-tolerant data flow

### 📈 Analytics

- Real-time technical indicators:
  - Hull Moving Average (HMA)
  - MACD with dynamic color coding
  - Volume analysis (planned)
  - Custom price and time references
- Interactive charting
- Customizable dashboards

### 🔧 Technical Architecture

```
                                   WebSocket Feed
                                         │
                                    ┌──────────┐  Message Parser
                    ┌───────────────│ DXClient │        &
                    │               └──────────┘   Event Router
                    │                    │
                    │                    ▼
                    │               ┌──────────┐
                    │               │ Telegraf │  ──  ──  ──  ─┐
                    │               └──────────┘
                    │                    │                     │
                    ▼                    ▼                     ▼
     pub/sub  ┌──────────┐          ┌──────────┐          ┌──────────┐
        &     │  Redis   │          │ InfluxDB │          │   Kafka  │ (in development)
      cache   └─────┬────┘          └──────────┘          └────┬─────┘
                    │                                          │
                    ▼                                          ▼
    ┌────────┬─────────────┬─────────────┬──────────────┬──────────────────┬──────┐
             │             │             │              │                  │
             ▼             ▼             ▼              ▼                  ▼
    ┌───────────────┐ ┌─────────┐ ┌─────────────┐ ┌────────────┐     ┌────────────┐
    │   Analytics   │ │ Alerts  │ │   Recipes   │ │  Logging   │ ... │    etc     │
    └───────────────┘ └─────────┘ └─────────────┘ └────────────┘     └────────────┘
```

- **Real-time Processing**: WebSocket streaming with asynchronous event handling
- **Data Storage**: InfluxDB for time-series data storage and analysis
- **Message Queue**: ~~Kafka~~ Redis for reliable event distribution
- **Metrics Collection**: Telegraf for system and application metrics
- **Containerization**: Full Docker support with dev containers

## 🛠️ Prerequisites

- VS Code or GitHub Codespaces
- Docker Desktop
- Git

## 📦 Installation

The TastyTrade SDK is designed to run in a development container that provides a consistent, pre-configured environment with all necessary dependencies and services.

### Option 1: VS Code (Recommended)

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/tastytrade_sdk.git
   cd tastytrade_sdk
   ```

2. Install the "Remote - Containers" extension in VS Code:
   - Open VS Code
   - Press `Ctrl+P` (or `Cmd+P` on macOS)
   - Type `ext install ms-vscode-remote.remote-containers`

3. Open in Dev Container:
   - Open the cloned repository in VS Code
   - When prompted "Folder contains a dev container configuration file. Reopen folder to develop in a container?", click "Reopen in Container"
   - Or press `F1`, type "Remote-Containers: Reopen in Container" and press Enter

VS Code will build and start the development container, which includes:
- Python 3.11 environment
- UV (fast Python package manager) for dependency management
- InfluxDB
- Telegraf
- Kafka
- Redis
- Redis-Commander
- All required Python packages
- Pre-configured development tools

### Option 2: GitHub Codespaces

1. Visit the repository on GitHub
2. Click the "Code" button
3. Select "Open with Codespaces"
4. Click "New codespace"

The development environment will be automatically configured with all necessary dependencies.

### Post-Installation Setup

1. Copy the environment template:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` with your TastyTrade credentials and preferences:
   ```bash
   TASTYTRADE_USERNAME=your_username
   TASTYTRADE_PASSWORD=your_password
   INFLUX_DB_ORG=your_org
   INFLUX_DB_BUCKET=your_bucket
   INFLUX_DB_TOKEN=your_token
   ```

3. Start the infrastructure services:
   ```bash
   docker-compose up -d
   ```

The SDK is now ready to use within the development container!

## 🚀 Quick Start

```python
from tastytrade.connections import Credentials
from tastytrade.connections.sockets import DXLinkManager
from tastytrade.analytics.visualizations.charts import CandleChart

# Initialize connection
credentials = Credentials(env="Live")
async with DXLinkManager(credentials) as dxlink:
    # Subscribe to market data
    await dxlink.subscribe_to_candles(
        symbol="SPY",
        interval="5m",
        from_time=datetime.now() - timedelta(days=1)
    )

    # Create real-time chart
    chart = CandleChart(
        streamer=dxlink,
        symbol="SPY",
        start_time=datetime.now() - timedelta(days=1)
    )
    chart.add_study(hull_ma)  # Add Hull Moving Average
    await chart.start()
```

## 📊 Data Processing Pipeline

### Market Data Flow
1. Real-time data ingestion via WebSocket
2. Event processing and normalization
3. Storage in InfluxDB for historical analysis
4. Distribution via ~~Kafka~~ Redis for real-time processing
5. Analytics and visualization

### Sample Visualization
```python
from tastytrade.analytics.visualizations.charts import Study

# Create a Hull Moving Average study
hma_study = Study(
    name="HMA-20",
    compute_fn=hull,
    params={"length": 20},
    plot_params={
        "colors": {"Up": "#01FFFF", "Down": "#FF66FE"},
        "width": 1,
    },
    value_column="HMA",
    color_column="HMA_color",
)

# Apply to chart
chart.add_study(hma_study)
```

## 🔧 Configuration

### Environment Variables
```bash
INFLUX_DB_ORG=your_org
INFLUX_DB_BUCKET=your_bucket
INFLUX_DB_TOKEN=your_token
```

### Docker Services
- InfluxDB (Port 8086)
- Telegraf (Port 8186)
- Kafka (Ports 9092, 9093)
- Grafana (Port 3000)

## 🧪 Development

### Dev Container Features
- Pre-configured Python 3.11 environment
- All dependencies pre-installed
- Integrated debugging support
- Pre-configured linting and formatting
- Automatic infrastructure service management
- Consistent development experience across machines

### Dependency Management (UV)

This project uses [uv](https://github.com/astral-sh/uv) instead of Poetry.

Install uv (if not already installed):
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Sync (install) dependencies (inside repo root):
```bash
uv sync
```

Add a runtime dependency:
```bash
uv add some-package
```

Add a dev-only dependency:
```bash
uv add --dev some-dev-package
```

Update all dependencies (respecting version constraints):
```bash
uv lock --upgrade
uv sync
```

Run a command in the project environment:
```bash
uv run python -m tastytrade --help
```

### Running Tests
```bash
uv run pytest
```

### Code Quality
```bash
uv run ruff check .
uv run mypy .
```

## 📚 Documentation

Detailed documentation is available in the `/docs` directory:
- API Reference
- Architecture Guide
- Development Guide
- Deployment Guide

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing_feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing_feature`)
5. Open a Pull Request

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Support

For issues and questions, please [open a GitHub issue](https://github.com/yourusername/tastytrade_sdk/issues).
