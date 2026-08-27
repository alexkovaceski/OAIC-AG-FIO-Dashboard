"""house_style: the prompt-side wiring of the house-style repo.

Hermetic: the linked .house-style/ folder may or may not exist on the machine
running the suite, so every test repoints _STYLE_DIR at a temp dir.
"""
import sys
sys.path.insert(0, "src")
import house_style
from house_style import load_style_block


def test_load_style_block_reads_the_linked_files(tmp_path, monkeypatch):
    monkeypatch.setattr(house_style, "_STYLE_DIR", tmp_path)
    (tmp_path / "voice.md").write_text("# Voice\n\nShort, AU spelling.",
                                       encoding="utf-8")
    (tmp_path / "tropes.md").write_text("# Tropes\n\nNo delve.",
                                        encoding="utf-8")
    block = load_style_block()
    assert "Short, AU spelling." in block
    assert "No delve." in block


def test_load_style_block_ignores_missing_files(tmp_path, monkeypatch):
    # one of the two style files missing still yields the other, never a crash
    monkeypatch.setattr(house_style, "_STYLE_DIR", tmp_path)
    (tmp_path / "voice.md").write_text("# Voice\n\nOnly voice.",
                                       encoding="utf-8")
    assert load_style_block() == "# Voice\n\nOnly voice."


def test_load_style_block_falls_back_when_repo_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(house_style, "_STYLE_DIR", tmp_path / "absent")
    block = load_style_block()
    assert "House style" in block
    assert "em dash" in block
    assert "AU spelling" in block
