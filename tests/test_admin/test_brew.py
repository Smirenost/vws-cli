"""
Tests for Homebrew and Linuxbrew.
"""

import logging
import subprocess
from pathlib import Path

import docker
from docker.types import Mount
from dulwich.repo import Repo

from admin.homebrew import get_homebrew_formula

LOGGER = logging.getLogger(__name__)


def _create_archive(directory: Path) -> Path:
    # Homebrew requires the archive name to look like a valid version.
    version = '1'
    archive_name = '{version}.tar.gz'.format(version=version)
    archive_file = directory / archive_name
    archive_file.touch()
    # We do not use ``dulwich.porcelain.archive`` because it has no option to
    # use a gzip format.
    args = [
        'git',
        'archive',
        '--format',
        'tar.gz',
        '-o',
        str(archive_file),
        '--prefix',
        '{version}/'.format(version=version),
        'HEAD',
    ]
    subprocess.run(args=args, check=True)
    return archive_file


def test_create_local_brewfile(tmp_path: Path) -> None:
    """
    Show that it is at least possible to write some brew file, whether that
    actually installs or not.
    """
    local_repository = Repo('.')
    archive_file = _create_archive(directory=tmp_path)
    # The path needs to look like a versioned artifact to Homebrew/Linuxbrew.
    local_archive_url = 'file://' + str(archive_file)
    head_url = 'file://' + str(Path(local_repository.path).absolute())
    homebrew_filename = 'vws.rb'

    homebrew_formula_contents = get_homebrew_formula(
        archive_url=local_archive_url,
        head_url=head_url,
        homebrew_recipe_filename=homebrew_filename,
    )

    homebrew_file = tmp_path / homebrew_filename
    homebrew_file.write_text(homebrew_formula_contents)
    # For local testing:
    # import pyperclip; pyperclip.copy(str(homebrew_file))
    #
    # Then:
    # $ brew install --debug <PASTE>


def test_brew(tmp_path: Path) -> None:
    """
    It is possible to create a Homebrew formula and to install this with
    Linuxbrew.

    This requires ``pip install docker`` and for Docker to be running.
    """
    local_repository = Repo('.')
    archive_file = _create_archive(directory=tmp_path)

    client = docker.from_env(version='auto')
    linuxbrew_image = 'linuxbrew/linuxbrew'
    # The path needs to look like a versioned artifact to Linuxbrew.
    container_archive_path = '/' + archive_file.stem
    container_archive_url = 'file://' + container_archive_path
    head_url = 'file://' + str(Path(local_repository.path).absolute())
    homebrew_filename = 'vws.rb'

    homebrew_formula_contents = get_homebrew_formula(
        archive_url=container_archive_url,
        head_url=head_url,
        homebrew_recipe_filename=homebrew_filename,
    )

    homebrew_file = tmp_path / homebrew_filename
    homebrew_file.write_text(homebrew_formula_contents)
    container_homebrew_file_path = '/' + homebrew_filename

    archive_mount = Mount(
        source=str(archive_file.resolve().absolute()),
        target=container_archive_path,
        type='bind',
    )

    homebrew_file_mount = Mount(
        source=str(homebrew_file.resolve().absolute()),
        target=container_homebrew_file_path,
        type='bind',
    )

    mounts = [archive_mount, homebrew_file_mount]
    client.images.pull(repository=linuxbrew_image, tag='latest')
    # Locally it is useful to run ``brew install`` with ``-v`` to expose
    # issues.
    # However, this produces a log which is too long for Travis CI.
    #
    # We see
    # "The job exceeded the maximum log length, and has been terminated.".
    command_list = [
        'brew',
        'install',
        container_homebrew_file_path,
        '&&',
        'vws',
        '--version',
    ]

    command = '/bin/bash -c "{command}"'.format(
        command=' '.join(command_list),
    )

    container = client.containers.create(
        image=linuxbrew_image,
        mounts=mounts,
        command=command,
        environment={'HOMEBREW_NO_AUTO_UPDATE': 1},
    )

    container.start()
    for line in container.logs(stream=True):
        line = line.decode().strip()
        LOGGER.info(line)

    status_code = container.wait()['StatusCode']
    assert status_code == 0
    container.remove(force=True)
