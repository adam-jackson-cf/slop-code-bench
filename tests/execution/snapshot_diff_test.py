"""Tests for snapshot diff functionality."""

import io
import tarfile
import tempfile
from pathlib import Path

import pytest

from slop_code.execution.models import ExecutionError
from slop_code.execution.snapshot import FileChangeType
from slop_code.execution.snapshot import FileDiff
from slop_code.execution.snapshot import Snapshot
from slop_code.execution.snapshot import _create_text_file_diff
from slop_code.execution.snapshot import _decode_text
from slop_code.execution.snapshot import _is_binary


class TestIsBinary:
    """Test binary file detection."""

    def test_null_byte_is_binary(self):
        """Files with null bytes are binary."""
        assert _is_binary(b"hello\x00world")

    def test_text_is_not_binary(self):
        """Plain text is not binary."""
        assert not _is_binary(b"Hello, world!\n")

    def test_empty_is_not_binary(self):
        """Empty data is not binary."""
        assert not _is_binary(b"")

    def test_high_non_printable_ratio_is_binary(self):
        """High ratio of non-printable characters means binary."""
        # Create data with lots of non-printable bytes
        data = bytes(range(256)) * 10
        assert _is_binary(data)

    def test_tabs_and_newlines_allowed(self):
        """Tabs and newlines don't count as binary."""
        assert not _is_binary(b"line1\nline2\n\ttabbed")


class TestDecodeText:
    """Test text decoding."""

    def test_utf8_decode(self):
        """UTF-8 text decodes correctly."""
        text = "Hello, 世界!"
        assert _decode_text(text.encode("utf-8")) == text

    def test_latin1_decode(self):
        """Latin-1 text decodes correctly."""
        text = "Héllo, wörld!"
        assert _decode_text(text.encode("latin-1")) == text

    def test_non_utf8_bytes_decode_as_latin1(self):
        """Non-UTF-8 bytes use the Latin-1 fallback without data loss."""
        assert _decode_text(b"\x80\x9f\xff") == "\x80\x9fÿ"


class TestCreateTextFileDiff:
    """Test individual text file diff creation."""

    def test_created_text_file(self):
        """Test diff for a newly created text file."""
        content = "line1\nline2\nline3\n"
        diff = _create_text_file_diff(
            Path("test.txt"),
            None,
            content,
            FileChangeType.CREATED,
        )
        assert diff.change_type == FileChangeType.CREATED
        assert not diff.is_binary
        assert diff.lines_added == 3
        assert diff.lines_removed == 0

    def test_deleted_text_file(self):
        """Test diff for a deleted text file."""
        content = "line1\nline2\n"
        diff = _create_text_file_diff(
            Path("test.txt"),
            content,
            None,
            FileChangeType.DELETED,
        )
        assert diff.change_type == FileChangeType.DELETED
        assert not diff.is_binary
        assert diff.lines_added == 0
        assert diff.lines_removed == 2

    def test_modified_text_file(self):
        """Test diff for a modified text file."""
        old_content = "line1\nline2\nline3\n"
        new_content = "line1\nmodified\nline3\nnew line\n"
        diff = _create_text_file_diff(
            Path("test.txt"),
            old_content,
            new_content,
            FileChangeType.MODIFIED,
        )
        assert diff.change_type == FileChangeType.MODIFIED
        assert not diff.is_binary
        assert diff.lines_added > 0
        assert diff.lines_removed > 0


