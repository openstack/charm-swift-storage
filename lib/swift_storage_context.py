import re

from charmhelpers.core.hookenv import (
    config,
    log,
    related_units,
    relation_get,
    relation_ids,
    unit_private_ip,
)

from charmhelpers.contrib.openstack.context import (
    OSContextGenerator,
)

from charmhelpers.contrib.network.ip import (
    get_ipv6_addr,
)

from charmhelpers.core.host import (
    lsb_release,
    CompareHostReleases,
)


class SwiftStorageContext(OSContextGenerator):
    interfaces = ['swift-storage']

    def __call__(self):
        rids = relation_ids('swift-storage')
        if not rids:
            return {}

        swift_hash = None
        for rid in rids:
            for unit in related_units(rid):
                if not swift_hash:
                    swift_hash = relation_get('swift_hash', rid=rid,
                                              unit=unit)
        if not swift_hash:
            log('No swift_hash passed via swift-storage relation. '
                'Peer not ready?')
            return {}
        return {'swift_hash': swift_hash}


class RsyncContext(OSContextGenerator):
    interfaces = []

    def enable_rsyncd(self):
        with open('/etc/default/rsync') as _in:
            default = _in.read()
        _m = re.compile('^RSYNC_ENABLE=(.*)$', re.MULTILINE)
        if not re.search(_m, default):
            with open('/etc/default/rsync', 'a+') as out:
                out.write('RSYNC_ENABLE=true\n')
        else:
            with open('/etc/default/rsync', 'w') as out:
                out.write(_m.sub('RSYNC_ENABLE=true', default))

    def __call__(self):
        ctxt = {}
        if config('prefer-ipv6'):
            ctxt['local_ip'] = '%s' % get_ipv6_addr()[0]
        else:
            ctxt['local_ip'] = unit_private_ip()

        timestamps = []
        for rid in relation_ids('swift-storage'):
            for unit in related_units(rid):
                settings = relation_get(unit=unit, rid=rid)
                ts = settings.get('timestamp')
                allowed_hosts = settings.get('rsync_allowed_hosts')
                if allowed_hosts and ts:
                    if not timestamps or ts > max(timestamps):
                        ctxt['allowed_hosts'] = allowed_hosts

                    timestamps.append(ts)

        self.enable_rsyncd()
        return ctxt


class SwiftStorageServerContext(OSContextGenerator):
    interfaces = []

    def __call__(self):
        ctxt = {
            'local_ip': unit_private_ip(),
            'account_server_port': config('account-server-port'),
            'account_server_port_rep': config('account-server-port-rep'),
            'container_server_port': config('container-server-port'),
            'container_server_port_rep': config('container-server-port-rep'),
            'object_server_port': config('object-server-port'),
            'object_server_port_rep': config('object-server-port-rep'),
            'object_server_threads_per_disk': config(
                'object-server-threads-per-disk'),
            'account_max_connections': config('account-max-connections'),
            'container_max_connections': config('container-max-connections'),
            'object_max_connections': config('object-max-connections'),
            'object_replicator_concurrency': config(
                'object-replicator-concurrency'),
            'object_rsync_timeout': config('object-rsync-timeout'),
            'object_handoffs_first': config('object-handoffs-first'),
            'fallocate_reserve': config('file-allocation-reserve'),
            'statsd_host': config('statsd-host'),
            'statsd_port': config('statsd-port'),
            'statsd_sample_rate': config('statsd-sample-rate'),
        }

        # Per the behavior listed on LB#1575277, object_lockup_timeout should
        # be smaller than object_rsync_timeout. But we have hit issues any time
        # this value is smaller or equal to '2 * object_rsync_timeout', so we
        # set it to a value a bit bigger than that.
        ctxt['object_lockup_timeout'] = max(
            config('object-lockup-timeout'),
            2*ctxt['object_rsync_timeout'] + 10
        )

        if config('node-timeout'):
            node_timeout = config('node-timeout')
            ctxt['node_timeout'] = node_timeout
            # docs say this must always be higher
            ctxt['http_timeout'] = max(60, node_timeout + 20)

        ubuntu_release = lsb_release()['DISTRIB_CODENAME'].lower()
        if CompareHostReleases(ubuntu_release) > "trusty":
            ctxt['standalone_replicator'] = True
        else:
            ctxt['standalone_replicator'] = False
        return ctxt
