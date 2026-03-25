# Contributing

Contributions are welcome! This project is a read-only Monzo banking integration for Claude Code.

## Getting Started

1. Fork the repository
2. Clone your fork
3. Install dependencies: `pip install -r mcp-server/requirements.txt`
4. Create a feature branch: `git checkout -b feature/your-feature`
5. Make your changes and test
6. Submit a pull request

## Guidelines

- Keep tools **read-only** by default. Write operations belong in Phase 2 and must be gated behind `MONZO_ENABLE_WRITE_OPS=true`.
- Never log or expose access tokens, refresh tokens, or client secrets.
- Follow existing code patterns (async httpx, FastMCP decorators).
- Update `SKILL.md` if you add new tools or change behavior.
- Test against the live Monzo API before submitting.

## Security

If you discover a security vulnerability, please report it privately rather than opening a public issue.
