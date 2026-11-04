"""``python -m clay_embeddings [--data DIR]``: run the server over stdio."""

from __future__ import annotations

import argparse

from clay_embeddings.server import build_server


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m clay_embeddings")
    parser.add_argument(
        "--data",
        help="staged directory or file (default: $CLAY_EMBEDDINGS_DATA or data/embeddings)",
    )
    args = parser.parse_args()
    build_server(args.data).run("stdio")


if __name__ == "__main__":
    main()
