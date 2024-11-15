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
import sys

import tempfile
import unittest

from unittest import mock
import yaml

from unit_tests.test_utils import CharmTestCase

from unittest.mock import patch, MagicMock

# python-apt is not installed as part of test-requirements but is imported by
# some charmhelpers modules so create a fake import.
sys.modules['apt'] = MagicMock()
sys.modules['apt_pkg'] = MagicMock()

with patch('charmhelpers.contrib.hardening.harden.harden') as \
        mock_dec:
    mock_dec.side_effect = (lambda *dargs, **dkwargs: lambda f:
                            lambda *args, **kwargs: f(*args, **kwargs))
    with patch('lib.misc_utils.is_paused') as is_paused:
        with patch('lib.swift_storage_utils.register_configs'):
            import actions.actions


class PauseTestCase(CharmTestCase):

    def setUp(self):
        super(PauseTestCase, self).setUp(
            actions.actions, ["service_pause", "HookData", "kv",
                              "set_os_workload_status"])

        class FakeArgs(object):
            services = ['swift-account',
                        'swift-account-auditor',
                        'swift-account-reaper',
                        'swift-account-replicator',
                        'swift-container',
                        'swift-container-auditor',
                        'swift-container-updater',
                        'swift-container-replicator',
                        'swift-container-sync',
                        'swift-object',
                        'swift-object-auditor',
                        'swift-object-updater',
                        'swift-object-replicator']
        self.args = FakeArgs()

    def test_pauses_services(self):
        """Pause action pauses all of the Swift services."""
        pause_calls = []

        def fake_service_pause(svc):
            pause_calls.append(svc)
            return True

        self.service_pause.side_effect = fake_service_pause

        actions.actions.pause(self.args)
        self.assertEqual(pause_calls, ['swift-account',
                                       'swift-account-auditor',
                                       'swift-account-reaper',
                                       'swift-account-replicator',
                                       'swift-container',
                                       'swift-container-auditor',
                                       'swift-container-updater',
                                       'swift-container-replicator',
                                       'swift-container-sync',
                                       'swift-object',
                                       'swift-object-auditor',
                                       'swift-object-updater',
                                       'swift-object-replicator'])

    def test_bails_out_early_on_error(self):
        """Pause action fails early if there are errors stopping a service."""
        pause_calls = []

        def maybe_kill(svc):
            if svc == "swift-container":
                return False
            else:
                pause_calls.append(svc)
                return True

        self.service_pause.side_effect = maybe_kill
        self.assertRaisesRegex(
            Exception, "swift-container didn't stop cleanly.",
            actions.actions.pause, self.args)
        self.assertEqual(pause_calls, ['swift-account',
                                       'swift-account-auditor',
                                       'swift-account-reaper',
                                       'swift-account-replicator'])

    def test_pause_sets_value(self):
        """Pause action sets the unit-paused value to True."""
        self.HookData()().return_value = True

        actions.actions.pause(self.args)
        self.kv().set.assert_called_with('unit-paused', True)


class ResumeTestCase(CharmTestCase):

    def setUp(self):
        super(ResumeTestCase, self).setUp(
            actions.actions, ["service_resume", "HookData", "kv",
                              "set_os_workload_status"])

        class FakeArgs(object):
            services = ['swift-account',
                        'swift-account-auditor',
                        'swift-account-reaper',
                        'swift-account-replicator',
                        'swift-container',
                        'swift-container-auditor',
                        'swift-container-updater',
                        'swift-container-replicator',
                        'swift-container-sync',
                        'swift-object',
                        'swift-object-auditor',
                        'swift-object-updater',
                        'swift-object-replicator']
        self.args = FakeArgs()

    def test_resumes_services(self):
        """Resume action resumes all of the Swift services."""
        resume_calls = []

        def fake_service_resume(svc):
            resume_calls.append(svc)
            return True

        self.service_resume.side_effect = fake_service_resume
        actions.actions.resume(self.args)
        self.assertEqual(resume_calls, ['swift-account',
                                        'swift-account-auditor',
                                        'swift-account-reaper',
                                        'swift-account-replicator',
                                        'swift-container',
                                        'swift-container-auditor',
                                        'swift-container-updater',
                                        'swift-container-replicator',
                                        'swift-container-sync',
                                        'swift-object',
                                        'swift-object-auditor',
                                        'swift-object-updater',
                                        'swift-object-replicator'])

    def test_bails_out_early_on_error(self):
        """Resume action fails early if there are errors starting a service."""
        resume_calls = []

        def maybe_kill(svc):
            if svc == "swift-container":
                return False
            else:
                resume_calls.append(svc)
                return True

        self.service_resume.side_effect = maybe_kill
        self.assertRaisesRegex(
            Exception, "swift-container didn't start cleanly.",
            actions.actions.resume, self.args)
        self.assertEqual(resume_calls, ['swift-account',
                                        'swift-account-auditor',
                                        'swift-account-reaper',
                                        'swift-account-replicator'])

    def test_resume_sets_value(self):
        """Resume action sets the unit-paused value to False."""
        self.HookData()().return_value = True

        actions.actions.resume(self.args)
        self.kv().set.assert_called_with('unit-paused', False)


class GetActionParserTestCase(unittest.TestCase):

    def test_definition_from_yaml(self):
        """ArgumentParser is seeded from actions.yaml."""
        actions_yaml = tempfile.NamedTemporaryFile(
            prefix="GetActionParserTestCase", suffix="yaml")
        actions_yaml.write(
            yaml.dump({"foo": {"description": "Foo is bar"}}).encode('utf-8'))
        actions_yaml.seek(0)
        parser = actions.actions.get_action_parser(actions_yaml.name, "foo",
                                                   get_services=lambda: [])
        self.assertEqual(parser.description, 'Foo is bar')


class MainTestCase(CharmTestCase):

    def setUp(self):
        super(MainTestCase, self).setUp(
            actions.actions, ["_get_action_name",
                              "get_action_parser",
                              "action_fail"])

    def test_invokes_pause(self):
        dummy_calls = []

        def dummy_action(args):
            dummy_calls.append(True)

        self._get_action_name.side_effect = lambda: "foo"
        self.get_action_parser = lambda: argparse.ArgumentParser()
        with mock.patch.dict(actions.actions.ACTIONS, {"foo": dummy_action}):
            actions.actions.main([])
        self.assertEqual(dummy_calls, [True])

    def test_unknown_action(self):
        """Unknown actions aren't a traceback."""
        self._get_action_name.side_effect = lambda: "foo"
        self.get_action_parser = lambda: argparse.ArgumentParser()
        exit_string = actions.actions.main([])
        self.assertEqual("Action foo undefined", exit_string)

    def test_failing_action(self):
        """Actions which traceback trigger action_fail() calls."""
        dummy_calls = []

        self.action_fail.side_effect = dummy_calls.append
        self._get_action_name.side_effect = lambda: "foo"

        def dummy_action(args):
            raise ValueError("uh oh")

        self.get_action_parser = lambda: argparse.ArgumentParser()
        with mock.patch.dict(actions.actions.ACTIONS, {"foo": dummy_action}):
            actions.actions.main([])
        self.assertEqual(dummy_calls, ["uh oh"])
