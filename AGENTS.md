# Repository Guidelines

## Project Structure & Module Organization

Hermes Pet is split between a WSL Python bridge and a Windows WPF overlay. Python source lives in `src/`: `event_schema.py` validates events, `state_mapper.py` infers Hermes state from SQLite, `bridge_watcher.py` polls `~/.hermes/profiles/phantom/state.db`, and `test_events.py` sends fake overlay events. Pytest coverage lives in `tests/`. The WPF app is under `src/wpf/HermesPet/`; treat its `bin/` and `obj/` subfolders as generated output. Root `bin/` contains launchers, `assets/pets/` contains sprite packs, and `docs/` plus `reports/` hold architecture notes.

## Build, Test, and Development Commands

- `bash pet.sh test`: run all Python tests with `python3 -m pytest tests/ -v`.
- `bash pet.sh watcher`: start the WSL bridge watcher against the default phantom profile database.
- `bash pet.sh test-bridge`: perform a one-shot database state check.
- `bash pet.sh test-fake`: send sample events to an already running overlay.
- `bash pet.sh install-deps`: install Python test dependencies in WSL.
- `cd src\wpf\HermesPet && dotnet build -c Release`: build the .NET 8 Windows overlay from PowerShell or CMD.
- `dotnet run -- --port 5731`: run the overlay locally during Windows development.

## Coding Style & Naming Conventions

Use four-space indentation in Python and C#. Python uses `snake_case` functions, `PascalCase` classes, type hints, `Path` for filesystem paths, and dataclasses for structured events. Keep event names and Hermes states aligned with `src/event_schema.py`. C# uses nullable reference types, `PascalCase` public members, `camelCase` locals, and XML summaries for user-facing classes.

## Testing Guidelines

Add pytest tests in `tests/` using files named `test_<module>.py`, classes named `Test<Feature>`, and methods named `test_<expected_behavior>`. Cover schema validation, state inference, bridge polling edge cases, and protocol send/receive behavior. Run `bash pet.sh test` before Python changes; for WPF changes, also run `dotnet build -c Release` on Windows.

## Commit & Pull Request Guidelines

This checkout has an empty `.git` directory, so no local history is available to infer a convention. Use concise imperative commits with an optional scope, such as `bridge: handle missing state db` or `overlay: preserve window position`. Pull requests should describe WSL and Windows surfaces touched, list verification commands, link related reports/issues, and include screenshots or clips for overlay or sprite changes.

## Security & Configuration Tips

Keep Hermes databases, runtime logs, and local machine paths out of new commits unless they are intentional fixtures. Default traffic is local HTTP on `127.0.0.1:5731`; document port or profile-path changes in `README.md` and the relevant report.
