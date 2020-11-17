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

from unittest.mock import MagicMock

from unit_tests.test_utils import CharmTestCase, patch_open

import lib.swift_storage_context as swift_context


TO_PATCH = [
    'config',
    'log',
    'related_units',
    'relation_get',
    'relation_ids',
    'unit_private_ip',
    'get_ipv6_addr',
]


class SwiftStorageContextTests(CharmTestCase):

    def setUp(self):
        super(SwiftStorageContextTests, self).setUp(swift_context, TO_PATCH)
        self.config.side_effect = self.test_config.get

    def test_swift_storage_context_missing_data(self):
        self.relation_ids.return_value = []
        ctxt = swift_context.SwiftStorageContext()
        self.assertEqual(ctxt(), {})
        self.relation_ids.return_value = ['swift-proxy:0']
        self.related_units.return_value = ['swift-proxy/0']
        self.relation_get.return_value = ''
        self.assertEqual(ctxt(), {})

    def test_swift_storage_context_with_data(self):
        self.relation_ids.return_value = []
        ctxt = swift_context.SwiftStorageContext()
        self.assertEqual(ctxt(), {})
        self.relation_ids.return_value = ['swift-proxy:0']
        self.related_units.return_value = ['swift-proxy/0']
        self.relation_get.return_value = 'fooooo'
        self.assertEqual(ctxt(), {'swift_hash': 'fooooo'})

    def test_rsync_context(self):
        self.unit_private_ip.return_value = '10.0.0.5'
        ctxt = swift_context.RsyncContext()
        ctxt.enable_rsyncd = MagicMock()
        ctxt.enable_rsyncd.return_value = True
        self.assertEqual({'local_ip': '10.0.0.5'}, ctxt())
        self.assertTrue(ctxt.enable_rsyncd.called)

    def test_rsync_context_ipv6(self):
        self.test_config.set('prefer-ipv6', True)
        self.get_ipv6_addr.return_value = ['2001:db8:1::1']
        ctxt = swift_context.RsyncContext()
        ctxt.enable_rsyncd = MagicMock()
        ctxt.enable_rsyncd.return_value = True
        self.assertEqual({'local_ip': '2001:db8:1::1'}, ctxt())
        self.assertTrue(ctxt.enable_rsyncd.called)

    def test_rsync_enable_rsync(self):
        with patch_open() as (_open, _file):
            ctxt = swift_context.RsyncContext()
            _file.read.return_value = 'RSYNC_ENABLE=false'
            ctxt.enable_rsyncd()
            _file.write.assert_called_with('RSYNC_ENABLE=true')
            _file.read.return_value = '#foo'
            ctxt.enable_rsyncd()
            _file.write.assert_called_with('RSYNC_ENABLE=true\n')

    def test_swift_storage_lockup_timeout_too_low(self):
        self.test_config.set('object-rsync-timeout', 1000)
        self.test_config.set('object-lockup-timeout', 1050)
        ctxt = swift_context.SwiftStorageServerContext()
        result = ctxt()
        ex = {
            'object_rsync_timeout': 1000,
            'object_lockup_timeout': 2010,
        }
        self.assertDictContainsSubset(ex, result)

    def test_swift_storage_server_context(self):
        self.unit_private_ip.return_value = '10.0.0.5'
        self.test_config.set('account-server-port', '500')
        self.test_config.set('account-server-port-rep', '510')
        self.test_config.set('object-server-port', '501')
        self.test_config.set('object-server-port-rep', '511')
        self.test_config.set('container-server-port', '502')
        self.test_config.set('container-server-port-rep', '512')
        self.test_config.set('object-server-threads-per-disk', '3')
        self.test_config.set('object-replicator-concurrency', '3')
        self.test_config.set('account-max-connections', '10')
        self.test_config.set('container-max-connections', '10')
        self.test_config.set('object-max-connections', '10')
        self.test_config.set('object-rsync-timeout', 950)
        self.test_config.set('object-lockup-timeout', 3000)
        self.test_config.set('object-handoffs-first', True)
        self.test_config.set('file-allocation-reserve', '10737418240')
        ctxt = swift_context.SwiftStorageServerContext()
        result = ctxt()
        ex = {
            'container_server_port': '502',
            'container_server_port_rep': '512',
            'object_server_port': '501',
            'object_server_port_rep': '511',
            'account_server_port': '500',
            'account_server_port_rep': '510',
            'local_ip': '10.0.0.5',
            'object_server_threads_per_disk': '3',
            'object_replicator_concurrency': '3',
            'account_max_connections': '10',
            'container_max_connections': '10',
            'object_max_connections': '10',
            'object_rsync_timeout': 950,
            'object_lockup_timeout': 3000,
            'fallocate_reserve': '10737418240',
            'standalone_replicator': True,
            'object_handoffs_first': True,
            'statsd_host': '',
            'statsd_port': 3125,
            'statsd_sample_rate': 1.0
        }
        self.assertEqual(ex, result)
