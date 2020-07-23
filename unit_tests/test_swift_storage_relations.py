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

from unittest.mock import patch
import json
import os
import tempfile
import uuid

from unit_tests.test_utils import CharmTestCase, TestKV, patch_open

with patch('charmhelpers.contrib.hardening.harden.harden') as mock_dec:
    mock_dec.side_effect = (lambda *dargs, **dkwargs: lambda f:
                            lambda *args, **kwargs: f(*args, **kwargs))
    with patch('lib.misc_utils.is_paused') as is_paused:
        with patch('lib.swift_storage_utils.register_configs') as _:
            import hooks.swift_storage_hooks as hooks

from lib.swift_storage_utils import PACKAGES

TO_PATCH = [
    'CONFIGS',
    # charmhelpers.core.hookenv
    'Hooks',
    'config',
    'log',
    'network_get_primary_address',
    'relation_set',
    'relation_ids',
    'relation_get',
    'relations_of_type',
    # charmhelpers.core.host
    'apt_update',
    'apt_install',
    'filter_installed_packages',
    # charmehelpers.contrib.openstack.utils
    'configure_installation_source',
    'openstack_upgrade_available',
    # swift_storage_utils
    'do_openstack_upgrade',
    'ensure_swift_directories',
    'execd_preinstall',
    'fetch_swift_rings',
    'save_script_rc',
    'setup_rsync',
    'rsync',
    'setup_storage',
    'register_configs',
    'update_nrpe_config',
    'get_relation_ip',
    'status_set',
    'set_os_workload_status',
    'os_application_version_set',
    'add_to_updatedb_prunepath',
    'ufw',
    'setup_ufw',
    'revoke_access',
    'kv',
    'create_sysctl',
]


UFW_DUMMY_RULES = b"""
# Don't delete these required lines, otherwise there will be errors
*filter
:ufw-before-input - [0:0]
:ufw-before-output - [0:0]
:ufw-before-forward - [0:0]
:ufw-not-local - [0:0]
# End required lines


# allow all on loopback
-A ufw-before-input -i lo -j ACCEPT
-A ufw-before-output -o lo -j ACCEPT
"""


