# Copyright 2017 Canonical Ltd
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

import datetime
import sys
import unittest
import urllib

from unittest.mock import (
    patch,
    mock_open,
    MagicMock,
    Mock,
    PropertyMock,
)

sys.path.append('files/nrpe-external-master')
from check_swift_storage import (
    check_md5,
    check_replication,
    generate_md5,
    repl_last_timestamp,
)


STATUS_OK = 0
STATUS_WARN = 1
STATUS_CRIT = 2
STATUS_UNKNOWN = 3


class CheckSwiftStorageTestCase(unittest.TestCase):
    def test_generate_md5(self):
        """
        Ensure md5 checksum is generated from a file content
        """
        with patch("builtins.open", mock_open(read_data=b'data')) as \
                mock_file:
            result = generate_md5('path/to/file')
            mock_file.assert_called_with('path/to/file', 'rb')
            # md5 hash for 'data' string
            self.assertEqual(result,
                             '8d777f385d3dfec8815d20f7496026dc')

    @patch('urllib.request.urlopen')
    def test_check_md5_unknown_urlerror(self, mock_urlopen):
        """
        Force urllib.request.URLError to test try-except
        """
        base_url = 'http://localhost:6000/recon/'
        url = '{}ringmd5'.format(base_url)
        error = 'connection refused'
        mock_urlopen.side_effect = (urllib
                                    .error
                                    .URLError(Mock(return_value=error)))
        result = check_md5(base_url)
        self.assertEqual(result,
                         [(STATUS_UNKNOWN,
                           "Can't open url: {}".format(url))])

    @patch('urllib.request.urlopen')
    def test_check_md5_unknown_valueerror1(self, mock_urlopen):
        """
        Force ValueError on urllib.error.URLError to test try-except
        """
        base_url = 'asdfasdf'
        url = '{}ringmd5'.format(base_url)
        mock_urlopen.side_effect = ValueError(Mock(return_value=''))
        result = check_md5(base_url)
        mock_urlopen.assert_called_with(url)
        self.assertEqual(result,
                         [(STATUS_UNKNOWN,
                           "Can't parse status data")])

    @patch('urllib.request.urlopen')
    def test_check_md5_unknown_valueerror2(self, mock_urlopen):
        """
        Force ValueError on json to test try-catch
        """
        jdata = PropertyMock(return_value=b'X')
        mock_urlopen.return_value = MagicMock(read=jdata)
        result = check_md5('.')
        mock_urlopen.assert_called_with('.ringmd5')
        self.assertEqual(result,
                         [(STATUS_UNKNOWN,
                           "Can't parse status data")])

    @patch('check_swift_storage.generate_md5')
    def test_check_md5_unknown_ioerror(self, mock_generate_md5):
        """
        Force IOError (reading file) to test try-catch
        """
        jdata = b'{"/etc/swift/object.ring.gz": ' \
                b'"6b4f3a0ef3731f18291ecd053ce0d9b6", ' \
                b'"/etc/swift/account.ring.gz": ' \
                b'"93fc4ae496a7343362ebf13988a137e7", ' \
                b'"/etc/swift/container.ring.gz": ' \
                b'"0ea1ec9585ef644ce2b5c5b1dced4128"}'
        pmock_jdata = PropertyMock(return_value=jdata)
        mock_generate_md5.side_effect = IOError()
        with patch('urllib.request.urlopen') as mock_urlopen:
            mock_urlopen.return_value = MagicMock(read=pmock_jdata)
            result = check_md5('.')
            mock_urlopen.assert_called_with('.ringmd5')
            expected_result = [(STATUS_UNKNOWN,
                                "Can't open ringfile "
                                "/etc/swift/{}.ring.gz".format(name))
                               for name in ('object', 'account', 'container')]
            self.assertEqual(result, expected_result)

    @patch('check_swift_storage.generate_md5')
    def test_check_md5_crit_md5sum_mismatch(self, mock_generate_md5):
        """
        Ensure md5 checksums match, STATUS_CRIT
        """
        jdata = b'{"/etc/swift/object.ring.gz": ' \
                b'"6b4f3a0ef3731f18291ecd053ce0d9b6", ' \
                b'"/etc/swift/account.ring.gz": ' \
                b'"93fc4ae496a7343362ebf13988a137e7", ' \
                b'"/etc/swift/container.ring.gz": ' \
                b'"0ea1ec9585ef644ce2b5c5b1dced4128"}'
        pmock_jdata = PropertyMock(return_value=jdata)
        mock_generate_md5.return_value = 'xxxx'
        with patch('urllib.request.urlopen') as mock_urlopen:
            mock_urlopen.return_value = MagicMock(read=pmock_jdata)
            result = check_md5('.')
            mock_urlopen.assert_called_with('.ringmd5')
            expected_result = [(STATUS_CRIT,
                                'Ringfile /etc/swift/{}.ring.gz '
                                'MD5 sum mismatch'.format(name))
                               for name in ('object', 'account', 'container')]
            self.assertEqual(result, expected_result)

    @patch('check_swift_storage.generate_md5')
    def test_check_md5_ok(self, mock_generate_md5):
        """
        Ensure md5 checksums match, STATUS_OK
        """
        jdata = b'{"/etc/swift/object.ring.gz": ' \
                b'"6b4f3a0ef3731f18291ecd053ce0d9b6", ' \
                b'"/etc/swift/account.ring.gz": ' \
                b'"6b4f3a0ef3731f18291ecd053ce0d9b6", ' \
                b'"/etc/swift/container.ring.gz": ' \
                b'"6b4f3a0ef3731f18291ecd053ce0d9b6"}'
        pmock_jdata = PropertyMock(return_value=jdata)
        mock_generate_md5.return_value = '6b4f3a0ef3731f18291ecd053ce0d9b6'
        with patch('urllib.request.urlopen') as mock_urlopen:
            mock_urlopen.return_value = MagicMock(read=pmock_jdata)
            result = check_md5('.')
            mock_urlopen.assert_called_with('.ringmd5')
            self.assertEqual(result,
                             [(STATUS_OK, 'OK')])

    @patch('urllib.request.urlopen')
    def test_check_replication_unknown_urlerror(self, mock_urlopen):
        """
        Force urllib.error.URLError to test try-catch
        """
        base_url = 'http://localhost:6000/recon/'
        url = '{}replication/{}'
        error = 'connection refused'
        mock_urlopen.side_effect = (urllib
                                    .error
                                    .URLError(Mock(return_value=error)))
        result = check_replication(base_url, 60)
        expected_result = [(STATUS_UNKNOWN,
                            "Can't open url: "
                            "{}".format(url.format(base_url, name)))
                           for name in ('account', 'object', 'container')]
        self.assertEqual(result, expected_result)

    @patch('urllib.request.urlopen')
    def test_check_replication_unknown_valueerror1(self, mock_urlopen):
        """
        Force ValueError on urllib.error to test try-catch
        """
        base_url = '.'
        mock_urlopen.side_effect = ValueError(Mock(return_value=''))
        result = check_replication(base_url, [4, 10, 4, 10])
        self.assertEqual(result,
                         3*[(STATUS_UNKNOWN,
                             "Can't parse status data")])

    @patch('urllib.request.urlopen')
    def test_check_replication_unknown_valueerror2(self, mock_urlopen):
        """
        Force ValueError on json to test try-catch
        """
        base_url = 'http://localhost:6000/recon/'
        jdata = PropertyMock(return_value=b'X')
        mock_urlopen.return_value = MagicMock(read=jdata)
        result = check_replication(base_url, [4, 10, 4, 10])
        self.assertEqual(result,
                         3*[(STATUS_UNKNOWN,
                             "Can't parse status data")])

    @patch('check_swift_storage.repl_last_timestamp')
    def test_check_replication_crit_lag_notworking(self, mock_timestamp):
        """
        Catch NULL replication value, STATUS_CRIT
        """
        base_url = 'http://localhost:6000/recon/'
        jdata = b'{"replication_last": 1493299546.629282, ' \
                b'"replication_stats": {"no_change": 0, "rsync": 0, ' \
                b'"success": 0, "failure": 0, "attempted": 0, "ts_repl": 0, ' \
                b'"remove": 0, "remote_merge": 0, "diff_capped": 0, ' \
                b'"start": 1493299546.621624, "hashmatch": 0, "diff": 0, ' \
                b'"empty": 0}, "replication_time": 0.0076580047607421875}'
        pmock_jdata = PropertyMock(return_value=jdata)
        mock_timestamp.return_value = (None, 0)
        with patch('urllib.request.urlopen') as mock_urlopen:
            mock_urlopen.return_value = MagicMock(read=pmock_jdata)
            result = check_replication(base_url, [4, 10, 4, 10])
            self.assertEqual(result,
                             [(STATUS_CRIT,
                               "'{}' replication lag not working "
                               "(perms issue? check syslog)".format(repl))
                              for repl in ('account', 'object', 'container')])

    @patch('check_swift_storage.repl_last_timestamp')
    def test_check_replication_crit_lag(self, mock_timestamp):
        """
        Replication lag over CRIT threshold, STATUS_CRIT
        """
        base_url = 'http://localhost:6000/recon/'
        jdata = b'{"replication_last": 1493299546.629282, ' \
                b'"replication_stats": {"no_change": 0, "rsync": 0, ' \
                b'"success": 0, "failure": 0, "attempted": 0, "ts_repl": 0, ' \
                b'"remove": 0, "remote_merge": 0, "diff_capped": 0, ' \
                b'"start": 1493299546.621624, "hashmatch": 0, "diff": 0, ' \
                b'"empty": 0}, "replication_time": 0.0076580047607421875}'
        pmock_jdata = PropertyMock(return_value=jdata)
        mock_timestamp.return_value = (MagicMock(days=0, seconds=12), 0)
        with patch('urllib.request.urlopen') as mock_urlopen:
            mock_urlopen.return_value = MagicMock(read=pmock_jdata)
            result = check_replication(base_url, [4, 10, 4, 10])
            self.assertEqual(result,
                             [(STATUS_CRIT,
                               "'{}' replication lag is "
                               "12 seconds".format(repl))
                              for repl in ('account', 'object', 'container')])

    @patch('check_swift_storage.repl_last_timestamp')
    def test_check_replication_crit_failures(self, mock_timestamp):
        """
        Replication failures over CRIT threshold, STATUS_CRIT
        """
        base_url = 'http://localhost:6000/recon/'
        jdata = b'{"replication_last": 1493299546.629282, ' \
                b'"replication_stats": {"no_change": 0, "rsync": 0, ' \
                b'"success": 0, "failure": 0, "attempted": 0, "ts_repl": 0, ' \
                b'"remove": 0, "remote_merge": 0, "diff_capped": 0, ' \
                b'"start": 1493299546.621624, "hashmatch": 0, "diff": 0, ' \
                b'"empty": 0}, "replication_time": 0.0076580047607421875}'
        pmock_jdata = PropertyMock(return_value=jdata)
        mock_timestamp.return_value = (MagicMock(days=0, seconds=0), 12)
        with patch('urllib.request.urlopen') as mock_urlopen:
            mock_urlopen.return_value = MagicMock(read=pmock_jdata)
            result = check_replication(base_url, [4, 10, 4, 10])
            self.assertEqual(result,
                             3*[(STATUS_CRIT, "12 replication failures")])

    @patch('check_swift_storage.repl_last_timestamp')
    def test_check_replication_crit_null_failures(self, mock_timestamp):
        """
        Catch NULL value on failures stats, STATUS_CRIT
        """
        base_url = 'http://localhost:6000/recon/'
        jdata = b'{"replication_last": 1493299546.629282, ' \
                b'"replication_stats": {"no_change": 0, "rsync": 0, ' \
                b'"success": 0, "failure": 0, "attempted": 0, "ts_repl": 0, ' \
                b'"remove": 0, "remote_merge": 0, "diff_capped": 0, ' \
                b'"start": 1493299546.621624, "hashmatch": 0, "diff": 0, ' \
                b'"empty": 0}, "replication_time": 0.0076580047607421875}'
        pmock_jdata = PropertyMock(return_value=jdata)
        mock_timestamp.return_value = (MagicMock(days=0, seconds=0), -1)
        with patch('urllib.request.urlopen') as mock_urlopen:
            mock_urlopen.return_value = MagicMock(read=pmock_jdata)
            result = check_replication(base_url, [4, 10, 4, 10])
            self.assertEqual(result,
                             3*[(STATUS_CRIT,
                                 "replication failures counter is NULL "
                                 "(check syslog)")])

    @patch('check_swift_storage.repl_last_timestamp')
    def test_check_replication_warn_lag(self, mock_timestamp):
        """
        Replication lag over WARN threshold (below CRIT), STATUS_WARN
        """
        base_url = 'http://localhost:6000/recon/'
        jdata = b'{"replication_last": 1493299546.629282, ' \
                b'"replication_stats": {"no_change": 0, "rsync": 0, ' \
                b'"success": 0, "failure": 0, "attempted": 0, "ts_repl": 0, ' \
                b'"remove": 0, "remote_merge": 0, "diff_capped": 0, ' \
                b'"start": 1493299546.621624, "hashmatch": 0, "diff": 0, ' \
                b'"empty": 0}, "replication_time": 0.0076580047607421875}'
        pmock_jdata = PropertyMock(return_value=jdata)
        mock_timestamp.return_value = (MagicMock(days=0, seconds=5), 0)
        with patch('urllib.request.urlopen') as mock_urlopen:
            mock_urlopen.return_value = MagicMock(read=pmock_jdata)
            result = check_replication(base_url, [4, 10, 4, 10])
            self.assertEqual(result,
                             [(STATUS_WARN,
                               "'{}' replication lag is "
                               "5 seconds".format(repl))
                              for repl in ('account', 'object', 'container')])

    @patch('check_swift_storage.repl_last_timestamp')
    def test_check_replication_crit_day_plus_lag(self, mock_timestamp):
        """
        Replication lag CRITS with day wrap, STATUS_CRIT
        """
        base_url = 'http://localhost:6000/recon/'
        jdata = b'{"replication_last": 1493299546.629282, ' \
                b'"replication_stats": {"no_change": 0, "rsync": 0, ' \
                b'"success": 0, "failure": 0, "attempted": 0, "ts_repl": 0, ' \
                b'"remove": 0, "remote_merge": 0, "diff_capped": 0, ' \
                b'"start": 1493299546.621624, "hashmatch": 0, "diff": 0, ' \
                b'"empty": 0}, "replication_time": 0.0076580047607421875}'
        pmock_jdata = PropertyMock(return_value=jdata)
        mock_timestamp.return_value = (MagicMock(days=2, seconds=5), 0)
        with patch('urllib.request.urlopen') as mock_urlopen:
            mock_urlopen.return_value = MagicMock(read=pmock_jdata)
            result = check_replication(base_url, [4, 10, 4, 10])
            self.assertEqual(result,
                             [(STATUS_CRIT,
                               "'{}' replication lag is "
                               "172805 seconds".format(repl))
                              for repl in ('account', 'object', 'container')])

    @patch('check_swift_storage.repl_last_timestamp')
    def test_check_replication_warn_failures(self, mock_timestamp):
        """
        Replication failures over WARN threshold (below CRIT), STATUS_WARN
        """
        base_url = 'http://localhost:6000/recon/'
        jdata = b'{"replication_last": 1493299546.629282, ' \
                b'"replication_stats": {"no_change": 0, "rsync": 0, ' \
                b'"success": 0, "failure": 0, "attempted": 0, "ts_repl": 0, ' \
                b'"remove": 0, "remote_merge": 0, "diff_capped": 0, ' \
                b'"start": 1493299546.621624, "hashmatch": 0, "diff": 0, ' \
                b'"empty": 0}, "replication_time": 0.0076580047607421875}'
        pmock_jdata = PropertyMock(return_value=jdata)
        mock_timestamp.return_value = (MagicMock(days=0, seconds=0), 5)
        # with patch('urllib2.urlopen') as mock_urlopen:
        with patch('urllib.request.urlopen') as mock_urlopen:
            mock_urlopen.return_value = MagicMock(read=pmock_jdata)
            result = check_replication(base_url, [4, 10, 4, 10])
            self.assertEqual(result,
                             3*[(STATUS_WARN, "5 replication failures")])

    @patch('check_swift_storage.repl_last_timestamp')
    def test_check_replication_ok(self, mock_timestamp):
        """
        Replication lag and number of failures are below WARN threshold,
        STATUS_OK
        """
        base_url = 'http://localhost:6000/recon/'
        jdata = b'{"replication_last": 1493299546.629282, ' \
                b'"replication_stats": {"no_change": 0, "rsync": 0, ' \
                b'"success": 0, "failure": 0, "attempted": 0, "ts_repl": 0, ' \
                b'"remove": 0, "remote_merge": 0, "diff_capped": 0, ' \
                b'"start": 1493299546.621624, "hashmatch": 0, "diff": 0, ' \
                b'"empty": 0}, "replication_time": 0.0076580047607421875}'
        pmock_jdata = PropertyMock(return_value=jdata)
        mock_timestamp.return_value = (MagicMock(days=0, seconds=0), 0)
        with patch('urllib.request.urlopen') as mock_urlopen:
            mock_urlopen.return_value = MagicMock(read=pmock_jdata)
            result = check_replication(base_url, [4, 10, 4, 10])
            self.assertEqual(result, [(STATUS_OK, 'OK')])

    @patch('check_swift_storage.datetime')
    def test_repl_last_timestamp(self, mock_datetime):
        """
        Calculates delta between NOW and last replication date
        Also gathers the number of failures
        """
        # 1493299546.629282
        mock_datetime.datetime.now.return_value = (
            datetime.datetime(2017, 4, 27, 13, 25, 46, 629282)
        )
        mock_datetime.datetime.fromtimestamp.side_effect = (
            datetime.datetime.utcfromtimestamp
        )

        jdata = {u'replication_last': 1493299546.629282, u'replication_stats':
                 {u'no_change': 0, u'rsync': 0, u'success': 0, u'start':
                  1493299546.621624, u'attempted': 0, u'ts_repl': 0, u'remove':
                  0, u'remote_merge': 0, u'diff_capped': 0, u'failure': 0,
                  u'hashmatch': 0, u'diff': 0, u'empty': 0},
                 u'replication_time': 0.0076580047607421875}
        result = repl_last_timestamp(jdata)
        self.assertEqual(result,
                         (datetime.timedelta(0), 0))
