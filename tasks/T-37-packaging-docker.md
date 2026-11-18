# T-37: Packaging and Dockerfile

## Goal
Make `pip install keel-proxy` produce a working `keel` command from a built wheel, and add a Docker image that runs `keel serve` with a mounted config.

## Context
PRD FR-18: `pip install keel-proxy` and a Docker image, with a quickstart that works on a clean machine. The wheel already contains the packages `keel` and `bench` (hatch config from T-01). Inside a container the server must bind `0.0.0.0`. `keel serve` gains optional `--host` and `--port` flags that override `server.host` / `server.port`.

```python
# src/keel/cli.py (existing): build_parser(), main(argv); serve -> load_config(args.config); uvicorn.run(create_app(cfg), host=cfg.server.host, port=cfg.server.port)
```

## Files
Modify: `pyproject.toml`, `src/keel/cli.py`.
Create: `Dockerfile`, `.dockerignore`.
Read: `pyproject.toml`, `src/keel/cli.py`.

## Implement
1. `pyproject.toml` `[project]`:
   - `readme = "README.md"` (README comes in T-38; create an empty placeholder only if the build fails without it)
   - `authors = [{name = "Hamza Aslam"}]`
   - `keywords = ["llm", "proxy", "compaction", "agents", "benchmark"]`
   - classifiers for Python 3.11 and MIT
   - `[project.urls] Repository = "https://github.com/<owner>/keel"`, left as a literal placeholder for HUMAN to edit
2. `cli.py`: `serve` gets `--host` (default None) and `--port` (type int, default None); when set, they override the config values.
3. `Dockerfile`:
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY bench ./bench
RUN pip install --no-cache-dir .
EXPOSE 8400
VOLUME ["/config", "/data"]
CMD ["keel", "serve", "--config", "/config/keel.yaml", "--host", "0.0.0.0", "--port", "8400"]
```
4. `.dockerignore`: `.venv`, `.git`, `results`, `models`, `viewer`, `**/__pycache__`, `*.db`, `tests`, `docs`, `scenarios`.

## Tests
Create `tests/test_cli_serve_flags.py`. That makes a 5th file, which is allowed because `.dockerignore` is data-only. Keep the test under 30 lines.
- `test_serve_overrides(monkeypatch, tmp_path)`: patch `keel.cli.uvicorn.run` to capture its kwargs, write a minimal config file, and run `main(["serve", "--config", p, "--host", "0.0.0.0", "--port", "9999"])` → captured `host == "0.0.0.0"` and `port == 9999`.

## Acceptance
```bash
uv run pytest tests/test_cli_serve_flags.py -q
uv build
uv run --isolated --no-project --with dist/keel_proxy-0.1.0-py3-none-any.whl keel --help
```
If Docker is available, also run `docker build -t keel-proxy .` and check it exits 0. If Docker is not available, note "docker not run" in PROGRESS (HUMAN H-11 verifies it on a clean machine).

## Out of scope
Publishing to PyPI, the README content (T-38), the viewer image.

## Depends on
T-19

---
## Implementer protocol
1. Read only this task file and the files it lists.
2. Do not change any contract from ARCHITECTURE.md. If a contract seems wrong, stop and write the problem to docs/BLOCKERS.md.
3. Run the Acceptance commands. The task is done only when all of them pass.
4. Append one line to docs/PROGRESS.md: task ID, date, files changed, test result.
5. No new dependencies unless the task names them.
