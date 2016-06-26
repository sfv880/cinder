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
"""Unit tests for INFINIDAT InfiniBox volume driver."""

import copy
import json

import mock
import requests
import six

from cinder import exception
from cinder import test
from cinder.volume import configuration
from cinder.volume.drivers.infinidat import InfiniboxVolumeDriver


BASE_URL = 'http://mockbox/api/rest/'
GET_VOLUME_URL = BASE_URL + 'volumes?name=openstack-vol-1'
GET_SNAP_URL = BASE_URL + 'volumes?name=openstack-snap-2'
VOLUMES_URL = BASE_URL + 'volumes'
VOLUME_URL = BASE_URL + 'volumes/1'
SNAPSHOT_URL = BASE_URL + 'volumes/2'
GET_HOST_URL = BASE_URL + 'hosts?name=openstack-host-0011223344556677'
GET_HOST2_URL = BASE_URL + 'hosts?name=openstack-host-1111223344556677'
HOSTS_URL = BASE_URL + 'hosts'
GET_POOL_URL = BASE_URL + 'pools?name=mockpool'
MAP_URL = BASE_URL + 'hosts/10/luns'
MAP2_URL = BASE_URL + 'hosts/11/luns'
ADD_PORT_URL = BASE_URL + 'hosts/10/ports'
UNMAP_URL = BASE_URL + 'hosts/10/luns/volume_id/1'
FC_PORT_URL = BASE_URL + 'components/nodes?fields=fc_ports'
APPROVAL = '?approved=true'

VOLUME_RESULT = dict(id=1,
                     write_protected=False,
                     has_children=False,
                     parent_id=0)
VOLUME_RESULT_WP = dict(id=1,
                        write_protected=True,
                        has_children=False,
                        parent_id=0)
SNAPSHOT_RESULT = dict(id=2,
                       write_protected=True,
                       has_children=False,
                       parent_id=0)
HOST_RESULT = dict(id=10)
HOST2_RESULT = dict(id=11)
POOL_RESULT = dict(id=100,
                   free_physical_space=1024 ** 3,
                   physical_capacity=1024 ** 3)

GOOD_PATH_RESPONSES = dict(GET={GET_VOLUME_URL: [VOLUME_RESULT],
                                GET_HOST_URL: [HOST_RESULT],
                                GET_HOST2_URL: [HOST2_RESULT],
                                GET_POOL_URL: [POOL_RESULT],
                                GET_SNAP_URL: [SNAPSHOT_RESULT],
                                SNAPSHOT_URL: SNAPSHOT_RESULT,
                                FC_PORT_URL: [],
                                MAP_URL: [],
                                MAP2_URL: []},
                           POST={VOLUMES_URL: VOLUME_RESULT,
                                 HOSTS_URL: HOST_RESULT,
                                 MAP_URL + APPROVAL: dict(lun=1),
                                 MAP2_URL + APPROVAL: dict(lun=1),
                                 ADD_PORT_URL: None},
                           PUT={VOLUME_URL + APPROVAL: VOLUME_RESULT},
                           DELETE={UNMAP_URL + APPROVAL: None,
                                   VOLUME_URL + APPROVAL: None,
                                   SNAPSHOT_URL + APPROVAL: None})

test_volume = mock.MagicMock(id=1, size=1)
test_snapshot = mock.MagicMock(id=2, volume=test_volume)


