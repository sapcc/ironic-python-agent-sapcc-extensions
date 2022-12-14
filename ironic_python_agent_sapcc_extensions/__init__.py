# Copyright 2015 Rackspace, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import contextlib
import os
import stat
import tempfile
import textwrap
from urllib.parse import urlparse

from oslo_concurrency import processutils
from oslo_log import log
from oslo_serialization import jsonutils

from ironic_python_agent.extensions import base
from ironic_python_agent.extensions import image
from ironic_python_agent import utils

LOG = log.getLogger(__name__)


def _mount_partition(partition, path):
    if not os.path.ismount(path):
        LOG.debug(
            "Attempting to mount %(device)s to %(path)s to " "partition.",
            {"device": partition, "path": path},
        )
        try:
            utils.execute("mount", partition, path)
        except processutils.ProcessExecutionError as e:
            # NOTE(TheJulia): It seems in some cases,
            # the python os.path.ismount can return False
            # even *if* it is actually mounted. This appears
            # to be becasue it tries to rely on inode on device
            # logic, yet the rules are sometimes different inside
            # ramdisks. So lets check the error first.
            if "already mounted" not in e:
                # Raise the error, since this is not a known
                # failure case
                raise
            else:
                LOG.debug("Partition already mounted, proceeding.")


class SapCc(base.BaseAgentExtension):
    MOUNT_PATH = "/mnt"
    METADATA_PATH = "/openstack/2018-08-27/meta_data.json"

    @base.sync_command("install_vsmp_memoryone")
    def install_vsmp_memoryone(self, **kwargs):
        """Yadda yadda"""
        instance_info = self.agent.node.get("instance_info", {})
        traits = instance_info.get("traits", [])
        if "CUSTOM_VSMP_MEMORYONE" not in traits:
            return {"info": "required trait missing"}

        with (self._mount_config_drive(), open(self.MOUNT_PATH + self.METADATA_PATH, mode="rb") as f):
            meta_data = jsonutils.load(f)
            vsmp_version = meta_data.get("meta", {}).get("sap.cloud.vsmp-version", "latest")

        image_properties = instance_info.get("image_properties", {})
        image_url = image_properties.get("direct_url")
        if not image_url:
            return {"info": "no image_url"}

        image_url = urlparse(image_url)
        if not image_url.netloc:
            return {"info": "could no parse image_url"}

        domain = image_url.netloc.split(".", 1)[1]
        url = f"https://repo.{domain}/memoryone/{{vsmp_installer-{vsmp_version}.sh,license.txt}}"

        with tempfile.TemporaryDirectory() as path:
            script_path = f"{path}/install.sh"
            with open(script_path, mode="w", encoding="utf8") as script:
                script.write(
                    textwrap.dedent(
                        f"""\
                    #!/bin/bash
                    set -Eeuo pipefail
                    shopt -s nullglob
                    cd /etc
                    [ -f resolv.conf ] ||
                      ln -s ../run/systemd/resolve/stub-resolv.conf resolv.conf
                    cd "{path}"
                    curl --retry 5 -sfZO "{url}"
                    chmod +x ./vsmp_installer*
                    ./vsmp_installer* in -q -n *.txt 2>&1
                    rm -f /etc/resolv.conf
                    """
                    )
                )
            st = os.stat(script_path)
            os.chmod(script_path, st.st_mode | stat.S_IEXEC)

            with contextlib.ExitStack() as stack:
                stack.enter_context(self._mount_root())
                stack.enter_context(self._mount_for_chroot())
                stack.enter_context(self._mount_tmp_for_chroot())
                stack.enter_context(self._mount_efivars_for_chroot())
                bytes_io = utils.get_command_output(["chroot", self.MOUNT_PATH, script_path])
                log = bytes_io.read().decode("utf8")

            return {"log": log, "status": "success"}

    @contextlib.contextmanager
    def _mount_config_drive(self):
        try:
            _mount_partition("LABEL=config-2", self.MOUNT_PATH)
            yield
        finally:
            utils.execute("umount", self.MOUNT_PATH)

    @contextlib.contextmanager
    def _mount_root(self):
        try:
            _mount_partition("LABEL=ROOT", self.MOUNT_PATH)
            yield
        finally:
            utils.execute("umount", self.MOUNT_PATH)

    @contextlib.contextmanager
    def _mount_for_chroot(self):
        try:
            image._mount_for_chroot(self.MOUNT_PATH)
            yield
        finally:
            image._umount_all_partitions(
                self.MOUNT_PATH,
                path_variable=image._get_path_variable(),
                umount_warn_msg="",
            )

    @contextlib.contextmanager
    def _mount_tmp_for_chroot(self):
        try:
            utils.execute("mount", "-o", "bind", "/tmp", self.MOUNT_PATH + "/tmp")
            yield
        finally:
            utils.execute("umount", self.MOUNT_PATH + "/tmp")

    @contextlib.contextmanager
    def _mount_efivars_for_chroot(self):
        try:
            utils.execute("mount", "-t", "efivarfs", "efivarfs", self.MOUNT_PATH + "/sys/firmware/efi/efivars")
            yield
        finally:
            utils.execute("umount", self.MOUNT_PATH + "/sys/firmware/efi/efivars")
