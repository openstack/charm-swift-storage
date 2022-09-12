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

import base64
import copy
import json
import os
import shutil
import sys
import socket
import subprocess
import tempfile
import yaml

from subprocess import CalledProcessError

_path = os.path.dirname(os.path.realpath(__file__))
_root = os.path.abspath(os.path.join(_path, '..'))


def _add_path(path):
    if path not in sys.path:
        sys.path.insert(1, path)


_add_path(_root)


from lib.swift_storage_utils import (
    restart_map,
    SWIFT_SVCS,
    determine_packages,
    do_openstack_upgrade,
    ensure_swift_directories,
    fetch_swift_rings,
    register_configs,
    save_script_rc,
    setup_storage,
    assert_charm_supports_ipv6,
    setup_rsync,
    remember_devices,
    REQUIRED_INTERFACES,
    assess_status,
    ensure_devs_tracked,
    VERSION_PACKAGE,
    setup_ufw,
    revoke_access,
    enable_replication,
)

from lib.misc_utils import pause_aware_restart_on_change

from charmhelpers.core.hookenv import (
    Hooks, UnregisteredHookError,
    config,
    log,
    network_get_primary_address,
    relation_get,
    relation_ids,
    relation_set,
    relations_of_type,
    status_set,
    ingress_address,
    DEBUG,
    WARNING,
    ERROR,
)

from charmhelpers.fetch import (
    apt_install,
    apt_update,
    filter_installed_packages
)
from charmhelpers.core.host import (
    add_to_updatedb_prunepath,
    rsync,
    write_file,
    umount,
    service_start,
    service_stop,
)

from charmhelpers.core.sysctl import create as create_sysctl
from charmhelpers.contrib.sysctl.watermark_scale_factor import (
    calculate_watermark_scale_factor,
)

from charmhelpers.payload.execd import execd_preinstall

from charmhelpers.contrib.openstack.utils import (
    configure_installation_source,
    openstack_upgrade_available,
    set_os_workload_status,
    os_application_version_set,
    clear_unit_paused,
    clear_unit_upgrading,
    is_unit_paused_set,
    set_unit_paused,
    set_unit_upgrading,
    get_os_codename_install_source,
)
from charmhelpers.contrib.network.ip import (
    get_relation_ip,
)
from charmhelpers.contrib.network import ufw
from charmhelpers.contrib.charmsupport import nrpe
from charmhelpers.contrib.hardening.harden import harden
from charmhelpers.core.unitdata import kv

from distutils.dir_util import mkpath

import charmhelpers.contrib.openstack.vaultlocker as vaultlocker

hooks = Hooks()
CONFIGS = register_configs()
NAGIOS_PLUGINS = '/usr/local/lib/nagios/plugins'
SUDOERS_D = '/etc/sudoers.d'
STORAGE_MOUNT_PATH = '/srv/node'
UFW_DIR = '/etc/ufw'


def add_ufw_gre_rule(ufw_rules_path):
    """Add allow gre rule to UFW

    Make a copy of existing UFW before rules, insert our new rule and replace
    existing rules with updated version.
    """
    rule = '-A ufw-before-input -p 47 -j ACCEPT'
    rule_exists = False
    with tempfile.NamedTemporaryFile() as tmpfile:
        # Close pre-opened file so that we can replace it with a copy of our
        # config file.
        tmpfile.file.close()
        dst = tmpfile.name
        # Copy over ufw rules file
        shutil.copyfile(ufw_rules_path, dst)
        with open(dst, 'r') as fd:
            lines = fd.readlines()

        # Check whether the line we are adding already exists
        for line in lines:
            if rule in line:
                rule_exists = True
                break

        added = False
        if not rule_exists:
            # Insert our rule as the first rule.
            with open(dst, 'w') as fd:
                for line in lines:
                    if not added and line.startswith('-A'):
                        fd.write('# Allow GRE Traffic (added by swift-storage '
                                 'charm)\n')
                        fd.write('{}\n'.format(rule))
                        fd.write(line)
                        added = True
                    else:
                        fd.write(line)

            # Replace existing config with updated one.
            shutil.copyfile(dst, ufw_rules_path)


