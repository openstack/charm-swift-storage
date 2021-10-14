#!/usr/bin/python3
#
# Copyright 2016 Canonical Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import argparse
import os
import sys
import yaml

_path = os.path.dirname(os.path.realpath(__file__))
_root = os.path.abspath(os.path.join(_path, '..'))


def _add_path(path):
    if path not in sys.path:
        sys.path.insert(1, path)


_add_path(_root)

from charmhelpers.core.host import service_pause, service_resume
from charmhelpers.core.hookenv import action_fail
from charmhelpers.core.unitdata import HookData, kv
from charmhelpers.contrib.openstack.utils import (
    get_os_codename_package,
    set_os_workload_status,
    CompareOpenStackReleases,
)
from lib.swift_storage_utils import (
    assess_status,
    REQUIRED_INTERFACES,
    SWIFT_SVCS,
)
from hooks.swift_storage_hooks import (
    CONFIGS,
)


def _get_services():
    """Return a list of services that need to be (un)paused."""
    services = SWIFT_SVCS[:]
    # Before Icehouse there was no swift-container-sync
    _os_release = get_os_codename_package("swift-container")
    if CompareOpenStackReleases(_os_release) < "icehouse":
        services.remove("swift-container-sync")
    return services


def get_action_parser(actions_yaml_path, action_name,
                      get_services=_get_services):
    """Make an argparse.ArgumentParser seeded from actions.yaml definitions."""
    with open(actions_yaml_path) as fh:
        doc = yaml.safe_load(fh)[action_name]["description"]
    parser = argparse.ArgumentParser(description=doc)
    parser.add_argument("--services", default=get_services())
    # TODO: Add arguments for params defined in the actions.yaml
    return parser


def pause(args):
    """Pause all the swift services.

    @raises Exception if any services fail to stop
    """
    for service in args.services:
        stopped = service_pause(service)
        if not stopped:
            raise Exception("{} didn't stop cleanly.".format(service))
    with HookData()():
        kv().set('unit-paused', True)
    set_os_workload_status(CONFIGS, REQUIRED_INTERFACES,
                           charm_func=assess_status)


def resume(args):
    """Resume all the swift services.

    @raises Exception if any services fail to start
    """
    for service in args.services:
        started = service_resume(service)
        if not started:
            raise Exception("{} didn't start cleanly.".format(service))
    with HookData()():
        kv().set('unit-paused', False)
    set_os_workload_status(CONFIGS, REQUIRED_INTERFACES,
                           charm_func=assess_status)


# A dictionary of all the defined actions to callables (which take
# parsed arguments).
ACTIONS = {"pause": pause, "resume": resume}


def main(argv):
    action_name = _get_action_name()
    actions_yaml_path = _get_actions_yaml_path()
    parser = get_action_parser(actions_yaml_path, action_name)
    args = parser.parse_args(argv)
    try:
        action = ACTIONS[action_name]
    except KeyError:
        return "Action {} undefined".format(action_name)
    else:
        try:
            action(args)
        except Exception as e:
            action_fail(str(e))


def _get_action_name():
    """Return the name of the action."""
    return os.path.basename(__file__)


def _get_actions_yaml_path():
    """Return the path to actions.yaml"""
    cwd = os.path.dirname(__file__)
    return os.path.join(cwd, "..", "actions.yaml")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
