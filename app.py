import hashlib
import io
import re
import tarfile
from typing import Any

import requests
from flask import Flask, Response, abort, request

app = Flask(__name__)

MAX_OUTPUT_BYTES = 50 * 1024 * 1024  # 50 MB limit for repacked tarball
_SAFE_PARAM = re.compile(r"^[A-Za-z0-9._-]+$")

_session = requests.Session()
_session.headers["User-Agent"] = "gitpkg-selfhost/1.0"


@app.route("/health")
def health():
    return "ok"


@app.route("/<user>/<repo>/<path:subdir>")
@app.route("/https://github.com/<user>/<repo>/tree/<commit>/<path:subdir>")
def pkg(user: str, repo: str, subdir: str, commit: str | None = None):
    if commit is None:
        qs = request.query_string.decode()
        commit = request.args.get("commit") or (qs if qs and "=" not in qs else "") or "main"

    # Validate inputs
    for param in (user, repo, commit):
        if not _SAFE_PARAM.match(param):
            abort(400, "Invalid characters in URL")

    subdir = subdir.rstrip("/") + "/"

    # Fetch full-repo tarball from GitHub
    codeload_url = f"https://codeload.github.com/{user}/{repo}/tar.gz/{commit}"

    # HEAD — skip download, no useful headers to return without repack
    if request.method == "HEAD":
        return Response(mimetype="application/gzip")

    upstream = _session.get(codeload_url, stream=True, timeout=(5, 60))
    if upstream.status_code != 200:
        upstream.close()
        abort(upstream.status_code, f"GitHub returned {upstream.status_code}")

    upstream.raw.decode_content = True

    # Stream the tarball, filter to subdir, repack with package/ prefix
    try:
        tgz_bytes = _repack(upstream.raw, subdir)
    except ValueError:
        abort(413, "Subdirectory too large to serve")
    finally:
        upstream.close()
    if tgz_bytes is None:
        abort(404, f"Subdirectory '{subdir}' not found in {user}/{repo}@{commit}")

    etag = hashlib.sha256(tgz_bytes).hexdigest()[:16]
    if request.headers.get("If-None-Match") == etag:
        return Response(status=304)

    safe_subdir = re.sub(r"[^\w.-]", "-", subdir)
    filename = f"{user}-{repo}-{safe_subdir}{commit[:12]}.tgz"
    return Response(
        tgz_bytes,
        mimetype="application/gzip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "ETag": etag,
            "Cache-Control": "public, immutable, max-age=31536000",
        },
    )


def _repack(stream: Any, subdir: str) -> bytes | None:
    """Extract subdir from streamed tarball and repack as npm-compatible tgz."""
    out_buf = io.BytesIO()

    found = False
    full_prefix = ""

    with tarfile.open(fileobj=stream, mode="r|gz") as src:
        with tarfile.open(fileobj=out_buf, mode="w:gz") as dst:
            for member in src:
                # First entry is the repo root dir, e.g. "wagmi-8fe5291/"
                if not full_prefix:
                    full_prefix = member.name.split("/")[0] + "/" + subdir
                    continue

                # Check if entry is inside the target subdir
                if not member.name.startswith(full_prefix):
                    continue

                # Only allow regular files and directories
                if not (member.isfile() or member.isdir()):
                    continue

                found = True

                # Copy member info with remapped name
                relative = member.name[len(full_prefix):]
                info = tarfile.TarInfo(name="package/" + relative if relative else "package")
                info.size = member.size if member.isfile() else 0
                info.mode = member.mode
                info.type = member.type
                info.mtime = member.mtime

                fileobj = src.extractfile(member) if member.isfile() else None
                dst.addfile(info, fileobj)

                if out_buf.tell() > MAX_OUTPUT_BYTES:
                    raise ValueError("Output tarball too large")

    if not found:
        return None

    return out_buf.getvalue()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