def initialize_ufw():
    """Initialize the UFW firewall

    Ensure critical ports have explicit allows

    :return: None
    """

    if not config('enable-firewall'):
        log("Firewall has been administratively disabled", "DEBUG")
        return

    # this charm will monitor exclusively the ports used, using 'allow' as
    # default policy enables sharing the machine with other services
    ufw.default_policy('allow', 'incoming')
    ufw.default_policy('allow', 'outgoing')
    ufw.default_policy('allow', 'routed')
    # Rsync manages its own ACLs
    ufw.service('rsync', 'open')
    # Guarantee SSH access
    ufw.service('ssh', 'open')
    # Enable
    ufw.enable(soft_fail=config('allow-ufw-ip6-softfail'))

    # Allow GRE traffic
    add_ufw_gre_rule(os.path.join(UFW_DIR, 'before.rules'))
    ufw.reload()


@hooks.hook('install.real')
@harden()
def install():
    status_set('maintenance', 'Executing pre-install')
    execd_preinstall()
    src = config('openstack-origin')
    configure_installation_source(src)
    status_set('maintenance', 'Installing apt packages')
    apt_update()
    rel = get_os_codename_install_source(src)
    pkgs = determine_packages(rel)
    apt_install(pkgs, fatal=True)
    initialize_ufw()
    ensure_swift_directories()
    install_vaultlocker()


@hooks.hook('config-changed')
@pause_aware_restart_on_change(restart_map())
@harden()
def config_changed():
    if config('enable-firewall'):
        initialize_ufw()
    else:
        ufw.disable()

    if config('ephemeral-unmount'):
        umount(config('ephemeral-unmount'), persist=True)

    if config('prefer-ipv6'):
        status_set('maintenance', 'Configuring ipv6')
        assert_charm_supports_ipv6()

    ensure_swift_directories()
    setup_rsync()

    if not config('action-managed-upgrade') and \
            openstack_upgrade_available('swift'):
        status_set('maintenance', 'Running openstack upgrade')
        do_openstack_upgrade(configs=CONFIGS)

    install_vaultlocker()

    configure_storage()

    CONFIGS.write_all()

    save_script_rc()
    if relations_of_type('nrpe-external-master'):
        update_nrpe_config()

    if config('sysctl'):
        sysctl_dict_parsed = {}
        sysctl_settings = config('sysctl')
        try:
            sysctl_dict_parsed = yaml.safe_load(sysctl_settings)
        except yaml.YAMLError:
            log("Error parsing YAML sysctl_dict: {}".format(sysctl_settings),
                level=ERROR)
        if (config('tune-watermark-scale-factor') is True and
                "vm.watermark_scale_factor" not in sysctl_dict_parsed):
            try:
                wmark = calculate_watermark_scale_factor()
                sysctl_dict_parsed["vm.watermark_scale_factor"] = wmark
            except Exception:
                pass

        if sysctl_dict_parsed:
            create_sysctl(sysctl_dict_parsed,
                          '/etc/sysctl.d/50-swift-storage-charm.conf')

    add_to_updatedb_prunepath(STORAGE_MOUNT_PATH)


def install_vaultlocker():
    """Determine whether vaultlocker is required and install"""
    if config('encrypt'):
        pkgs = ['vaultlocker']
        installed = len(filter_installed_packages(pkgs)) == 0
        if not installed:
            apt_install(pkgs, fatal=True)


@hooks.hook('upgrade-charm.real')
@harden()
def upgrade_charm():
    initialize_ufw()
    rel = get_os_codename_install_source(config('openstack-origin'))
    pkgs = determine_packages(rel)
    apt_install(pkgs, fatal=True)
    update_nrpe_config()
    ensure_devs_tracked()


