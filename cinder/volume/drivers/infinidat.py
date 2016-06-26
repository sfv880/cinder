# Copyright 2016 Infinidat Ltd.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
"""
INFINIDAT InfiniBox Volume Driver
"""

import mock
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import units
from oslo_utils import uuidutils
import requests
import six

from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder.volume import driver
from cinder.volume.drivers.san import san



LOG = logging.getLogger(__name__)

VENDOR_NAME = 'INFINIDAT'

infinidat_opts = [
    cfg.StrOpt('infinidat_pool_name',
               help='Name of the pool from which volumes are allocated'),
]

CONF = cfg.CONF
CONF.register_opts(infinidat_opts)


@interface.volumedriver
class InfiniboxVolumeDriver(san.SanDriver,
                            driver.ExtendVD,
                            driver.SnapshotVD,
                            driver.TransferVD):
    VERSION = '1.0'

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "INFINIDAT_Cinder_CI"

    def __init__(self, *args, **kwargs):
        super(InfiniboxVolumeDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(infinidat_opts)

    def do_setup(self, context):
        """Driver initialization"""
        self._session = requests.Session()
        self._session.auth = (self.configuration.san_login,
                              self.configuration.san_password)
        management_address = self.configuration.san_ip
        self._base_url = 'http://{0}/api/rest/'.format(management_address)
        backend_name = self.configuration.safe_get('volume_backend_name')
        self._backend_name = backend_name or self.__class__.__name__
        self._volume_stats = None
        LOG.debug('setup complete. base url: %s', self._base_url)

    def check_for_setup_error(self):
        """Validate setup"""
        pass

    def _request(self, action, uri, data=None):
        LOG.debug('--> %(action)s %(uri)s %(data)r',
                  {'action': action, 'uri': uri, 'data': data})
        response = self._session.request(action,
                                         self._base_url + uri,
                                         json=data)
        LOG.debug('<-- %(status_code)s %(response_json)r',
                  {'status_code': response.status_code,
                   'response_json': response.json()})
        try:
            response.raise_for_status()
        except requests.HTTPError as ex:
            # text_type(ex) includes http code and url
            msg = _('InfiniBox storage array returned ') + six.text_type(ex)
            msg += _('\nData: ') + repr(data)
            msg += _('\nResponse: ') + repr(response.json())
            LOG.exception(msg)
            if response.status_code == 404:
                raise exception.NotFound()
            else:
                raise exception.VolumeBackendAPIException(data=msg)
        return response.json()['result']

    def _get(self, uri):
        return self._request('GET', uri)

    def _post(self, uri, data):
        return self._request('POST', uri, data)

    def _delete(self, uri):
        return self._request('DELETE', uri)

    def _put(self, uri, data):
        return self._request('PUT', uri, data)

    def _cleanup_wwpn(self, wwpn):
        return wwpn.replace(':', '')

    def _make_volume_name(self, cinder_volume):
        return 'openstack-vol-{0}'.format(cinder_volume.id)

    def _make_snapshot_name(self, cinder_snapshot):
        return 'openstack-snap-{0}'.format(cinder_snapshot.id)

    def _make_host_name(self, wwpn):
        wwn_for_name = self._cleanup_wwpn(wwpn)
        return 'openstack-host-{0}'.format(wwn_for_name)

    def _get_infinidat_volume_by_name(self, name):
        volumes = self._get('volumes?name={0}'.format(name))
        if len(volumes) != 1:
            msg = _('Volume "%s" not found') % name
            LOG.error(msg)
            raise exception.InvalidVolume(reason=msg)
        return volumes[0]

    def _get_infinidat_snapshot_by_name(self, name):
        snapshots = self._get('volumes?name={0}'.format(name))
        if len(snapshots) != 1:
            msg = _('Snapshot "%s" not found') % name
            LOG.error(msg)
            raise exception.InvalidSnapshot(reason=msg)
        return snapshots[0]

    def _get_infinidat_volume_id(self, cinder_volume):
        volume_name = self._make_volume_name(cinder_volume)
        return self._get_infinidat_volume_by_name(volume_name)['id']

    def _get_infinidat_snapshot_id(self, cinder_snapshot):
        snap_name = self._make_snapshot_name(cinder_snapshot)
        return self._get_infinidat_snapshot_by_name(snap_name)['id']

    def _get_infinidat_pool(self):
        pool_name = self.configuration.infinidat_pool_name
        pools = self._get('pools?name={0}'.format(pool_name))
        if len(pools) != 1:
            msg = _('Pool "%s" not found') % pool_name
            LOG.error(msg)
            raise exception.VolumeDriverException(msg)
        return pools[0]

    def _get_or_create_host(self, wwpn):
        host_name = self._make_host_name(wwpn)
        infinidat_hosts = self._get('hosts?name={0}'.format(host_name))
        if len(infinidat_hosts) == 1:
            infinidat_host = infinidat_hosts[0]
        else:
            # create host
            infinidat_host = self._post('hosts', dict(name=host_name))
            # add port to host
            self._post('hosts/{0}/ports'.format(infinidat_host['id']),
                       dict(type='FC', address=self._cleanup_wwpn(wwpn)))
        return infinidat_host

    def _get_or_create_mapping(self, host_id, volume_id):
        existing_mapping = self._get("hosts/{0}/luns".format(host_id))
        for mapping in existing_mapping:
            if mapping['volume_id'] == volume_id:
                return mapping
        # volume not mapped. map it
        uri = 'hosts/{0}/luns?approved=true'.format(host_id)
        return self._post(uri, dict(volume_id=volume_id))

    def _get_online_fc_ports(self):
        nodes = self._get('components/nodes?fields=fc_ports')
        for node in nodes:
            for port in node['fc_ports']:
                if (port['link_state'].lower() == 'up'
                   and port['state'] == 'OK'):
                    yield self._cleanup_wwpn(port['wwpn'])

    def initialize_connection(self, volume, connector):
        """Map an InfiniBox volume to the host"""
        volume_name = self._make_volume_name(volume)
        infinidat_volume = self._get_infinidat_volume_by_name(volume_name)
        for wwpn in connector['wwpns']:
            infinidat_host = self._get_or_create_host(wwpn)
            mapping = self._get_or_create_mapping(infinidat_host['id'],
                                                  infinidat_volume['id'])
            lun = mapping['lun']

        access_mode = 'ro' if infinidat_volume['write_protected'] else 'rw'
        target_wwn = list(self._get_online_fc_ports())
        return dict(driver_volume_type='fibre_channel',
                    data=dict(target_discovered=False,
                              target_wwn=target_wwn,
                              target_lun=lun,
                              access_mode=access_mode))

    def terminate_connection(self, volume, connector, **kwargs):
        """Unmap an InfiniBox volume from the host"""
        volume_id = self._get_infinidat_volume_id(volume)
        for wwpn in connector['wwpns']:
            host_name = self._make_host_name(wwpn)
            infinidat_hosts = self._get('hosts?name={0}'.format(host_name))
            if len(infinidat_hosts) != 1:
                # not found. ignore.
                continue
            host_id = infinidat_hosts[0]['id']
            # unmap
            uri = ('hosts/{0}/luns/volume_id/{1}'.format(host_id, volume_id) +
                   '?approved=true')
            self._delete(uri)

    def get_volume_stats(self, refresh=False):
        if self._volume_stats is None or refresh:
            pool = self._get_infinidat_pool()
            free_capacity_gb = float(pool['free_physical_space']) / units.Gi
            total_capacity_gb = float(pool['physical_capacity']) / units.Gi
            self._volume_stats = dict(volume_backend_name=self._backend_name,
                                      vendor_name=VENDOR_NAME,
                                      driver_version=self.VERSION,
                                      storage_protocol='FC',
                                      consistencygroup_support='False',
                                      total_capacity_gb=total_capacity_gb,
                                      free_capacity_gb=free_capacity_gb)
        return self._volume_stats

    def create_volume(self, volume):
        """Create a new volume on the backend."""
        # get pool id from name
        pool = self._get_infinidat_pool()
        # create volume
        volume_name = self._make_volume_name(volume)
        provtype = "THIN" if self.configuration.san_thin_provision else "THICK"
        data = dict(pool_id=pool['id'],
                    provtype=provtype,
                    name=volume_name,
                    size=volume.size * units.Gi)
        self._post('volumes', data)

    def _delete_parent_snapshot_if_needed(self, volume):
        if volume['parent_id'] == 0:
            # no parent
            return
        try:
            uri = 'volumes/{0}'.format(volume['parent_id'])
            parent = self._get(uri)
            if parent['name'].endswith('-internal'):
                self._delete(uri + '?approved=true')
        except (exception.InvalidVolume, exception.NotFound):
            return      # parent not found

    def delete_volume(self, volume):
        """Delete a volume from the backend."""
        try:
            volume_name = self._make_volume_name(volume)
            volume = self._get_infinidat_volume_by_name(volume_name)
            if volume['has_children']:
                # can't delete a volume that has a live snapshot/clone
                raise exception.VolumeIsBusy(volume_name=volume_name)
            self._delete('volumes/{0}?approved=true'.format(volume['id']))
            self._delete_parent_snapshot_if_needed(volume)
        except (exception.InvalidVolume, exception.NotFound):
            return      # volume not found

    def extend_volume(self, volume, new_size):
        """Extend the size of a volume."""
        volume_id = self._get_infinidat_volume_id(volume)
        self._put('volumes/{0}?approved=true'.format(volume_id),
                  dict(size=new_size * units.Gi))

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        volume_id = self._get_infinidat_volume_id(snapshot.volume)
        name = self._make_snapshot_name(snapshot)
        self._post('volumes', dict(parent_id=volume_id, name=name))

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        snapshot_id = self._get_infinidat_snapshot_id(snapshot)
        volume_name = self._make_volume_name(volume)
        # create clone
        result = self._post('volumes', dict(parent_id=snapshot_id,
                                            name=volume_name))
        # disable write protection and update size
        uri = 'volumes/{0}?approved=true'.format(result['id'])
        self._put(uri, dict(write_protected=False))
        self._put(uri, dict(size=volume.size * units.Gi))

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        try:
            snapshot_name = self._make_snapshot_name(snapshot)
            snapshot = self._get_infinidat_snapshot_by_name(snapshot_name)
            if snapshot['has_children']:
                # can't delete a snapshot that has a live clone
                raise exception.SnapshotIsBusy(snapshot_name=snapshot_name)
            self._delete('volumes/{0}?approved=true'.format(snapshot['id']))
        except (exception.InvalidSnapshot, exception.NotFound):
            return      # snapshot not found

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        # on InfiniBox 2.2, to create a clone, we must first create a snapshot
        snapshot_id = uuidutils.generate_uuid() + '-internal'
        snapshot = mock.MagicMock(id=snapshot_id, volume=src_vref)
        self.create_snapshot(snapshot)
        self.create_volume_from_snapshot(volume, snapshot)

    def create_export(self, context, volume, connector=None):
        """Exports the volume."""
        # nothing to do here. SAN volumes are exported automatically
        pass

    def remove_export(self, context, volume):
        """Removes an export for a logical volume."""
        pass
