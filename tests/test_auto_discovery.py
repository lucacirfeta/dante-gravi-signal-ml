"""Tests for discover_references() from src.utils."""

import pytest
from pathlib import Path

from src.utils import discover_references


class TestDiscoverReferences:
    def test_discover_finds_indomain_files(self, tmp_path):
        """Indomain .npz files should be discovered and returned sorted."""
        (tmp_path / "indomain_o4a_h1.npz").touch()
        (tmp_path / "indomain_o3b_l1.npz").touch()

        refs = discover_references(reference_dir=tmp_path)

        assert len(refs) == 2
        assert refs[0].name == "indomain_o3b_l1.npz"
        assert refs[1].name == "indomain_o4a_h1.npz"

    def test_discover_excludes_non_indomain(self, tmp_path):
        """Files that don't start with 'indomain' should be ignored."""
        (tmp_path / "gravity_spy_index.npz").touch()
        (tmp_path / "other_file.txt").touch()

        refs = discover_references(reference_dir=tmp_path)

        assert refs == []

    def test_discover_nonexistent_dir(self, tmp_path):
        """A non-existent directory should return an empty list, not raise."""
        refs = discover_references(reference_dir=tmp_path / "does_not_exist")

        assert refs == []

    def test_discover_mixed(self, tmp_path):
        """Only indomain*.npz files should be returned, regardless of name."""
        (tmp_path / "indomain_index.npz").touch()       # old format
        (tmp_path / "indomain_o4a_h1.npz").touch()      # new format
        (tmp_path / "gravity_spy_index.npz").touch()     # non-indomain

        refs = discover_references(reference_dir=tmp_path)

        assert len(refs) == 2
        names = [r.name for r in refs]
        assert "indomain_index.npz" in names
        assert "indomain_o4a_h1.npz" in names
        assert "gravity_spy_index.npz" not in names

    def test_discover_default_dir(self):
        """The default directory should be Path('data/reference')."""
        import inspect

        sig = inspect.signature(discover_references)
        default = sig.parameters["reference_dir"].default

        assert default == Path("data/reference")