@hooks.hook()
def swift_storage_relation_joined(rid=None):
    if config('encrypt') and not vaultlocker.vault_relation_complete():
        log('Encryption configured and vault not ready, deferring',
            level=DEBUG)
        return
    rel_settings = {
        'zone': config('zone'),
        'object_port': config('object-server-port'),
        'container_port': config('container-server-port'),
        'account_port': config('account-server-port'),
    }
    if enable_replication():
        replication_ip = network_get_primary_address('replication')
        cluster_ip = network_get_primary_address('cluster')
        rel_settings.update({
            'ip_rep': replication_ip,
            'ip_cls': cluster_ip,
            'region': config('storage-region'),
            'object_port_rep': config('object-server-port-rep'),
            'container_port_rep': config('container-server-port-rep'),
            'account_port_rep': config('account-server-port-rep')})
    db = kv()
    devs = db.get('prepared-devices', [])
    devs = [os.path.basename(d) for d in devs]
    rel_settings['device'] = ':'.join(devs)
    # Keep a reference of devices we are adding to the ring
    remember_devices(devs)

    rel_settings['private-address'] = get_relation_ip('swift-storage')

    relation_set(relation_id=rid, relation_settings=rel_settings)


@hooks.hook('swift-storage-relation-changed')
@pause_aware_restart_on_change(restart_map())
def swift_storage_relation_changed():
    setup_ufw()
    rings_url = relation_get('rings_url')
    swift_hash = relation_get('swift_hash')
    if '' in [rings_url, swift_hash] or None in [rings_url, swift_hash]:
        log('swift_storage_relation_changed: Peer not ready?')
        sys.exit(0)

    CONFIGS.write('/etc/rsync-juju.d/050-swift-storage.conf')
    CONFIGS.write('/etc/swift/swift.conf')

    # NOTE(hopem): retries are handled in the function but it is possible that
    #              we are attempting to get rings from a proxy that is no
    #              longer publiscising them so lets catch the error, log a
    #              message and hope that the good rings_url us waiting to be
    #              consumed.
    try:
        fetch_swift_rings(rings_url)
    except CalledProcessError:
        log("Failed to sync rings from {} - no longer available from that "
            "unit?".format(rings_url), level=WARNING)


@hooks.hook('swift-storage-relation-departed')
def swift_storage_relation_departed():
    ports = [config('object-server-port'),
             config('container-server-port'),
             config('account-server-port')]
    removed_client = ingress_address()
    if removed_client:
        for port in ports:
            revoke_access(removed_client, port)


@hooks.hook('secrets-storage-relation-joined')
def secrets_storage_joined(relation_id=None):
    relation_set(relation_id=relation_id,
                 secret_backend='charm-vaultlocker',
                 isolated=True,
                 access_address=get_relation_ip('secrets-storage'),
                 hostname=socket.gethostname())


@hooks.hook('secrets-storage-relation-changed')
def secrets_storage_changed():
    vault_ca = relation_get('vault_ca')
    if vault_ca:
        vault_ca = base64.decodebytes(json.loads(vault_ca).encode())
        write_file('/usr/local/share/ca-certificates/vault-ca.crt',
                   vault_ca, perms=0o644)
        subprocess.check_call(['update-ca-certificates', '--fresh'])
    configure_storage()


@hooks.hook('storage.real')
def configure_storage():
    setup_storage(config('encrypt'))

    for rid in relation_ids('swift-storage'):
        swift_storage_relation_joined(rid=rid)


