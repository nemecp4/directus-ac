# Implementation Tasks

## Task 1: Add `--ignore-ssl` and `--verbose` arguments to CLI parser

- [x] 1.1 Add `--ignore-ssl` store_true argument to `build_parser()` in `directus_ac/cli.py`
- [x] 1.2 Add `--verbose` store_true argument to `build_parser()` in `directus_ac/cli.py`

## Task 2: Update logging configuration for verbose mode

- [x] 2.1 Replace the static `logging.basicConfig` call in `main()` with conditional logic that uses DEBUG level and `%(levelname)s:%(name)s: %(message)s` format when `args.verbose` is True, and INFO level with `%(message)s` format otherwise

## Task 3: Add SSL warning emission

- [x] 3.1 After logging is configured in `main()`, emit `logger.warning("SSL certificate verification is disabled.")` when `args.ignore_ssl` is True

## Task 4: Update `DirectusClient` to accept `verify_ssl` parameter

- [x] 4.1 Add `verify_ssl: bool = True` keyword-only parameter to `DirectusClient.__init__` in `directus_ac/client.py`
- [x] 4.2 Pass `verify=verify_ssl` to the `httpx.Client` constructor

## Task 5: Wire `--ignore-ssl` flag to client instantiation

- [x] 5.1 Update all `DirectusClient(...)` calls in `main()` to pass `verify_ssl=not args.ignore_ssl`

## Task 6: Write tests

- [x] 6.1 Add unit tests for argument parsing (both flags present, absent, and combined)
- [x] 6.2 Add unit test verifying `DirectusClient` passes `verify=False` to httpx when `verify_ssl=False`
- [x] 6.3 Add unit test verifying SSL warning is logged when `--ignore-ssl` is active
- [x] 6.4 Add unit test verifying logging level and format change when `--verbose` is active
