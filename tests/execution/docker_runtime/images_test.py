"""Tests for Docker image build caching."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from docker.errors import ImageNotFound

from slop_code.execution.docker_runtime.images import BASE_IMAGE_HASH_LABEL
from slop_code.execution.docker_runtime.images import NODE_RELEASE
from slop_code.execution.docker_runtime.images import _build_image
from slop_code.execution.docker_runtime.images import _get_base_image_hash
from slop_code.execution.docker_runtime.images import build_base_image
from slop_code.execution.docker_runtime.images import build_submission_image
from slop_code.execution.docker_runtime.images import make_base_image
from slop_code.execution.docker_runtime.models import DockerEnvironmentSpec


def _mock_image(hash_value: str | None) -> MagicMock:
    image = MagicMock()
    labels = {} if hash_value is None else {BASE_IMAGE_HASH_LABEL: hash_value}
    image.attrs = {"Config": {"Labels": labels}}
    return image


def test_build_base_image_reuses_current_image(
    docker_spec: DockerEnvironmentSpec,
) -> None:
    client = MagicMock()
    current_hash = _get_base_image_hash(docker_spec)
    current_image = _mock_image(current_hash)

    with (
        patch(
            "slop_code.execution.docker_runtime.images._find_image",
            return_value=current_image,
        ),
        patch(
            "slop_code.execution.docker_runtime.images._build_image"
        ) as build,
    ):
        result = build_base_image(client, docker_spec)

    assert result is current_image
    build.assert_not_called()


def test_build_base_image_rebuilds_stale_image(
    docker_spec: DockerEnvironmentSpec,
) -> None:
    client = MagicMock()
    stale_image = _mock_image(None)
    rebuilt_image = MagicMock()

    with (
        patch(
            "slop_code.execution.docker_runtime.images._find_image",
            return_value=stale_image,
        ),
        patch(
            "slop_code.execution.docker_runtime.images._build_image",
            return_value=rebuilt_image,
        ) as build,
    ):
        result = build_base_image(client, docker_spec)

    assert result is rebuilt_image
    build.assert_called_once()

    context_tar = build.call_args.args[2]
    with tarfile.open(fileobj=context_tar) as context:
        dockerfile = context.extractfile("Dockerfile")
        assert dockerfile is not None
        rendered_dockerfile = dockerfile.read().decode()

    assert "xz-utils" in rendered_dockerfile
    assert (
        "# Install the canonical pinned Node release directly with checksum verification."
        in rendered_dockerfile
    )
    assert f"ENV NODE_VERSION={NODE_RELEASE.version}" in rendered_dockerfile
    assert (
        "https://nodejs.org/dist/v${NODE_VERSION}/${NODE_TARBALL}"
        in rendered_dockerfile
    )
    assert "sha256sum --check --status" in rendered_dockerfile
    assert (
        'tar --extract --xz --file="/tmp/${NODE_TARBALL}"'
        in rendered_dockerfile
    )
    assert "NVM_DIR" not in rendered_dockerfile


def test_make_base_image_rejects_node_version_drift(
    docker_spec: DockerEnvironmentSpec,
) -> None:
    drifted_spec = docker_spec.model_copy(
        update={
            "environment": docker_spec.environment.model_copy(
                update={"env": {"NODE_VERSION": "20.0.0"}}
            )
        }
    )

    with pytest.raises(
        ValueError,
        match="NODE_VERSION must match the pinned Node release",
    ):
        make_base_image(drifted_spec)


def test_build_submission_image_rebuilds_stale_base_image(
    docker_spec: DockerEnvironmentSpec,
    tmp_path: Path,
) -> None:
    client = MagicMock()
    submission_path = tmp_path / "submission"
    submission_path.mkdir()
    (submission_path / "solution.py").write_text("print('ok')\n")

    stale_base_image = _mock_image(None)
    submission_image = MagicMock()

    with (
        patch(
            "slop_code.execution.docker_runtime.images._find_image",
            side_effect=[stale_base_image, None],
        ),
        patch(
            "slop_code.execution.docker_runtime.images.build_base_image",
            return_value=MagicMock(),
        ) as build_base,
        patch(
            "slop_code.execution.docker_runtime.images._build_image",
            return_value=submission_image,
        ),
    ):
        image_name, built_image = build_submission_image(
            client,
            submission_path,
            docker_spec,
            {},
            build_base=False,
        )

    assert image_name.startswith("slop-code:submission-")
    assert built_image is submission_image
    build_base.assert_called_once_with(
        client,
        docker_spec,
        force_build=True,
    )


def test_build_image_falls_back_to_tag_lookup_after_sdk_image_not_found() -> (
    None
):
    client = MagicMock()
    tagged_image = MagicMock()
    client.images.build.side_effect = ImageNotFound("missing")
    client.images.get.return_value = tagged_image

    result = _build_image(
        "slop-code:test-image",
        client,
        io.BytesIO(b"docker context"),
    )

    assert result is tagged_image
    client.images.get.assert_called_once_with("slop-code:test-image")