class InfiniboxDriverTestCase(test.TestCase):
    def setUp(self):
        super(InfiniboxDriverTestCase, self).setUp()

        # create mock configuration
        self.configuration = mock.Mock(spec=configuration.Configuration)
        self.configuration.san_ip = "mockbox"
        self.configuration.infinidat_pool_name = "mockpool"
        self.configuration.san_thin_provision = "thin"
        self.configuration.san_login = "user"
        self.configuration.san_password = "pass"
        self.configuration.volume_backend_name = "mock"

        self.driver = InfiniboxVolumeDriver(configuration=self.configuration)
        self.driver.do_setup(None)
        self.driver._session = mock.Mock(spec=requests.Session)
        self.driver._session.request.side_effect = self._request
        self._responses = copy.deepcopy(GOOD_PATH_RESPONSES)

    def _request(self, action, url, **kwargs):
        result = self._responses[action][url]
        response = requests.Response()
        if type(result) == int:
            # tests set the response to an int of a bad status code if they
            # want the api call to fail
            response.status_code = result
            response.raw = six.BytesIO(six.b(json.dumps(dict())))
        else:
            response.status_code = 200
            response.raw = six.BytesIO(six.b(json.dumps(dict(result=result))))
        return response

    def test_check_for_setup_error(self):
        self.driver.check_for_setup_error()

    def test_get_volume_stats_refreshes(self):
        result = self.driver.get_volume_stats()
        self.assertEqual(1, result["free_capacity_gb"])
        # change the "free space" in the pool
        self._responses["GET"][GET_POOL_URL][0]["free_physical_space"] = 0
        # no refresh - free capacity should stay the same
        result = self.driver.get_volume_stats(refresh=False)
        self.assertEqual(1, result["free_capacity_gb"])
        # refresh - free capacity should change to 0
        result = self.driver.get_volume_stats(refresh=True)
        self.assertEqual(0, result["free_capacity_gb"])

    def test_get_volume_stats_pool_not_found(self):
        self._responses["GET"][GET_POOL_URL] = []
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.get_volume_stats)

    def test_initialize_connection(self):
        connector = {'wwpns': ['00:11:22:33:44:55:66:77']}
        self._responses["GET"][GET_HOST_URL] = []     # host doesn't exist yet
        result = self.driver.initialize_connection(test_volume, connector)
        self.assertEqual(1, result["data"]["target_lun"])
        self.assertEqual("rw", result["data"]["access_mode"])

    def test_initialize_connection_host_exists(self):
        connector = {'wwpns': ['00:11:22:33:44:55:66:77']}
        result = self.driver.initialize_connection(test_volume, connector)
        self.assertEqual(1, result["data"]["target_lun"])
        self.assertEqual("rw", result["data"]["access_mode"])

    def test_initialize_connection_mapping_exists(self):
        connector = {'wwpns': ['00:11:22:33:44:55:66:77']}
        self._responses["GET"][MAP_URL] = [{'lun': 888, 'volume_id': 1}]
        result = self.driver.initialize_connection(test_volume, connector)
        self.assertEqual(888, result["data"]["target_lun"])
        self.assertEqual("rw", result["data"]["access_mode"])

    def test_initialize_connection_multiple_hosts(self):
        connector = {'wwpns': ['00:11:22:33:44:55:66:77',
                               '11:11:22:33:44:55:66:77']}
        result = self.driver.initialize_connection(test_volume, connector)
        self.assertEqual(1, result["data"]["target_lun"])
        self.assertEqual("rw", result["data"]["access_mode"])

    def test_initialize_connection_map_write_protecetd_vol(self):
        connector = {'wwpns': ['00:11:22:33:44:55:66:77']}
        self._responses["GET"][GET_VOLUME_URL] = [VOLUME_RESULT_WP]
        result = self.driver.initialize_connection(test_volume, connector)
        self.assertEqual(1, result["data"]["target_lun"])
        self.assertEqual("ro", result["data"]["access_mode"])

    def test_initialize_connection_volume_doesnt_exist(self):
        connector = {'wwpns': ['00:11:22:33:44:55:66:77']}
        self._responses["GET"][GET_VOLUME_URL] = []
        self.assertRaises(exception.InvalidVolume,
                          self.driver.initialize_connection,
                          test_volume, connector)

    def test_initialize_connection_create_fails(self):
        connector = {'wwpns': ['00:11:22:33:44:55:66:77']}
        self._responses["GET"][GET_HOST_URL] = []     # host doesn't exist yet
        self._responses["POST"][HOSTS_URL] = 500
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          test_volume, connector)

    def test_initialize_connection_map_fails(self):
        connector = {'wwpns': ['00:11:22:33:44:55:66:77']}
        self._responses["POST"][MAP_URL + APPROVAL] = 500
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          test_volume, connector)

    def test_terminate_connection(self):
        connector = {'wwpns': ['00:11:22:33:44:55:66:77']}
        self.driver.terminate_connection(test_volume, connector)

    def test_terminate_connection_volume_doesnt_exist(self):
        connector = {'wwpns': ['00:11:22:33:44:55:66:77']}
        self._responses["GET"][GET_VOLUME_URL] = []
        self.assertRaises(exception.InvalidVolume,
                          self.driver.terminate_connection,
                          test_volume, connector)

    def test_terminate_connection_api_fail(self):
        connector = {'wwpns': ['00:11:22:33:44:55:66:77']}
        self._responses["DELETE"][UNMAP_URL + APPROVAL] = 500
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.terminate_connection,
                          test_volume, connector)

    def test_create_volume(self):
        self.driver.create_volume(test_volume)

    def test_create_volume_pool_not_found(self):
        self._responses["GET"][GET_POOL_URL] = []
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.create_volume, test_volume)

    def test_create_volume_api_fail(self):
        self._responses["POST"][VOLUMES_URL] = 500
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume, test_volume)

    def test_delete_volume(self):
        self.driver.delete_volume(test_volume)

    def test_delete_volume_doesnt_exist(self):
        self._responses["GET"][GET_VOLUME_URL] = []
        # should not raise an exception
        self.driver.delete_volume(test_volume)

    def test_delete_volume_doesnt_exist_on_delete(self):
        self._responses["DELETE"][VOLUME_URL + APPROVAL] = 404
        # due to a possible race condition (get+delete is not atomic) the
        # GET may return the volume but it may still be deleted before
        # the DELETE request
        # In this case we still should not raise an exception
        self.driver.delete_volume(test_volume)

    def test_delete_volume_with_children(self):
        self._responses["GET"][GET_VOLUME_URL][0]['has_children'] = True
        self.assertRaises(exception.VolumeIsBusy,
                          self.driver.delete_volume, test_volume)

    def test_delete_volume_with_internal_parent(self):
        self._responses["GET"][GET_VOLUME_URL][0]['parent_id'] = 2
        self._responses["GET"][SNAPSHOT_URL]['name'] = 'mock-internal'
        self.driver.delete_volume(test_volume)

    def test_delete_volume_api_fail(self):
        self._responses["DELETE"][VOLUME_URL + APPROVAL] = 500
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.delete_volume, test_volume)

    def test_extend_volume(self):
        self.driver.extend_volume(test_volume, 2)

    def test_extend_volume_api_fail(self):
        self._responses["PUT"][VOLUME_URL + APPROVAL] = 500
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.extend_volume, test_volume, 2)

    def test_create_snapshot(self):
        self.driver.create_snapshot(test_snapshot)

    def test_create_snapshot_volume_doesnt_exist(self):
        self._responses["GET"][GET_VOLUME_URL] = []
        self.assertRaises(exception.InvalidVolume,
                          self.driver.create_snapshot, test_snapshot)

    def test_create_snapshot_api_fail(self):
        self._responses["POST"][VOLUMES_URL] = 500
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_snapshot, test_snapshot)

    def test_create_volume_from_snapshot(self):
        new_volume = mock.MagicMock(id=3, size=1)
        self.driver.create_volume_from_snapshot(new_volume, test_snapshot)

    def test_create_volume_from_snapshot_doesnt_exist(self):
        new_volume = mock.MagicMock(id=3, size=1)
        self._responses["GET"][GET_SNAP_URL] = []
        self.assertRaises(exception.InvalidSnapshot,
                          self.driver.create_volume_from_snapshot,
                          new_volume, test_snapshot)

    def test_create_volume_from_snapshot_api_fail(self):
        new_volume = mock.MagicMock(id=3, size=1)
        self._responses["POST"][VOLUMES_URL] = 500
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          new_volume, test_snapshot)

    def test_delete_snapshot(self):
        self.driver.delete_snapshot(test_snapshot)

    def test_delete_snapshot_doesnt_exist(self):
        self._responses["GET"][GET_SNAP_URL] = []
        # should not raise an exception
        self.driver.delete_snapshot(test_snapshot)

    def test_delete_snapshot_doesnt_exist_on_delete(self):
        self._responses["DELETE"][SNAPSHOT_URL + APPROVAL] = 404
        # due to a possible race condition (get+delete is not atomic) the
        # GET may return the snapshot but it may still be deleted before
        # the DELETE request
        # In this case we still should not raise an exception
        self.driver.delete_snapshot(test_snapshot)

    def test_delete_snapshot_with_children(self):
        self._responses["GET"][GET_SNAP_URL][0]['has_children'] = True
        self.assertRaises(exception.SnapshotIsBusy,
                          self.driver.delete_snapshot, test_snapshot)

    def test_delete_snapshot_api_fail(self):
        self._responses["DELETE"][SNAPSHOT_URL + APPROVAL] = 500
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.delete_snapshot, test_snapshot)

    def test_create_cloned_volume(self):
        # the internals of this function are tested by testing create_snapshot
        # and create_volume_from_snapshot
        with mock.patch("oslo_utils.uuidutils.generate_uuid",
                        return_value="2"):
            internal_snapshot_url = GET_SNAP_URL + "-internal"
            self._responses["GET"][internal_snapshot_url] = [SNAPSHOT_RESULT]
            new_volume = mock.MagicMock(id=3, size=1)
            self.driver.create_cloned_volume(new_volume, test_volume)

    def test_create_export(self):
        self.driver.create_export(None, test_volume)

    def test_remove_export(self):
        self.driver.remove_export(None, test_volume)
