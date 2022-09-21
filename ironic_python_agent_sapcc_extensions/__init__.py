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

from oslo_log import log

from ironic_python_agent.extensions import base
from ironic_python_agent import utils

LOG = log.getLogger(__name__)


class SapCc(base.BaseAgentExtension):
    @base.sync_command('run')
    def run(self):
        """Yadda yadda"""
        instance_info = self.agent.node.get("instance_info", {})
        traits = instance_info.get("traits", [])
        if "CUSTOM_VSMP_MEMORYONE" not in traits:
            return {"status": "required trait missing"}
        image_properties = instance_info.get("image_properties")
        if not image_properties:
            return {"status": "image property missing"}

        url = image_properties.get("sapcc.post_install_script_url")
        log = utils.get_command_output(["bash", "-c", "curl -sSL " + url + " | bash"])
        compact = utils.gzip_and_b64encode(io_dict={"log": log})
        return {"log": compact, "status": "success"}
