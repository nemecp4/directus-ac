# Design Document: CLI SSL & Verbose Options

## Overview

This design adds two new optional flags (`--ignore-ssl` and `--verbose`) to the `directus_ac` CLI. The changes touch three areas: argument parsing, HTTP client construction, and logging configuration.

## Architecture

### Affected Components

1. **`directus_ac/cli.py`** — Adds new argparse arguments and passes values downstream.
2. **`directus_ac/client.py`** — Accepts an optional `verify_ssl` parameter to control `httpx.Client` TLS behavior.
3. **Logging setup in `main()`** — Conditionally adjusts log level and format based on `--verbose`.

### Data Flow

```
CLI args (argparse)
  │
  ├── --verbose ──► logging.basicConfig(level=DEBUG, format=VERBOSE_FMT)
  │
  └── --ignore-ssl ──► DirectusClient(base_url, token, verify_ssl=False)
                            │
                            └── httpx.Client(verify=False)
```

## Detailed Design

### 1. Argument Parsing (`cli.py :: build_parser`)

Add two `store_true` arguments to the existing parser:

```python
parser.add_argument(
    "--ignore-ssl",
    action="store_true",
    default=False,
    help="Disable SSL certificate verification for HTTPS connections",
)

parser.add_argument(
    "--verbose",
    action="store_true",
    default=False,
    help="Enable debug-level logging output",
)
```

### 2. Logging Configuration (`cli.py :: main`)

Replace the current static `logging.basicConfig` call with conditional logic:

```python
if args.verbose:
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(levelname)s:%(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
else:
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
```

### 3. SSL Warning

When `--ignore-ssl` is active, emit a warning immediately after logging is configured:

```python
if args.ignore_ssl:
    logger.warning("SSL certificate verification is disabled.")
```

### 4. HTTP Client (`client.py :: DirectusClient.__init__`)

Add a `verify_ssl` keyword argument (default `True`):

```python
def __init__(self, base_url: str, token: str, *, verify_ssl: bool = True) -> None:
    self._base_url = base_url.rstrip("/")
    self._client = httpx.Client(
        base_url=self._base_url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        verify=verify_ssl,
    )
```

### 5. Wiring in `main()`

Pass `verify_ssl` derived from `args.ignore_ssl` to every `DirectusClient` instantiation:

```python
client = DirectusClient(base_url=url, token=token, verify_ssl=not args.ignore_ssl)
```

## Correctness Properties

| ID | Property | Type | Criteria Ref |
|----|----------|------|-------------|
| CP-1 | Parsing `--ignore-ssl` sets `args.ignore_ssl` to `True`; absent means `False` | example | 1.1, 1.3 |
| CP-2 | Parsing `--verbose` sets `args.verbose` to `True`; absent means `False` | example | 2.1 |
| CP-3 | When `verify_ssl=False`, the httpx client is constructed with `verify=False` | example | 1.2 |
| CP-4 | When `verify_ssl=True` (default), the httpx client uses default verification | example | 1.3 |
| CP-5 | When `--ignore-ssl` is active, a WARNING-level log message about disabled SSL is emitted | example | 1.4 |
| CP-6 | When `--verbose` is active, root logger level is DEBUG and format includes levelname and name | example | 2.2, 2.4 |
| CP-7 | When `--verbose` is absent, root logger level is INFO and format is plain message | example | 2.3, 2.5 |
| CP-8 | Both flags can be provided simultaneously and both effects apply | example | 3.1, 3.2 |

## Testing Strategy

All correctness properties are testable as example-based unit tests:

- **Argument parsing tests**: Call `build_parser().parse_args([...])` with various flag combinations and assert namespace values.
- **Client construction tests**: Mock or inspect `httpx.Client` instantiation to verify `verify` kwarg.
- **Logging tests**: Use `caplog` or inspect handler/level after calling a `configure_logging` helper.
- **Integration test**: Call `main()` with mocked environment and verify both flags cooperate.

## Migration & Compatibility

- Both flags default to `False`, so existing usage is unaffected.
- `DirectusClient.__init__` uses a keyword-only `verify_ssl` parameter with a default of `True`, maintaining backward compatibility with all existing call sites.