@hooks.hook('nrpe-external-master-relation-joined')
@hooks.hook('nrpe-external-master-relation-changed')
def update_nrpe_config():
    # python-dbus is used by check_upstart_job
    apt_install('python-dbus')
    log('Refreshing nrpe checks')
    if not os.path.exists(NAGIOS_PLUGINS):
        mkpath(NAGIOS_PLUGINS)
    rsync(os.path.join(os.getenv('CHARM_DIR'), 'files', 'nrpe-external-master',
                       'check_swift_storage.py'),
          os.path.join(NAGIOS_PLUGINS, 'check_swift_storage.py'))
    rsync(os.path.join(os.getenv('CHARM_DIR'), 'files', 'nrpe-external-master',
                       'check_timed_logs.pl'),
          os.path.join(NAGIOS_PLUGINS, 'check_timed_logs.pl'))
    rsync(os.path.join(os.getenv('CHARM_DIR'), 'files', 'nrpe-external-master',
                       'check_swift_replicator_logs.sh'),
          os.path.join(NAGIOS_PLUGINS, 'check_swift_replicator_logs.sh'))
    rsync(os.path.join(os.getenv('CHARM_DIR'), 'files', 'nrpe-external-master',
                       'check_swift_service'),
          os.path.join(NAGIOS_PLUGINS, 'check_swift_service'))
    rsync(os.path.join(os.getenv('CHARM_DIR'), 'files', 'sudo',
                       'swift-storage'),
          os.path.join(SUDOERS_D, 'swift-storage'))

    # Find out if nrpe set nagios_hostname
    hostname = nrpe.get_nagios_hostname()
    current_unit = nrpe.get_nagios_unit_name()
    nrpe_setup = nrpe.NRPE(hostname=hostname)

    # check the rings and replication
    nrpe_setup.add_check(
        shortname='swift_storage',
        description='Check swift storage ring hashes and replication'
                    ' {%s}' % current_unit,
        check_cmd='check_swift_storage.py {}'.format(
            config('nagios-check-params'))
    )

    object_port = config('object-server-port')
    container_port = config('container-server-port')
    account_port = config('account-server-port')

    nrpe_setup.add_check(
        shortname="swift-object-server-api",
        description="Check Swift Object Server API availability",
        check_cmd="/usr/lib/nagios/plugins/check_http \
                  -I localhost -u /recon/version -p {} \
                  -e \"OK\"".format(object_port))

    nrpe_setup.add_check(
        shortname="swift-container-server-api",
        description="Check Swift Container Server API availability",
        check_cmd="/usr/lib/nagios/plugins/check_http \
                  -I localhost -u /recon/version -p {} \
                  -e \"OK\"".format(container_port))

    nrpe_setup.add_check(
        shortname="swift-account-server-api",
        description="Check Swift Account Server API availability",
        check_cmd="/usr/lib/nagios/plugins/check_http \
                  -I localhost -u /recon/version -p {} \
                  -e \"OK\"".format(account_port))

    if config('nagios-replication-check-params'):
        nrpe_setup.add_check(
            shortname='swift_replicator_health',
            description='Check swift object replicator log reporting',
            check_cmd='check_swift_replicator_logs.sh {}'.format(
                config('nagios-replication-check-params'))
        )
    else:
        nrpe_setup.remove_check(shortname='swift_replicator_health')

    nrpe.add_init_service_checks(nrpe_setup, SWIFT_SVCS, current_unit)
    nrpe_setup.write()


@hooks.hook('update-status')
@harden()
def update_status():
    log('Updating status.')


@hooks.hook('pre-series-upgrade')
def pre_series_upgrade():
    log("Running prepare series upgrade hook", "INFO")
    if not is_unit_paused_set():
        for service in SWIFT_SVCS:
            stopped = service_stop(service)
            if not stopped:
                raise Exception("{} didn't stop cleanly.".format(service))
        set_unit_paused()
    set_unit_upgrading()


@hooks.hook('post-series-upgrade')
def post_series_upgrade():
    log("Running complete series upgrade hook", "INFO")
    clear_unit_paused()
    clear_unit_upgrading()
    if not is_unit_paused_set():
        for service in SWIFT_SVCS:
            started = service_start(service)
            if not started:
                raise Exception("{} didn't start cleanly.".format(service))


def main():
    try:
        hooks.execute(sys.argv)
    except UnregisteredHookError as e:
        log('Unknown hook {} - skipping.'.format(e))
    required_interfaces = copy.deepcopy(REQUIRED_INTERFACES)

    if config('encrypt') and \
            len(filter_installed_packages('vaultlocker')) == 0:
        required_interfaces['vault'] = ['secrets-storage']

    set_os_workload_status(CONFIGS, required_interfaces,
                           charm_func=assess_status)
    os_application_version_set(VERSION_PACKAGE)


if __name__ == '__main__':
    main()
