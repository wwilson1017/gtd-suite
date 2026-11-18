# Contributing

Pull requests are welcome. Keep changes small and explain what they do in plain words.
Read [AGENTS.md](AGENTS.md) for the rules that are easy to break.

For local development, install uv and Node 22, then run:

```sh
uv sync
cd frontend && npm ci && cd ..
OPEN_SIGNUP=true uv run uvicorn backend.main:app --workers 1 --reload
```

In another terminal, run `cd frontend && npm run dev` and open the address Vite prints.
Run `scripts/check.sh` before opening a pull request. See [README.md](README.md) for
settings and running the built app.

Contributions are accepted under the MIT license. The paid folder is part of the repo,
and changes to it are welcome too. What the hosted service sells is its owner's call.
