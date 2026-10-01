"""Serves cklxx/laya-browser as the TypeSafe-compatible /v1/systemone endpoint that jev-ultrafast calls."""

import os
import sys

from huggingface_hub import snapshot_download

REPO = "cklxx/laya-browser"
REVISION = "645cf366a2ae35f1086e8c20eff48f909bb49206"


def main():
    # The server code ships with the weights, so pinning the revision pins both.
    # One connection at a time: parallel downloads get reset by some networks; it is a one-off ~0.7 GB fetch.
    checkpoint = snapshot_download(
        REPO, revision=REVISION, ignore_patterns=["assets/*", "results/*", "code/*"], max_workers=1
    )
    sys.path.insert(0, checkpoint)
    from laya_browser import LayaBrowser

    LayaBrowser.from_pretrained(checkpoint).serve(
        port=int(os.environ.get("DECISION_PORT", "8791")),
        host=os.environ.get("DECISION_HOST", "127.0.0.1"),
    )


if __name__ == "__main__":
    main()