class SwiftStorageRelationsTests(CharmTestCase):

    def setUp(self):
        super(SwiftStorageRelationsTests, self).setUp(hooks, TO_PATCH)
        self.config.side_effect = self.test_config.get
        self.relation_get.side_effect = self.test_relation.get
        self.get_relation_ip.return_value = '10.10.10.2'
        self.test_kv = TestKV()
        self.kv.return_value = self.test_kv

    @patch.object(hooks, 'add_ufw_gre_rule', lambda *args: None)
    def test_prunepath(self):
        hooks.config_changed()
        self.add_to_updatedb_prunepath.assert_called_with("/srv/node")

    @patch.object(hooks, 'add_ufw_gre_rule', lambda *args: None)
    @patch('lib.swift_storage_utils.swift_init')
    def test_install_hook(self, mock_swift_init):
        mock_swift_init.return_value = 0
        self.test_config.set('openstack-origin', 'cloud:precise-havana')
        hooks.install()
        self.configure_installation_source.assert_called_with(
            'cloud:precise-havana',
        )
        self.assertTrue(self.apt_update.called)
        self.apt_install.assert_called_with(PACKAGES, fatal=True)
        self.assertTrue(self.execd_preinstall.called)

    @patch.object(hooks, 'add_ufw_gre_rule', lambda *args: None)
    def test_config_changed_no_upgrade_available(self):
        self.openstack_upgrade_available.return_value = False
        self.relations_of_type.return_value = False
        with patch_open() as (_open, _file):
            _file.read.return_value = "foo"
            hooks.config_changed()
        self.assertFalse(self.do_openstack_upgrade.called)
        self.assertTrue(self.CONFIGS.write_all.called)
        self.assertTrue(self.setup_rsync.called)

    @patch.object(hooks, 'add_ufw_gre_rule', lambda *args: None)
    def test_config_changed_upgrade_available(self):
        self.openstack_upgrade_available.return_value = True
        self.relations_of_type.return_value = False
        with patch_open() as (_open, _file):
            _file.read.return_value = "foo"
            hooks.config_changed()
        self.assertTrue(self.do_openstack_upgrade.called)
        self.assertTrue(self.CONFIGS.write_all.called)

    @patch.object(hooks, 'add_ufw_gre_rule', lambda *args: None)
    def test_config_changed_with_openstack_upgrade_action(self):
        self.openstack_upgrade_available.return_value = True
        self.test_config.set('action-managed-upgrade', True)

        with patch_open() as (_open, _file):
            _file.read.return_value = "foo"
            hooks.config_changed()

        self.assertFalse(self.do_openstack_upgrade.called)

    @patch.object(hooks, 'add_ufw_gre_rule', lambda *args: None)
    def test_config_changed_nrpe_master(self):
        self.openstack_upgrade_available.return_value = False
        self.relations_of_type.return_value = True
        with patch_open() as (_open, _file):
            _file.read.return_value = "foo"
            hooks.config_changed()
        self.assertTrue(self.CONFIGS.write_all.called)
        self.assertTrue(self.setup_rsync.called)
        self.assertTrue(self.update_nrpe_config.called)

    @patch.object(hooks, 'add_ufw_gre_rule', lambda *args: None)
    @patch.object(hooks, 'assert_charm_supports_ipv6')
    def test_config_changed_ipv6(self, mock_assert_charm_supports_ipv6):
        self.test_config.set('prefer-ipv6', True)
        self.openstack_upgrade_available.return_value = False
        self.relations_of_type.return_value = False
        with patch_open() as (_open, _file):
            _file.read.return_value = "foo"
            hooks.config_changed()
        self.assertTrue(self.CONFIGS.write_all.called)
        self.assertTrue(self.setup_rsync.called)

    @patch.object(hooks, 'add_ufw_gre_rule', lambda *args: None)
    @patch.object(hooks, 'ensure_devs_tracked')
    @patch.object(hooks, 'get_os_codename_install_source')
    def test_upgrade_charm(self, mock_get_os_codename_install_source,
                           mock_ensure_devs_tracked):
        mock_get_os_codename_install_source.return_value = 'stein'
        hooks.upgrade_charm()
        self.apt_install.assert_called_with(
            ['gdisk', 'lvm2', 'swift', 'swift-account',
             'swift-container', 'swift-object', 'python-jinja2',
             'python-psutil', 'ufw', 'xfsprogs',
             'libfile-readbackwards-perl', 'libtime-piece-perl'],
            fatal=True)
        self.assertTrue(self.update_nrpe_config.called)
        self.assertTrue(mock_ensure_devs_tracked.called)

    @patch('lib.swift_storage_utils.get_device_blkid',
           lambda dev: str(uuid.uuid4()))
    @patch.object(hooks.os, 'environ')
    @patch('lib.swift_storage_utils.os.path.isdir', lambda *args: True)
    @patch.object(hooks, 'relation_set')
    @patch('lib.swift_storage_utils.local_unit')
    @patch('lib.swift_storage_utils.relation_ids', lambda *args: [])
    @patch('lib.swift_storage_utils.KVStore')
    @patch.object(uuid, 'uuid4', lambda: 'a-test-uuid')
    def _test_storage_joined_single_device(self, mock_kvstore, mock_local_unit,
                                           mock_rel_set, mock_environ,
                                           env_key):
        test_uuid = uuid.uuid4()
        test_environ = {env_key: test_uuid}
        mock_environ.get.side_effect = test_environ.get
        mock_local_unit.return_value = 'test/0'
        kvstore = mock_kvstore.return_value
        kvstore.__enter__.return_value = kvstore
        kvstore.get.return_value = None
        self.test_kv.set('prepared-devices', ['/dev/vdb'])
        self.network_get_primary_address.return_value = "10.10.10.2"

        # py3 is very picky, and log is only patched in
        # hooks.swift_storage_hooks
        with patch('lib.swift_storage_utils.log'):
            hooks.swift_storage_relation_joined()

        self.get_relation_ip.assert_called_once_with('swift-storage')

        mock_rel_set.assert_called_with(
            relation_id=None,
            relation_settings={
                "ip_cls": "10.10.10.2",
                "ip_rep": "10.10.10.2",
                "private-address": "10.10.10.2",
                "region": 1,
                "zone": 1,
                "device": 'vdb',
                "account_port": 6002,
                "account_port_rep": 6012,
                "container_port": 6001,
                "container_port_rep": 6011,
                "object_port": 6000,
                "object_port_rep": 6010
            }
        )

        kvstore.get.return_value = None
        rel_settings = {}

        def fake_kv_set(key, value):
            rel_settings[key] = value

        kvstore.set.side_effect = fake_kv_set

        def fake_kv_get(key):
            return rel_settings.get(key)

        kvstore.get.side_effect = fake_kv_get
        devices = {"vdb@%s" % (test_uuid):
                   {"status": "active",
                    "blkid": 'a-test-uuid'}}
        kvstore.set.assert_called_with(
            key='devices', value=json.dumps(devices, sort_keys=True))

    def test_storage_joined_single_device_juju_1(self):
        '''Ensure use of JUJU_ENV_UUID for Juju < 2'''
        self._test_storage_joined_single_device(env_key='JUJU_ENV_UUID')

    def test_storage_joined_single_device_juju_2(self):
        '''Ensure use of JUJU_MODEL_UUID for Juju >= 2'''
        self._test_storage_joined_single_device(env_key='JUJU_MODEL_UUID')

    @patch('lib.swift_storage_utils.get_device_blkid',
           lambda dev: '%s-blkid-uuid' % os.path.basename(dev))
    @patch.object(hooks.os, 'environ')
    @patch('lib.swift_storage_utils.os.path.isdir', lambda *args: True)
    @patch('lib.swift_storage_utils.local_unit')
    @patch('lib.swift_storage_utils.relation_ids', lambda *args: [])
    @patch('lib.swift_storage_utils.KVStore')
    @patch.object(uuid, 'uuid4', lambda: 'a-test-uuid')
    def test_storage_joined_multi_device(self, mock_kvstore, mock_local_unit,
                                         mock_environ):
        test_uuid = uuid.uuid4()
        test_environ = {'JUJU_ENV_UUID': test_uuid}
        mock_environ.get.side_effect = test_environ.get
        self.test_kv.set('prepared-devices', ['/dev/vdb', '/dev/vdc',
                                              '/dev/vdd'])
        mock_local_unit.return_value = 'test/0'
        kvstore = mock_kvstore.return_value
        kvstore.__enter__.return_value = kvstore
        kvstore.get.return_value = None
        rel_settings = {}

        def fake_kv_set(key, value):
            rel_settings[key] = value

        kvstore.set.side_effect = fake_kv_set

        def fake_kv_get(key):
            return rel_settings.get(key)

        kvstore.get.side_effect = fake_kv_get

        # py3 is very picky, and log is only patched in
        # hooks.swift_storage_hooks
        with patch('lib.swift_storage_utils.log'):
            hooks.swift_storage_relation_joined()
        devices = {"vdb@%s" % (test_uuid): {"status": "active",
                                            "blkid": 'vdb-blkid-uuid'},
                   "vdd@%s" % (test_uuid): {"status": "active",
                                            "blkid": 'vdd-blkid-uuid'},
                   "vdc@%s" % (test_uuid): {"status": "active",
                                            "blkid": 'vdc-blkid-uuid'}}
        kvstore.set.assert_called_with(
            key='devices', value=json.dumps(devices, sort_keys=True)
        )
        self.get_relation_ip.assert_called_once_with('swift-storage')

    @patch('lib.swift_storage_utils.get_device_blkid',
           lambda dev: '%s-blkid-uuid' % os.path.basename(dev))
    @patch.object(hooks.os, 'environ')
    @patch('lib.swift_storage_utils.os.path.isdir', lambda *args: True)
    @patch('lib.swift_storage_utils.local_unit')
    @patch('lib.swift_storage_utils.relation_ids', lambda *args: [])
    @patch('lib.swift_storage_utils.KVStore')
    def test_storage_joined_dev_exists_unknown_juju_env_uuid(self,
                                                             mock_kvstore,
                                                             mock_local_unit,
                                                             mock_environ):
        test_uuid = uuid.uuid4()
        test_environ = {'JUJU_ENV_UUID': test_uuid}
        mock_environ.get.side_effect = test_environ.get
        self.test_kv.set('prepared-devices', ['/dev/vdb', '/dev/vdc',
                                              '/dev/vdd'])
        mock_local_unit.return_value = 'test/0'
        kvstore = mock_kvstore.return_value
        kvstore.__enter__.return_value = kvstore
        kvstore.get.return_value = None
        store = {'vdb@%s' % (uuid.uuid4()): {"status": "active",
                                             "blkid": 'vdb-blkid-uuid'}}

        def fake_kv_set(key, value):
            store[key] = value

        kvstore.set.side_effect = fake_kv_set

        def fake_kv_get(key):
            return store.get(key)

        kvstore.get.side_effect = fake_kv_get

        # py3 is very picky, and log is only patched in
        # hooks.swift_storage_hooks
        with patch('lib.swift_storage_utils.log'):
            hooks.swift_storage_relation_joined()

        devices = {"vdb@%s" % (test_uuid): {"status": "active",
                                            "blkid": 'vdb-blkid-uuid'},
                   "vdd@%s" % (test_uuid): {"status": "active",
                                            "blkid": 'vdd-blkid-uuid'},
                   "vdc@%s" % (test_uuid): {"status": "active",
                                            "blkid": 'vdc-blkid-uuid'}}
        kvstore.set.assert_called_with(
            key='devices', value=json.dumps(devices, sort_keys=True)
        )
        self.get_relation_ip.assert_called_once_with('swift-storage')

    @patch('sys.exit')
    def test_storage_changed_missing_relation_data(self, exit):
        hooks.swift_storage_relation_changed()
        exit.assert_called_with(0)

    def test_storage_changed_with_relation_data(self):
        self.test_relation.set({
            'swift_hash': 'foo_hash',
            'rings_url': 'http://swift-proxy.com/rings/',
        })
        hooks.swift_storage_relation_changed()
        self.CONFIGS.write.assert_called_with('/etc/swift/swift.conf')
        self.fetch_swift_rings.assert_called_with(
            'http://swift-proxy.com/rings/'
        )

    @patch('sys.argv', new=['dodah'])
    def test_main_hook_missing(self):
        hooks.main()
        self.assertTrue(self.log.called)

    def test_add_ufw_gre_rule(self):
        with tempfile.NamedTemporaryFile() as tmpfile:
            tmpfile.file.write(UFW_DUMMY_RULES)
            tmpfile.file.close()
            hooks.add_ufw_gre_rule(tmpfile.name)
