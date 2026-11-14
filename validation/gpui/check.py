#!/usr/bin/env python3
"""Compile and run selected Markdown recipes against a verified Zed checkout."""

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


REVISION = "4c7244790a075e862eeb4e5ccc12d6c8f5da6f7e"
ROOT = Path(__file__).resolve().parents[2]
REFERENCES = ROOT / "skills/gpui/references"
RECIPES = {
    "entity_test": [("test-reference.md", "entity-test")],
    "event_test": [("test-reference.md", "event-test")],
    "async_test": [("test-reference.md", "async-test")],
    "timer_test": [("test-reference.md", "timer-test")],
    "deferred_test": [("test-reference.md", "deferred-test")],
    "simple_text": [
        ("element-examples.md", "simple-text"),
        ("element-examples.md", "simple-text-test"),
    ],
}


def revision(path):
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True, text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def extract(filename, name):
    document = (REFERENCES / filename).read_text()
    marker = f"<!-- gpui-check: {name} -->"
    if document.count(marker) != 1:
        raise ValueError(f"{filename}: expected exactly one {marker}")
    match = re.match(r"\s*```rust\n(.*?)\n```(?:\n|$)", document.split(marker)[1], re.S)
    if not match:
        raise ValueError(f"{filename}: {name} must precede a complete Rust fence")
    return match.group(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zed-checkout", type=Path, help="checkout at the recorded revision")
    parser.add_argument("--target-dir", type=Path, default=ROOT / "validation/gpui/target")
    parser.add_argument("--online", action="store_true", help="allow Cargo to download missing dependencies")
    args = parser.parse_args()

    checkout = args.zed_checkout
    if checkout is None:
        cached = Path.home() / ".cargo/git/checkouts"
        checkout = next((p for p in sorted(cached.glob("zed-*/*")) if revision(p) == REVISION), None)
    if checkout is None or revision(checkout) != REVISION:
        parser.error(f"provide --zed-checkout at {REVISION}; the default searches Cargo's cache")
    checkout = checkout.resolve()
    # A matching HEAD does not establish that the source is unchanged.
    if subprocess.run(["git", "-C", str(checkout), "diff", "--quiet", "HEAD"]).returncode:
        parser.error("the Zed checkout has tracked modifications; use a clean checkout")

    modules = []
    for name, blocks in RECIPES.items():
        source = "\n\n".join(extract(*block) for block in blocks)
        modules.append(f"mod {name} {{\n{source}\n}}")

    with tempfile.TemporaryDirectory(prefix="skills-gpui-check-") as directory:
        fixture = Path(directory)
        (fixture / "src").mkdir()
        (fixture / "src/lib.rs").write_text("\n\n".join(modules) + "\n")
        # Start from the pinned workspace lock, rather than resolving every
        # transitive dependency afresh. Cargo adds the generated consumer package
        # and prunes unrelated workspace packages in this disposable copy.
        shutil.copyfile(checkout / "Cargo.lock", fixture / "Cargo.lock")
        manifest = '''[package]
name = "skills-gpui-validation"
version = "0.1.0"
edition = "2024"

[dependencies]
gpui = { path = GPUI_PATH, default-features = false, features = ["test-support"] }

[patch.crates-io]
async-task = { git = "https://github.com/smol-rs/async-task.git", rev = "b4486cd71e4e94fbda54ce6302444de14f4d190e" }

[profile.dev]
debug = 0
'''.replace("GPUI_PATH", json.dumps(str(checkout / "crates/gpui")))
        (fixture / "Cargo.toml").write_text(manifest)
        command = [
            "cargo", "test", "--quiet", "--lib", "--manifest-path", str(fixture / "Cargo.toml"),
            "--target-dir", str(args.target_dir.resolve()),
        ]
        if not args.online:
            command.append("--offline")
        print(f"Checking {len(RECIPES)} Markdown recipes against Zed {REVISION}", flush=True)
        subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