class TestSnapshot:
    """Test archive snapshot functionality."""

    @pytest.fixture
    def temp_workspace(self, tmp_path):
        """Create a temporary workspace with some files."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        # Create some initial files
        (workspace / "file1.txt").write_text("line1\nline2\n")
        (workspace / "file2.txt").write_text("hello\nworld\n")
        (workspace / "subdir").mkdir()
        (workspace / "subdir" / "file3.txt").write_text("nested\nfile\n")

        return workspace

    def test_archive_snapshot_extract_contents(self, temp_workspace):
        """Test extracting contents from an archive snapshot."""
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot = Snapshot.from_directory(
                cwd=temp_workspace,
                env={},
                save_path=Path(tmpdir),
            )

            contents = snapshot.extract_contents()

            assert Path("file1.txt") in contents
            assert Path("file2.txt") in contents
            assert Path("subdir/file3.txt") in contents
            assert contents[Path("file1.txt")] == b"line1\nline2\n"

    def test_archive_snapshot_extract_text_contents(self, temp_workspace):
        """Test extracting text contents from an archive snapshot."""
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot = Snapshot.from_directory(
                cwd=temp_workspace,
                env={},
                save_path=Path(tmpdir),
            )

            contents = snapshot.extract_text_contents()

            assert Path("file1.txt") in contents
            assert Path("file2.txt") in contents
            assert Path("subdir/file3.txt") in contents
            assert contents[Path("file1.txt")] == "line1\nline2\n"

    def test_archive_snapshot_restores_modes_and_links(self, temp_workspace):
        """Snapshots preserve executable files and safe symbolic and hard links."""
        executable = temp_workspace / "run.sh"
        executable.write_text("#!/bin/sh\nexit 0\n")
        executable.chmod(0o755)
        (temp_workspace / "run-link").symlink_to("run.sh")
        (temp_workspace / "run-hard-link").hardlink_to(executable)

        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot = Snapshot.from_directory(
                cwd=temp_workspace,
                env={},
                save_path=Path(tmpdir),
            )
            restored = Path(tmpdir) / "restored"
            restored.mkdir()
            snapshot.extract_to_path(restored)

            assert (restored / "run.sh").stat().st_mode & 0o111
            assert (restored / "run-link").is_symlink()
            assert (restored / "run-link").readlink() == Path("run.sh")
            assert (restored / "run-hard-link").stat().st_ino == (
                restored / "run.sh"
            ).stat().st_ino

    @pytest.mark.parametrize(
        ("member_type", "link_target"),
        [
            (tarfile.SYMTYPE, "/outside"),
            (tarfile.SYMTYPE, "../../outside"),
            (tarfile.FIFOTYPE, ""),
        ],
    )
    def test_archive_snapshot_rejects_unsafe_members_before_mutation(
        self, tmp_path: Path, member_type: bytes, link_target: str
    ):
        """Unsafe archive entries leave an existing destination untouched."""
        archive = tmp_path / "unsafe.tar.gz"
        with tarfile.open(archive, "w:gz") as tf:
            safe = tarfile.TarInfo("safe.txt")
            safe_data = b"safe"
            safe.size = len(safe_data)
            tf.addfile(safe, io.BytesIO(safe_data))
            unsafe = tarfile.TarInfo("unsafe")
            unsafe.type = member_type
            unsafe.linkname = link_target
            tf.addfile(unsafe)

        snapshot = Snapshot(
            path=tmp_path,
            archive=archive,
            checksum="unused",
        )
        target = tmp_path / "target"
        target.mkdir()
        sentinel = target / "sentinel.txt"
        sentinel.write_text("unchanged")

        with pytest.raises(ExecutionError, match="Unsafe|Unsupported"):
            snapshot.extract_to_path(target)

        assert sentinel.read_text() == "unchanged"
        assert not (target / "safe.txt").exists()

    def test_archive_snapshot_diff_no_changes(self, temp_workspace):
        """Test diff with no changes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot1 = Snapshot.from_directory(
                cwd=temp_workspace,
                env={},
                save_path=Path(tmpdir),
            )
            snapshot2 = Snapshot.from_directory(
                cwd=temp_workspace,
                env={},
                save_path=Path(tmpdir),
            )

            diff = snapshot1.diff(snapshot2)

            assert len(diff.file_diffs) == 0

    def test_archive_snapshot_diff_file_created(self, temp_workspace):
        """Test diff when a file is created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # First snapshot
            snapshot1 = Snapshot.from_directory(
                cwd=temp_workspace,
                env={},
                save_path=Path(tmpdir),
            )

            # Create a new file
            (temp_workspace / "new_file.txt").write_text("new content\n")

            # Second snapshot
            snapshot2 = Snapshot.from_directory(
                cwd=temp_workspace,
                env={},
                save_path=Path(tmpdir),
            )

            diff = snapshot1.diff(snapshot2)

            assert len(diff.file_diffs) == 1
            assert Path("new_file.txt") in diff.file_diffs
            file_diff = diff.file_diffs[Path("new_file.txt")]
            assert file_diff.change_type == FileChangeType.CREATED
            assert not file_diff.is_binary

    def test_archive_snapshot_diff_file_deleted(self, temp_workspace):
        """Test diff when a file is deleted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # First snapshot
            snapshot1 = Snapshot.from_directory(
                cwd=temp_workspace,
                env={},
                save_path=Path(tmpdir),
            )

            # Delete a file
            (temp_workspace / "file1.txt").unlink()

            # Second snapshot
            snapshot2 = Snapshot.from_directory(
                cwd=temp_workspace,
                env={},
                save_path=Path(tmpdir),
            )

            diff = snapshot1.diff(snapshot2)

            assert len(diff.file_diffs) == 1
            assert Path("file1.txt") in diff.file_diffs
            file_diff = diff.file_diffs[Path("file1.txt")]
            assert file_diff.change_type == FileChangeType.DELETED

    def test_archive_snapshot_diff_file_modified(self, temp_workspace):
        """Test diff when a file is modified."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # First snapshot
            snapshot1 = Snapshot.from_directory(
                cwd=temp_workspace,
                env={},
                save_path=Path(tmpdir),
            )

            # Modify a file
            (temp_workspace / "file1.txt").write_text("modified\ncontent\n")

            # Second snapshot
            snapshot2 = Snapshot.from_directory(
                cwd=temp_workspace,
                env={},
                save_path=Path(tmpdir),
            )

            diff = snapshot1.diff(snapshot2)

            assert len(diff.file_diffs) == 1
            assert Path("file1.txt") in diff.file_diffs
            file_diff = diff.file_diffs[Path("file1.txt")]
            assert file_diff.change_type == FileChangeType.MODIFIED
            assert not file_diff.is_binary

    def test_archive_snapshot_diff_multiple_changes(self, temp_workspace):
        """Test diff with multiple file changes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # First snapshot
            snapshot1 = Snapshot.from_directory(
                cwd=temp_workspace,
                env={},
                save_path=Path(tmpdir),
            )

            # Make multiple changes
            (temp_workspace / "file1.txt").write_text("modified\n")
            (temp_workspace / "file2.txt").unlink()
            (temp_workspace / "new.txt").write_text("new\n")

            # Second snapshot
            snapshot2 = Snapshot.from_directory(
                cwd=temp_workspace,
                env={},
                save_path=Path(tmpdir),
            )

            diff = snapshot1.diff(snapshot2)

            assert len(diff.file_diffs) == 3
            assert (
                diff.file_diffs[Path("file1.txt")].change_type
                == FileChangeType.MODIFIED
            )
            assert (
                diff.file_diffs[Path("file2.txt")].change_type
                == FileChangeType.DELETED
            )
            assert (
                diff.file_diffs[Path("new.txt")].change_type
                == FileChangeType.CREATED
            )

    def test_archive_snapshot_diff_binary_file(self, temp_workspace):
        """Test diff with binary files (should be excluded from text-only diff)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # First snapshot
            snapshot1 = Snapshot.from_directory(
                cwd=temp_workspace,
                env={},
                save_path=Path(tmpdir),
            )

            # Create a binary file
            (temp_workspace / "binary.bin").write_bytes(b"hello\x00world")

            # Second snapshot
            snapshot2 = Snapshot.from_directory(
                cwd=temp_workspace,
                env={},
                save_path=Path(tmpdir),
            )

            diff = snapshot1.diff(snapshot2)

            # Binary files are not included in text-only diff
            assert len(diff.file_diffs) == 0


class TestFileDiffRepr:
    """Test FileDiff string representations."""

    def test_created_text_repr(self):
        """Test repr for created text file."""
        diff = FileDiff(
            path=Path("test.txt"),
            change_type=FileChangeType.CREATED,
            lines_added=0,
        )
        repr_str = repr(diff)
        assert "CREATED" in repr_str
        assert "test.txt" in repr_str

    def test_deleted_binary_repr(self):
        """Test repr for deleted binary file."""
        diff = FileDiff(
            path=Path("test.bin"),
            change_type=FileChangeType.DELETED,
            is_binary=True,
            old_size=1024,
        )
        repr_str = repr(diff)
        assert "DELETED" in repr_str
        assert "1024" in repr_str

    def test_modified_binary_repr(self):
        """Test repr for modified binary file."""
        diff = FileDiff(
            path=Path("test.bin"),
            change_type=FileChangeType.MODIFIED,
            is_binary=True,
            old_size=1024,
            new_size=2048,
        )
        repr_str = repr(diff)
        assert "MODIFIED" in repr_str
        assert "1024" in repr_str
        assert "2048" in repr_str


class TestSnapshotDiffRepr:
    """Test SnapshotDiff string representation."""

    @pytest.fixture
    def temp_workspace(self, tmp_path):
        """Create a temporary workspace with some files."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        # Create some initial files
        (workspace / "file1.txt").write_text("line1\nline2\n")
        (workspace / "file2.txt").write_text("hello\nworld\n")
        (workspace / "subdir").mkdir()
        (workspace / "subdir" / "file3.txt").write_text("nested\nfile\n")

        return workspace

    def test_snapshot_diff_repr(self, temp_workspace):
        """Test repr for snapshot diff."""
        with tempfile.TemporaryDirectory() as tmpdir:
            snapshot1 = Snapshot.from_directory(
                cwd=temp_workspace,
                env={},
                save_path=Path(tmpdir),
            )

            # Make changes
            (temp_workspace / "file1.txt").write_text("modified\n")
            (temp_workspace / "file2.txt").unlink()
            (temp_workspace / "new.txt").write_text("new\n")

            snapshot2 = Snapshot.from_directory(
                cwd=temp_workspace,
                env={},
                save_path=Path(tmpdir),
            )

            diff = snapshot1.diff(snapshot2)
            repr_str = repr(diff)

            assert "+1" in repr_str  # 1 created
            assert "-1" in repr_str  # 1 deleted
            assert "~1" in repr_str  # 1 modified
