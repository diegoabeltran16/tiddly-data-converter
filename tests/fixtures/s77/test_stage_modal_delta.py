from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from python_scripts.stage_modal_delta import compare_and_stage


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def record(record_id: str, title: str, role: str, content: dict | None = None) -> dict:
    payload = {
        "schema_version": "v0",
        "id": record_id,
        "key": title,
        "title": title,
        "canonical_slug": title.replace(" ", "-"),
        "version_id": "sha256:" + record_id[-1] * 64,
        "content_type": "image/png" if role == "asset" else "text/markdown",
        "modality": "image" if role == "asset" else "text",
        "encoding": "base64" if role == "asset" else "utf-8",
        "is_binary": role == "asset",
        "is_reference_only": False,
        "role_primary": role,
        "text": "aGVsbG8=" if role == "asset" else "body",
        "source_type": "image/png" if role == "asset" else "text/markdown",
        "source_position": f"fixture:{title}",
        "created": "20260430000000000",
        "modified": "20260430000000000",
    }
    if content is not None:
        payload["content"] = content
    return payload


class StageModalDeltaTests(unittest.TestCase):
    def test_stages_only_missing_asset_projection(self) -> None:
        with tempfile.TemporaryDirectory(prefix="s77_modal_delta_") as raw_tmp:
            tmp = Path(raw_tmp)
            canon_dir = tmp / "canon"
            normalized = tmp / "normalized.jsonl"
            out_dir = tmp / "out"

            live_asset = record("00000000-0000-5000-8000-000000000001", "asset missing", "asset")
            live_text = record(
                "00000000-0000-5000-8000-000000000002",
                "text changed in normalized",
                "note",
                {"plain": "body"},
            )
            live_asset_already = record(
                "00000000-0000-5000-8000-000000000003",
                "asset already projected",
                "asset",
                {"projection_kind": "asset", "modalities": ["asset"], "asset": {"payload_present": False}},
            )
            write_jsonl(canon_dir / "tiddlers_1.jsonl", [live_asset, live_text, live_asset_already])

            normalized_asset = dict(live_asset)
            normalized_asset["content"] = {
                "projection_kind": "asset",
                "modalities": ["asset"],
                "asset": {
                    "mime_type": "image/png",
                    "encoding": "base64",
                    "payload_present": True,
                },
            }
            normalized_text = dict(live_text)
            normalized_text["content"] = {"plain": "body", "references": [{"kind": "url", "target": "https://example.test", "source": "bare_url"}]}
            write_jsonl(normalized, [normalized_asset, normalized_text, live_asset_already])

            report = compare_and_stage(canon_dir, normalized, out_dir, scope="asset-content")

            self.assertEqual(report["comparison"]["changed_line_count"], 2)
            self.assertEqual(report["comparison"]["field_change_counts"], {"content": 2})
            self.assertEqual(report["delta"]["selected_count"], 1)
            self.assertEqual(report["delta"]["ignored_changed_lines"], 1)

            patch = read_jsonl(out_dir / "modal-assets.patch.jsonl")
            self.assertEqual(len(patch), 1)
            self.assertEqual(patch[0]["id"], live_asset["id"])
            self.assertEqual(patch[0]["changed_fields"], ["content"])

            staged = read_jsonl(out_dir / "staged-canon" / "tiddlers_1.jsonl")
            self.assertIn("asset", staged[0]["content"])
            self.assertEqual(staged[1], live_text)
            self.assertEqual(staged[2], live_asset_already)


if __name__ == "__main__":
    unittest.main()
