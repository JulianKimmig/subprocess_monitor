# Subprocess Monitor

A robust Python service for managing, monitoring, and spawning subprocesses with advanced lifecycle management features. Provides both a Python API and CLI interface for subprocess operations using async/await patterns.

## Table of Contents

- [Why Subprocess Monitor?](#why-subprocess-monitor)
- [Key Features](#key-features)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Use Cases vs Built-in subprocess](#use-cases-vs-built-in-subprocess)
- [API Reference](#api-reference)
- [CLI Usage](#cli-usage)
- [Architecture](#architecture)
- [Development](#development)

## Why Subprocess Monitor?

While Python's built-in `subprocess` module is excellent for basic process management, `subprocess-monitor` provides enterprise-grade features for complex subprocess orchestration:

### Problems with Built-in subprocess

- **No centralized management**: Each subprocess is isolated
- **Manual lifecycle tracking**: You must track PIDs and process states yourself
- **No real-time monitoring**: Limited ability to stream output in real-time
- **Complex async patterns**: Difficult to integrate with async/await workflows
- **No process persistence**: Processes die with parent termination
- **Limited observability**: No built-in logging or monitoring

### Subprocess Monitor Solutions

- **Centralized service**: Single point of control for all subprocesses
- **Automatic lifecycle management**: Built-in process tracking and cleanup
- **Real-time streaming**: WebSocket-based output streaming
- **Async-first design**: Native async/await support throughout
- **Process persistence**: Processes can outlive parent applications
- **Rich observability**: Comprehensive logging and monitoring
- **Cross-platform compatibility**: Works on Windows, Linux, and macOS
- **REST API**: HTTP endpoints for remote process management
- **Type safety**: Full TypeScript-style typing with runtime validation

## Key Features

### 🎯 **Centralized Process Management**
- Single service manages multiple subprocesses
- Automatic PID tracking and process ownership
- Built-in process cleanup and resource management

### 🔄 **Real-time Monitoring**
- WebSocket subscriptions for live output streaming
- Process state change notifications
- Resource usage monitoring

### ⚡ **Async/Await Native**
- Built on aiohttp for high-performance async operations
- Non-blocking subprocess operations
- Concurrent process management

### 🛡️ **Enterprise Security**
- Runtime type validation prevents injection attacks
- Secure port binding prevents race conditions
- Process isolation and sandboxing

### 🌐 **Cross-Platform**
- Windows, Linux, and macOS support
- Platform-specific optimizations
- Unified API across all platforms

### 🔌 **Multiple Interfaces**
- Python API for programmatic access
- CLI for terminal operations
- REST API for remote management
- WebSocket API for real-time updates

## Installation

```bash
# Using pip
pip install subprocess-monitor

# Using uv (recommended)
uv add subprocess-monitor

# From source
git clone https://github.com/JulianKimmig/subprocess_monitor
cd subprocess-monitor
uv sync
```

## Quick Start

### Python API

```python
import asyncio
from subprocess_monitor import SubprocessMonitor

async def main():
    # For server-side usage
    monitor = SubprocessMonitor(host="localhost", port=8080)
    server_task = asyncio.create_task(monitor.run())

    # For client-side usage (more common)
    from subprocess_monitor.helper import send_spawn_request, get_status

    # Start a subprocess via API
    response = await send_spawn_request(
        "python", ["-c", "print('Hello World')"],
        env={"MY_VAR": "value"}, host="localhost", port=8080
    )
    pid = response["pid"]
    print(f"Started process {pid}")

    # Get status
    processes = await get_status(host="localhost", port=8080)
    print(f"Active processes: {processes}")

asyncio.run(main())
```

### CLI Usage

```bash
# Start the monitor service
subprocess-monitor start --port 8080

# Spawn a process
subprocess-monitor spawn python -c "print('Hello World')"

# Check status
subprocess-monitor status

# Stop a process
subprocess-monitor stop <pid>

# Subscribe to process output
subprocess-monitor subscribe <pid>
```

## Use Cases vs Built-in subprocess

### When to Use Built-in subprocess

✅ **Simple one-off commands**
```python
import subprocess
result = subprocess.run(["ls", "-la"], capture_output=True, text=True)
print(result.stdout)
```

✅ **Synchronous workflows**
```python
with subprocess.Popen(["python", "script.py"]) as proc:
    proc.wait()
```

✅ **Basic process communication**
```python
proc = subprocess.Popen(["python"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
stdout, stderr = proc.communicate(input="print('hello')")
```

### When to Use Subprocess Monitor

✅ **Long-running process orchestration**
```python
# Built-in subprocess - complex manual management
processes = []
for i in range(10):
    proc = subprocess.Popen(["worker.py", f"--id={i}"])
    processes.append(proc)

# Subprocess Monitor - simple centralized management
monitor = SubprocessMonitor()
for i in range(10):
    await monitor.start_subprocess({"cmd": "python", "args": ["worker.py", f"--id={i}"]})
```

✅ **Real-time output monitoring**
```python
# Built-in subprocess - polling required
proc = subprocess.Popen(["tail", "-f", "log.txt"], stdout=subprocess.PIPE)
for line in iter(proc.stdout.readline, b''):
    print(line.decode())

# Subprocess Monitor - WebSocket streaming
async with websockets.connect(f"ws://localhost:8080/subscribe?pid={pid}") as ws:
    async for message in ws:
        data = json.loads(message)
        print(f"{data['stream']}: {data['data']}")
```

✅ **Async/await workflows**
```python
# Built-in subprocess - complex async integration
async def run_process():
    proc = await asyncio.create_subprocess_exec("python", "script.py")
    await proc.wait()

# Subprocess Monitor - native async support
async def run_process():
    pid = await monitor.start_subprocess({"cmd": "python", "args": ["script.py"]})
    # Process runs in background - monitor via subscribe_output endpoint
```

✅ **Process lifecycle management**
```python
# Built-in subprocess - manual cleanup
import atexit
import signal

processes = []

def cleanup():
    for proc in processes:
        proc.terminate()
        proc.wait()

atexit.register(cleanup)
signal.signal(signal.SIGTERM, lambda s, f: cleanup())

# Subprocess Monitor - automatic cleanup
monitor = SubprocessMonitor()  # Handles all cleanup automatically
```

✅ **Remote process management**
```python
# Built-in subprocess - local only
subprocess.run(["python", "script.py"])

# Subprocess Monitor - remote management via REST API
import aiohttp
async with aiohttp.ClientSession() as session:
    async with session.post("http://remote:8080/spawn", json={
        "cmd": "python", "args": ["script.py"]
    }) as resp:
        result = await resp.json()
        print(f"Started remote process {result['pid']}")
```

✅ **Multi-service coordination**
```python
# Start multiple interdependent services
services = [
    {"cmd": "redis-server", "args": []},
    {"cmd": "python", "args": ["api_server.py"]},
    {"cmd": "python", "args": ["worker.py"]},
    {"cmd": "nginx", "args": ["-c", "nginx.conf"]}
]

monitor = SubprocessMonitor()
pids = []
for service in services:
    pid = await monitor.start_subprocess(service)
    pids.append(pid)
    await asyncio.sleep(1)  # Staggered startup

# Monitor all services via WebSocket (client-side implementation needed)
# WebSocket endpoint: ws://localhost:8080/subscribe?pid={pid}
```

## API Reference

### SubprocessMonitor Class

#### Constructor
```python
SubprocessMonitor(
    host: str = "localhost",
    port: Optional[int] = None,
    check_interval: float = 2.0,
    logger: Optional[logging.Logger] = None
)
```

#### Methods

**`async start_subprocess(request: SpawnProcessRequest) -> int`**
- Spawns a new subprocess
- Returns the process PID
- Automatically tracks process lifecycle

**`async stop_subprocess(pid: int) -> bool`**
- Terminates a subprocess by PID
- Returns True if successful
- Handles cleanup automatically

**Note**: The SubprocessMonitor class provides internal process management. For client access, use the helper functions or REST API endpoints:
- **GET /**: Returns list of active process PIDs
- **POST /spawn**: Spawn a new subprocess
- **POST /stop**: Stop a subprocess by PID
- **WebSocket /subscribe?pid={pid}**: Subscribe to real-time process output

### Helper Functions

**`async send_spawn_request(cmd: str, args: List[str], env: Dict[str, str] = None, host: str = None, port: int = None) -> SpawnRequestResponse`**

**`async send_stop_request(pid: int, host: str = None, port: int = None) -> StopRequestResponse`**

**`async get_status(host: str = None, port: int = None) -> List[int]`**

## CLI Usage

### Starting the Service

```bash
# Start with default settings
subprocess-monitor start

# Start with custom port
subprocess-monitor start --port 8080

# Start with custom host and port
subprocess-monitor start --host 0.0.0.0 --port 8080
```

### Process Management

```bash
# Spawn a simple command
subprocess-monitor spawn echo "Hello World"

# Spawn with arguments
subprocess-monitor spawn python script.py --arg1 value1

# Spawn with environment variables
subprocess-monitor spawn --env VAR1=value1 --env VAR2=value2 python script.py

# Check active processes
subprocess-monitor status

# Stop a process
subprocess-monitor stop 12345

# Subscribe to process output
subprocess-monitor subscribe 12345
```

### Environment Variables

- `SUBPROCESS_MONITOR_HOST`: Default host (default: localhost)
- `SUBPROCESS_MONITOR_PORT`: Default port (default: 5000)
- `SUBPROCESS_MONITOR_PID`: Monitor service PID (auto-set)

## Architecture

### Core Components

```
subprocess_monitor/
├── __init__.py              # Package exports
├── __main__.py              # CLI entry point
├── subprocess_monitor.py    # Core service logic
├── helper.py               # Client helper functions
├── types.py                # TypedDict definitions
├── defaults.py             # Configuration constants
└── validation.py           # Runtime type validation
```

### Key Design Patterns

**Async/Await First**: Built on asyncio and aiohttp for high-performance async operations

**Type Safety**: Full typing with runtime validation using TypedDict and custom validators

**Resource Management**: Automatic cleanup of processes, sockets, and WebSocket connections

**Cross-Platform**: Unified API with platform-specific optimizations

**Security**: Input validation, secure port binding, and process isolation

### Service Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   CLI Client    │    │   Python API     │    │  HTTP Client    │
└─────────┬───────┘    └─────────┬────────┘    └─────────┬───────┘
          │                      │                       │
          └──────────────────────┼───────────────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │  Subprocess Monitor     │
                    │  (aiohttp server)       │
                    └────────────┬────────────┘
                                 │
        ┌────────────────────────┼────────────────────────┐
        │                        │                        │
┌───────▼────────┐    ┌─────────▼────────┐    ┌─────────▼────────┐
│ REST Endpoints │    │ WebSocket Stream │    │ Process Manager  │
│ /spawn         │    │ /subscribe       │    │ - Lifecycle      │
│ /stop          │    │ Real-time I/O    │    │ - Monitoring     │
│ /status        │    │ JSON messages    │    │ - Cleanup        │
└────────────────┘    └──────────────────┘    └──────────────────┘
```

## Development

### Setup

```bash
# Clone and setup
git clone https://github.com/JulianKimmig/subprocess_monitor
cd subprocess-monitor
uv sync

# Install pre-commit hooks
uv run pre-commit install
```

### Testing

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=subprocess_monitor

# Run specific test
uv run pytest tests/test_sm.py::TestHelperFunctions::test_send_spawn_request
```

### Code Quality

```bash
# Format code
uv run ruff format .

# Lint code
uv run ruff check . --fix

# Type checking
uv run flake8

# Security scanning
uv run vulture subprocess_monitor

# Run all checks
uv run pre-commit run --all-files
```

### Project Structure

- **Type Safety**: Uses TypedDict for API contracts with runtime validation
- **Async Patterns**: Built on asyncio for non-blocking operations
- **Testing**: Comprehensive test suite with IsolatedAsyncioTestCase
- **Security**: Input validation and secure resource management
- **Cross-Platform**: Works on Windows, Linux, and macOS

---

## License

MIT License - see LICENSE file for details.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes with tests
4. Run the full test suite
5. Submit a pull request

## Support

- 🐛 **Bug Reports**: [GitHub Issues](https://github.com/JulianKimmig/subprocess_monitor/issues)
- 💬 **Discussions**: [GitHub Discussions](https://github.com/JulianKimmig/subprocess_monitor/discussions)
- 📚 **Documentation**: [Wiki](https://github.com/JulianKimmig/subprocess_monitor/wiki)
