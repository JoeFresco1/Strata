from __future__ import annotations

import os

import uvicorn


def main() -> None:
    """Run the self-hosted single-process API and built React application."""
    uvicorn.run(
        "serve_api:app",
        host=os.getenv("STRATA_HOST", "127.0.0.1"),
        port=int(os.getenv("STRATA_PORT", "8000")),
        proxy_headers=True,
        forwarded_allow_ips=os.getenv("STRATA_FORWARDED_ALLOW_IPS", "127.0.0.1"),
    )


if __name__ == "__main__":
    main()
