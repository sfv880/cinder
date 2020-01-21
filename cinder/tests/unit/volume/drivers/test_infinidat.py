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

import functools
import platform
import socket
from unittest import mock

from oslo_utils import units

from cinder import exception
from cinder import test
from cinder import version
from cinder.volume import configuration
from cinder.volume.drivers import infinidat

TEST_WWN_1 = '00:11:22:33:44:55:66:77'
TEST_WWN_2 = '11:11:22:33:44:55:66:77'

TEST_IP_ADDRESS = '1.1.1.1'
TEST_IQN = 'iqn.2012-07.org.fake:01'
TEST_ISCSI_TCP_PORT = 3260

TEST_TARGET_PORTAL = '{}:{}'.format(TEST_IP_ADDRESS, TEST_ISCSI_TCP_PORT)

test_volume = mock.Mock(id=1, size=1, volume_type_id=1)
test_snapshot = mock.Mock(id=2, volume=test_volume, volume_id='1')
test_clone = mock.Mock(id=3, size=1)
test_group = mock.Mock(id=4)
test_snapgroup = mock.Mock(id=5, group=test_group)
test_connector = dict(wwpns=[TEST_WWN_1],
                      initiator=TEST_IQN)


def skip_driver_setup(func):
    @functools.wraps(func)
    def f(*args, **kwargs):
        return func(*args, **kwargs)

    f.__skip_driver_setup = True
    return f


class FakeInfinisdkException(Exception):
    pass


class InfiniboxDriverTestCaseBase(test.TestCase):
    def _test_skips_driver_setup(self):
        test_method_name = self.id().split('.')[-1]
        test_method = getattr(self, test_method_name)
        return getattr(test_method, '__skip_driver_setup', False)

    def setUp(self):
        super(InfiniboxDriverTestCaseBase, self).setUp()

        # create mock configuration
        self.configuration = mock.Mock(spec=configuration.Configuration)
        self.configuration.infinidat_storage_protocol = 'fc'
        self.configuration.san_ip = 'mockbox'
        self.configuration.infinidat_pool_name = 'mockpool'
        self.configuration.san_thin_provision = True
        self.configuration.san_login = 'user'
        self.configuration.san_password = 'pass'
        self.configuration.volume_backend_name = 'mock'
        self.configuration.volume_dd_blocksize = '1M'
        self.configuration.use_multipath_for_image_xfer = False
        self.configuration.enforce_multipath_for_image_xfer = False
        self.configuration.num_volume_device_scan_tries = 1
        self.configuration.san_is_local = False
        self.configuration.chap_username = None
        self.configuration.chap_password = None
        self.configuration.infinidat_use_compression = None
        self.configuration.max_over_subscription_ratio = 10.0

        self.driver = infinidat.InfiniboxVolumeDriver(
            configuration=self.configuration)
        self._system = self._infinibox_mock()
        # mock external library dependencies
        infinisdk = self.patch("cinder.volume.drivers.infinidat.infinisdk")
        capacity = self.patch("cinder.volume.drivers.infinidat.capacity")
        self._iqn = self.patch("cinder.volume.drivers.infinidat.iqn")
        self._wwn = self.patch("cinder.volume.drivers.infinidat.wwn")
        self._wwn.WWN = mock.Mock
        self._iqn.IQN = mock.Mock
        capacity.byte = 1
        capacity.GiB = units.Gi
        infinisdk.core.exceptions.InfiniSDKException = FakeInfinisdkException
        infinisdk.InfiniBox.return_value = self._system

        if not self._test_skips_driver_setup():
            self.driver.do_setup(None)

    def _infinibox_mock(self):
        result = mock.Mock()
        self._mock_volume = mock.Mock()
        self._mock_volume.get_pool_name.return_value = (
            self.configuration.infinidat_pool_name)
        self._mock_volume.get_size.return_value = 1 * units.Gi
        self._mock_volume.has_children.return_value = False
        self._mock_volume.get_logical_units.return_value = []
        self._mock_volume.create_snapshot.return_value = self._mock_volume
        self._mock_volume.get_provisioning.return_value = 'THIN'
        self._mock_volume.is_compression_enabled.return_value = False

        self._mock_host = mock.Mock()
        self._mock_host.get_luns.return_value = []
        self._mock_host.map_volume().get_lun.return_value = 1

        self._mock_pool = mock.Mock()
        self._mock_pool.get_free_physical_capacity.return_value = units.Gi
        self._mock_pool.get_physical_capacity.return_value = units.Gi
        self._mock_pool.get_volumes.return_value = [self._mock_volume]

        self._mock_ns = mock.Mock()
        self._mock_ns.get_ips.return_value = [
            mock.Mock(ip_address=TEST_IP_ADDRESS, enabled=True)]
        self._mock_ns.get_properties.return_value = mock.Mock(
            iscsi_iqn=TEST_IQN, iscsi_tcp_port=TEST_ISCSI_TCP_PORT)

        self._mock_group = mock.Mock()
        self._mock_qos_policy = mock.Mock()

        result.volumes.safe_get.return_value = self._mock_volume
        result.volumes.create.return_value = self._mock_volume
        result.pools.safe_get.return_value = self._mock_pool
        result.hosts.safe_get.return_value = self._mock_host
        result.cons_groups.safe_get.return_value = self._mock_group
        result.cons_groups.create.return_value = self._mock_group
        result.hosts.create.return_value = self._mock_host
        result.network_spaces.safe_get.return_value = self._mock_ns
        result.components.nodes.get_all.return_value = []
        result.qos_policies.create.return_value = self._mock_qos_policy
        result.qos_policies.safe_get.return_value = None
        return result

    def _raise_infinisdk(self, *args, **kwargs):
        raise FakeInfinisdkException()


class InfiniboxDriverTestCase(InfiniboxDriverTestCaseBase):
    @staticmethod
    def _generate_mock_object_metadata(infinidat_object, cinder_object):
        return {"system": "openstack",
                "backend_volume_name": infinidat_object.get_name(),
                "openstack_version": version.version_info.release_string(),
                "cinder_id": cinder_object.id,
                "cinder_name": cinder_object.name,
                "host.created_by": infinidat._INFINIDAT_CINDER_IDENTIFIER}

    def _validate_object_metadata(self, infinidat_object, cinder_object):
        infinidat_object.set_metadata_from_dict.assert_called_once_with(
            self._generate_mock_object_metadata(infinidat_object,
                                                cinder_object))

    @staticmethod
    def _generate_mock_host_metadata():
        return {"system": "openstack",
                "openstack_version": version.version_info.release_string(),
                "hostname": socket.gethostname(),
                "platform": platform.platform(),
                "host.created_by": infinidat._INFINIDAT_CINDER_IDENTIFIER}

    def _validate_host_metadata(self):
        self._mock_host.set_metadata_from_dict.assert_called_once_with(
            self._generate_mock_host_metadata())

    @skip_driver_setup
    def test__setup_and_get_system_object(self):
        # This test should skip the driver setup, as it generates more calls to
        # the add_auto_retry, set_source_identifier and login methods:
        auth = (self.configuration.san_login,
                self.configuration.san_password)

        self.driver._setup_and_get_system_object(
            self.configuration.san_ip, auth)

        self._system.api.add_auto_retry.assert_called_once()
        self._system.api.set_source_identifier.assert_called_once_with(
            infinidat._INFINIDAT_CINDER_IDENTIFIER)
        self._system.login.assert_called_once()

    def test_initialize_connection(self):
        self._system.hosts.safe_get.return_value = None
        result = self.driver.initialize_connection(test_volume, test_connector)
        self.assertEqual(1, result["data"]["target_lun"])

    def test_initialize_connection_host_exists(self):
        result = self.driver.initialize_connection(test_volume, test_connector)
        self.assertEqual(1, result["data"]["target_lun"])

    def test_initialize_connection_mapping_exists(self):
        mock_mapping = mock.Mock()
        mock_mapping.get_volume.return_value = self._mock_volume
        mock_mapping.get_lun.return_value = 888
        self._mock_host.get_luns.return_value = [mock_mapping]
        result = self.driver.initialize_connection(test_volume, test_connector)
        self.assertEqual(888, result["data"]["target_lun"])

    def test_initialize_connection_volume_doesnt_exist(self):
        self._system.volumes.safe_get.return_value = None
        self.assertRaises(exception.InvalidVolume,
                          self.driver.initialize_connection,
                          test_volume, test_connector)

    def test_initialize_connection_create_fails(self):
        self._system.hosts.safe_get.return_value = None
        self._system.hosts.create.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          test_volume, test_connector)

    def test_initialize_connection_map_fails(self):
        self._mock_host.map_volume.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          test_volume, test_connector)

    def test_initialize_connection_metadata(self):
        self._system.hosts.safe_get.return_value = None
        self.driver.initialize_connection(test_volume, test_connector)
        self._validate_host_metadata()

    def test_terminate_connection(self):
        self.driver.terminate_connection(test_volume, test_connector)

    def test_terminate_connection_delete_host(self):
        self._mock_host.get_luns.return_value = [object()]
        self.driver.terminate_connection(test_volume, test_connector)
        self.assertEqual(0, self._mock_host.safe_delete.call_count)
        self._mock_host.get_luns.return_value = []
        self.driver.terminate_connection(test_volume, test_connector)
        self.assertEqual(1, self._mock_host.safe_delete.call_count)

    def test_terminate_connection_volume_doesnt_exist(self):
        self._system.volumes.safe_get.return_value = None
        self.assertRaises(exception.InvalidVolume,
                          self.driver.terminate_connection,
                          test_volume, test_connector)

    def test_terminate_connection_api_fail(self):
        self._mock_host.unmap_volume.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.terminate_connection,
                          test_volume, test_connector)

    def test_get_volume_stats_refreshes(self):
        result = self.driver.get_volume_stats()
        self.assertEqual(1, result["free_capacity_gb"])
        # change the "free space" in the pool
        self._mock_pool.get_free_physical_capacity.return_value = 0
        # no refresh - free capacity should stay the same
        result = self.driver.get_volume_stats(refresh=False)
        self.assertEqual(1, result["free_capacity_gb"])
        # refresh - free capacity should change to 0
        result = self.driver.get_volume_stats(refresh=True)
        self.assertEqual(0, result["free_capacity_gb"])

    def test_get_volume_stats_pool_not_found(self):
        self._system.pools.safe_get.return_value = None
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.get_volume_stats)

    def test_get_volume_stats_max_over_subscription_ratio(self):
        result = self.driver.get_volume_stats()
        # check the defaults defined in setUp
        self.assertEqual(10.0, result['max_over_subscription_ratio'])
        self.assertTrue(result['thin_provisioning_support'])
        self.assertFalse(result['thick_provisioning_support'])

    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_create_volume(self, *mocks):
        self.driver.create_volume(test_volume)

    def test_create_volume_pool_not_found(self):
        self._system.pools.safe_get.return_value = None
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.create_volume, test_volume)

    def test_create_volume_api_fail(self):
        self._system.pools.safe_get.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume, test_volume)

    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_create_volume_metadata(self, *mocks):
        self.driver.create_volume(test_volume)
        self._validate_object_metadata(self._mock_volume, test_volume)

    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_create_volume_compression_enabled(self, *mocks):
        self.configuration.infinidat_use_compression = True
        self.driver.create_volume(test_volume)
        self.assertTrue(
            self._system.volumes.create.call_args[1]["compression_enabled"]
        )

    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_create_volume_compression_not_enabled(self, *mocks):
        self.configuration.infinidat_use_compression = False
        self.driver.create_volume(test_volume)
        self.assertFalse(
            self._system.volumes.create.call_args[1]["compression_enabled"]
        )

    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_create_volume_compression_not_available(self, *mocks):
        self._system.compat.has_compression.return_value = False
        self.driver.create_volume(test_volume)
        self.assertNotIn(
            "compression_enabled",
            self._system.volumes.create.call_args[1]
        )

    def test_delete_volume(self):
        self.driver.delete_volume(test_volume)

    def test_delete_volume_doesnt_exist(self):
        self._system.volumes.safe_get.return_value = None
        # should not raise an exception
        self.driver.delete_volume(test_volume)

    def test_delete_volume_with_children(self):
        self._mock_volume.has_children.return_value = True
        self.assertRaises(exception.VolumeIsBusy,
                          self.driver.delete_volume, test_volume)

    def test_extend_volume(self):
        self.driver.extend_volume(test_volume, 2)
        self._mock_volume.resize.assert_called_with(1 * units.Gi)

    def test_extend_volume_api_fail(self):
        self._mock_volume.resize.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.extend_volume, test_volume, 2)

    def test_create_snapshot(self):
        self.driver.create_snapshot(test_snapshot)

    def test_create_snapshot_metadata(self):
        self._mock_volume.create_snapshot.return_value = self._mock_volume
        self.driver.create_snapshot(test_snapshot)
        self._validate_object_metadata(self._mock_volume, test_snapshot)

    def test_create_snapshot_volume_doesnt_exist(self):
        self._system.volumes.safe_get.return_value = None
        self.assertRaises(exception.InvalidVolume,
                          self.driver.create_snapshot, test_snapshot)

    def test_create_snapshot_api_fail(self):
        self._mock_volume.create_snapshot.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_snapshot, test_snapshot)

    @mock.patch("cinder.volume.volume_utils.copy_volume")
    @mock.patch("cinder.utils.brick_get_connector")
    @mock.patch("cinder.utils.brick_get_connector_properties",
                return_value=test_connector)
    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_create_volume_from_snapshot(self, *mocks):
        self.driver.create_volume_from_snapshot(test_clone, test_snapshot)

    def test_create_volume_from_snapshot_doesnt_exist(self):
        self._system.volumes.safe_get.return_value = None
        self.assertRaises(exception.InvalidSnapshot,
                          self.driver.create_volume_from_snapshot,
                          test_clone, test_snapshot)

    def test_create_volume_from_snapshot_create_fails(self):
        self._mock_volume.create_snapshot.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          test_clone, test_snapshot)

    @mock.patch("cinder.utils.brick_get_connector_properties",
                return_value=test_connector)
    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_create_volume_from_snapshot_map_fails(self, *mocks):
        self._mock_host.map_volume.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          test_clone, test_snapshot)

    @mock.patch("cinder.volume.volume_utils.copy_volume")
    @mock.patch("cinder.utils.brick_get_connector")
    @mock.patch("cinder.utils.brick_get_connector_properties",
                return_value=test_connector)
    def test_create_volume_from_snapshot_delete_clone_fails(self, *mocks):
        self._mock_volume.delete.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          test_clone, test_snapshot)

    def test_delete_snapshot(self):
        self.driver.delete_snapshot(test_snapshot)

    def test_delete_snapshot_doesnt_exist(self):
        self._system.volumes.safe_get.return_value = None
        # should not raise an exception
        self.driver.delete_snapshot(test_snapshot)

    def test_delete_snapshot_api_fail(self):
        self._mock_volume.safe_delete.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.delete_snapshot, test_snapshot)

    @mock.patch("cinder.volume.volume_utils.copy_volume")
    @mock.patch("cinder.utils.brick_get_connector")
    @mock.patch("cinder.utils.brick_get_connector_properties",
                return_value=test_connector)
    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_create_cloned_volume(self, *mocks):
        self.driver.create_cloned_volume(test_clone, test_volume)

    def test_create_cloned_volume_volume_already_mapped(self):
        mock_mapping = mock.Mock()
        mock_mapping.get_volume.return_value = self._mock_volume
        self._mock_volume.get_logical_units.return_value = [mock_mapping]
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume,
                          test_clone, test_volume)

    def test_create_cloned_volume_create_fails(self):
        self._system.volumes.create.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume,
                          test_clone, test_volume)

    @mock.patch("cinder.utils.brick_get_connector_properties",
                return_value=test_connector)
    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_create_cloned_volume_map_fails(self, *mocks):
        self._mock_host.map_volume.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_cloned_volume,
                          test_clone, test_volume)

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_create_group(self, *mocks):
        self.driver.create_group(None, test_group)

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_create_group_metadata(self, *mocks):
        self.driver.create_group(None, test_group)
        self._validate_object_metadata(self._mock_group, test_group)

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_create_group_twice(self, *mocks):
        self.driver.create_group(None, test_group)
        self.driver.create_group(None, test_group)

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_create_group_api_fail(self, *mocks):
        self._system.cons_groups.create.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_group,
                          None, test_group)

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_delete_group(self, *mocks):
        self.driver.delete_group(None, test_group, [test_volume])

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_delete_group_doesnt_exist(self, *mocks):
        self._system.cons_groups.safe_get.return_value = None
        self.driver.delete_group(None, test_group, [test_volume])

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_delete_group_api_fail(self, *mocks):
        self._mock_group.safe_delete.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.delete_group,
                          None, test_group, [test_volume])

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_update_group_add_and_remove(self, *mocks):
        self.driver.update_group(None, test_group,
                                 [test_volume], [test_volume])

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_update_group_api_fail(self, *mocks):
        self._mock_group.add_member.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.update_group,
                          None, test_group,
                          [test_volume], [test_volume])

    @mock.patch("cinder.volume.volume_utils.copy_volume")
    @mock.patch("cinder.utils.brick_get_connector")
    @mock.patch("cinder.utils.brick_get_connector_properties",
                return_value=test_connector)
    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
                return_value=True)
    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_create_group_from_src_snaps(self, *mocks):
        self.driver.create_group_from_src(None, test_group, [test_volume],
                                          test_snapgroup, [test_snapshot],
                                          None, None)

    @mock.patch("cinder.volume.volume_utils.copy_volume")
    @mock.patch("cinder.utils.brick_get_connector")
    @mock.patch("cinder.utils.brick_get_connector_properties",
                return_value=test_connector)
    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
                return_value=True)
    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_create_group_from_src_vols(self, *mocks):
        self.driver.create_group_from_src(None, test_group, [test_volume],
                                          None, None,
                                          test_group, [test_volume])

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_create_group_snap(self, *mocks):
        mock_snapgroup = mock.Mock()
        mock_snapgroup.get_members.return_value = [self._mock_volume]
        self._mock_volume.get_parent.return_value = self._mock_volume
        self._mock_volume.get_name.return_value = ''
        self._mock_group.create_snapshot.return_value = mock_snapgroup
        self.driver.create_group_snapshot(None,
                                          test_snapgroup,
                                          [test_snapshot])

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_create_group_snap_api_fail(self, *mocks):
        self._mock_group.create_snapshot.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_group_snapshot, None,
                          test_snapgroup, [test_snapshot])

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_delete_group_snap(self, *mocks):
        self.driver.delete_group_snapshot(None,
                                          test_snapgroup,
                                          [test_snapshot])

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_delete_group_snap_does_not_exist(self, *mocks):
        self._system.cons_groups.safe_get.return_value = None
        self.driver.delete_group_snapshot(None,
                                          test_snapgroup,
                                          [test_snapshot])

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_delete_group_snap_invalid_group(self, *mocks):
        self._mock_group.is_snapgroup.return_value = False
        self.assertRaises(exception.InvalidGroupSnapshot,
                          self.driver.delete_group_snapshot,
                          None, test_snapgroup, [test_snapshot])

    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
                return_value=True)
    def test_delete_group_snap_api_fail(self, *mocks):
        self._mock_group.safe_delete.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.delete_group_snapshot,
                          None, test_snapgroup, [test_snapshot])

    def test_terminate_connection_force_detach(self):
        mock_infinidat_host = mock.Mock()
        mock_infinidat_host.get_ports.return_value = [
            self._wwn.WWN(TEST_WWN_1)]
        mock_mapping = mock.Mock()
        mock_mapping.get_host.return_value = mock_infinidat_host
        self._mock_volume.get_logical_units.return_value = [mock_mapping]
        # connector is None - force detach - detach all mappings
        self.driver.terminate_connection(test_volume, None)
        # make sure we actually detached the host mapping
        self._mock_host.unmap_volume.assert_called_once()
        self._mock_host.safe_delete.assert_called_once()


class InfiniboxDriverTestCaseFC(InfiniboxDriverTestCaseBase):
    def test_initialize_connection_multiple_wwpns(self):
        connector = {'wwpns': [TEST_WWN_1, TEST_WWN_2]}
        result = self.driver.initialize_connection(test_volume, connector)
        self.assertEqual(1, result["data"]["target_lun"])

    def test_validate_connector(self):
        fc_connector = {'wwpns': [TEST_WWN_1, TEST_WWN_2]}
        iscsi_connector = {'initiator': TEST_IQN}
        self.driver.validate_connector(fc_connector)
        self.assertRaises(exception.InvalidConnectorException,
                          self.driver.validate_connector, iscsi_connector)


class InfiniboxDriverTestCaseISCSI(InfiniboxDriverTestCaseBase):
    def setUp(self):
        super(InfiniboxDriverTestCaseISCSI, self).setUp()
        self.configuration.infinidat_storage_protocol = 'iscsi'
        self.configuration.infinidat_iscsi_netspaces = ['netspace1']
        self.configuration.use_chap_auth = False
        self.driver.do_setup(None)

    def test_setup_without_netspaces_configured(self):
        self.configuration.infinidat_iscsi_netspaces = []
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.do_setup, None)

    def _assert_plurals(self, result, expected_length):
        self.assertEqual(expected_length, len(result['data']['target_luns']))
        self.assertEqual(expected_length, len(result['data']['target_iqns']))
        self.assertEqual(expected_length,
                         len(result['data']['target_portals']))
        self.assertTrue(all(lun == 1 for lun in result['data']['target_luns']))
        self.assertTrue(
            all(iqn == test_connector['initiator'] for
                iqn in result['data']['target_iqns']))

        self.assertTrue(all(target_portal == TEST_TARGET_PORTAL for
                            target_portal in result['data']['target_portals']))

    def test_initialize_connection(self):
        result = self.driver.initialize_connection(test_volume, test_connector)
        self.assertEqual(1, result['data']['target_lun'])
        self._assert_plurals(result, 1)

    def test_initialize_netspace_does_not_exist(self):
        self._system.network_spaces.safe_get.return_value = None
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.initialize_connection,
                          test_volume, test_connector)

    def test_initialize_netspace_has_no_ips(self):
        self._mock_ns.get_ips.return_value = []
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.initialize_connection,
                          test_volume, test_connector)

    def test_initialize_connection_with_chap(self):
        self.configuration.use_chap_auth = True
        result = self.driver.initialize_connection(test_volume, test_connector)
        self.assertEqual(1, result['data']['target_lun'])
        self.assertEqual('CHAP', result['data']['auth_method'])
        self.assertIn('auth_username', result['data'])
        self.assertIn('auth_password', result['data'])

    def test_initialize_connection_multiple_netspaces(self):
        self.configuration.infinidat_iscsi_netspaces = ['netspace1',
                                                        'netspace2']
        result = self.driver.initialize_connection(test_volume, test_connector)
        self.assertEqual(1, result['data']['target_lun'])
        self._assert_plurals(result, 2)

    def test_initialize_connection_plurals(self):
        result = self.driver.initialize_connection(test_volume, test_connector)
        self._assert_plurals(result, 1)

    def test_terminate_connection(self):
        self.driver.terminate_connection(test_volume, test_connector)

    def test_validate_connector(self):
        fc_connector = {'wwpns': [TEST_WWN_1, TEST_WWN_2]}
        iscsi_connector = {'initiator': TEST_IQN}
        self.driver.validate_connector(iscsi_connector)
        self.assertRaises(exception.InvalidConnectorException,
                          self.driver.validate_connector, fc_connector)


class InfiniboxDriverTestCaseQoS(InfiniboxDriverTestCaseBase):
    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_qos_max_ipos(self, qos_specs):
        qos_specs.return_value = {'qos_specs': {'id': 'qos_name',
                                                'consumer': 'back-end',
                                                'specs': {'maxIOPS': 1000,
                                                          'maxBWS': None}}}
        self.driver.create_volume(test_volume)
        self._system.qos_policies.create.assert_called_once()
        self._mock_qos_policy.assign_entity.assert_called_once()

    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_qos_max_bws(self, qos_specs):
        qos_specs.return_value = {'qos_specs': {'id': 'qos_name',
                                                'consumer': 'back-end',
                                                'specs': {'maxIOPS': None,
                                                          'maxBWS': 10000}}}
        self.driver.create_volume(test_volume)
        self._system.qos_policies.create.assert_called_once()
        self._mock_qos_policy.assign_entity.assert_called_once()

    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_qos_no_compat(self, qos_specs):
        qos_specs.return_value = {'qos_specs': {'id': 'qos_name',
                                                'consumer': 'back-end',
                                                'specs': {'maxIOPS': 1000,
                                                          'maxBWS': 10000}}}
        self._system.compat.has_qos.return_value = False
        self.driver.create_volume(test_volume)
        self._system.qos_policies.create.assert_not_called()
        self._mock_qos_policy.assign_entity.assert_not_called()

    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_qos_volume_type_id_none(self, qos_specs):
        qos_specs.return_value = {'qos_specs': {'id': 'qos_name',
                                                'consumer': 'back-end',
                                                'specs': {'maxIOPS': 1000,
                                                          'maxBWS': 10000}}}
        test_volume = mock.Mock(id=1, size=1, volume_type_id=None)
        self.driver.create_volume(test_volume)
        self._system.qos_policies.create.assert_not_called()
        self._mock_qos_policy.assign_entity.assert_not_called()

    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_qos_no_specs(self, qos_specs):
        qos_specs.return_value = {'qos_specs': None}
        self.driver.create_volume(test_volume)
        self._system.qos_policies.create.assert_not_called()
        self._mock_qos_policy.assign_entity.assert_not_called()

    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_qos_front_end(self, qos_specs):
        qos_specs.return_value = {'qos_specs': {'id': 'qos_name',
                                                'consumer': 'front-end',
                                                'specs': {'maxIOPS': 1000,
                                                          'maxBWS': 10000}}}
        self.driver.create_volume(test_volume)
        self._system.qos_policies.create.assert_not_called()
        self._mock_qos_policy.assign_entity.assert_not_called()

    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_qos_specs_empty(self, qos_specs):
        qos_specs.return_value = {'qos_specs': {'id': 'qos_name',
                                                'consumer': 'back-end',
                                                'specs': {'maxIOPS': None,
                                                          'maxBWS': None}}}
        self.driver.create_volume(test_volume)
        self._system.qos_policies.create.assert_not_called()
        self._mock_qos_policy.assign_entity.assert_not_called()

    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_qos_policy_exists(self, qos_specs):
        qos_specs.return_value = {'qos_specs': {'id': 'qos_name',
                                                'consumer': 'back-end',
                                                'specs': {'maxIOPS': 1000,
                                                          'maxBWS': 10000}}}
        self._system.qos_policies.safe_get.return_value = self._mock_qos_policy
        self.driver.create_volume(test_volume)
        self._system.qos_policies.create.assert_not_called()
        self._mock_qos_policy.assign_entity.assert_called()


class InfiniboxDriverTestCaseManageApi(InfiniboxDriverTestCaseBase):
    def setUp(self):
        super(InfiniboxDriverTestCaseManageApi, self).setUp()

    @staticmethod
    def _generate_mock_object_metadata(cinder_object):
        return {"system": "openstack",
                "openstack_version": version.version_info.release_string(),
                "cinder_id": cinder_object.id,
                "cinder_name": cinder_object.name,
                "host.created_by": infinidat._INFINIDAT_CINDER_IDENTIFIER}

    @staticmethod
    def _validate_object_metadata(infinidat_object, cinder_object):
        infinidat_object.set_metadata_from_dict.assert_called()

    def _generate_extra_info(self):
        return dict(
            pool_name=self._mock_volume.get_pool_name(),
            type=self._mock_volume.get_type(),
            qos_policy=self._mock_volume.get_qos_policy(),
            metadata=str(self._mock_volume.get_all_metadata()),
        )

    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_manage_existing(self, *mocks):
        self.driver.manage_existing(test_volume,
                                    {'source-name': 'existing_volume'})

    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_manage_existing_no_such_volume(self, *mocks):
        self._system.volumes.safe_get.return_value = None
        self.assertRaises(exception.InvalidVolume, self.driver.manage_existing,
                          test_volume,
                          {'source-name': 'existing_volume'})

    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_manage_existing_wrong_pool(self, *mocks):
        self._mock_volume.get_pool_name.return_value = 'blah'
        self.assertRaises(exception.InvalidInput, self.driver.manage_existing,
                          test_volume,
                          {'source-name': 'existing_volume'})

    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_manage_existing_validate_metadata(self, *mocks):
        self.driver.manage_existing(test_volume,
                                    {'source-name': 'existing_volume'})
        self._validate_object_metadata(self._mock_volume, test_volume)

    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_existing_get_size(self, *mocks):
        size = self.driver.manage_existing_get_size(
            test_volume, {'source-name': 'existing_volume'})
        self.assertEqual(size, 1)

    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_existing_get_size_round_up_correctly(self, *mocks):
        self._mock_volume.get_size.return_value = 1.7 * units.Gi
        size = self.driver.manage_existing_get_size(
            test_volume, {'source-name': 'existing_volume'})
        self.assertEqual(size, 2)

    def _setup_get_manageable_volumes(self):
        self._mock_volume.get_name.return_value = self.driver._make_ds_name(
            test_volume, 'vol')
        self._mock_volume.is_snapshot.return_value = False
        self._mock_volume.get_type.return_value = 'MASTER'
        self._mock_volume.get_qos_policy.return_value = None
        self._mock_volume.get_all_metadata.return_value = None

        self.expected_refs = [
            dict(
                cinder_id=None,
                reference={'name': self._mock_volume.get_name()},
                size=self._mock_volume.get_size() / units.Gi,
                extra_info=self._generate_extra_info(),
                safe_to_manage=True,
                reason_not_safe='',
            ),
        ]

    @staticmethod
    def _setup_mock_pagination():
        marker = mock.Mock()
        limit = mock.Mock()
        offset = mock.Mock()
        sort_keys = mock.Mock()
        sort_dirs = mock.Mock()
        return [marker, limit, offset, sort_keys, sort_dirs]

    def test_get_manageable_volumes(self, *mocks):
        self._setup_get_manageable_volumes()
        page_values = [None, 10, 0, [],
                       []]  # marker, limit, offset, sort_keys, sort_dirs
        sorted_entries = self.driver.get_manageable_volumes([], *page_values)
        self.assertEqual(sorted_entries, self.expected_refs)

    def test_get_manageable_volumes_no_volumes(self, *mocks):
        self._mock_pool.get_volumes.return_value = []
        sorted_entries = self.driver.get_manageable_volumes([], None, 10, 0,
                                                            [], [])
        self.assertEqual(sorted_entries, [])

    def test_get_manageable_volumes_already_managed(self, *mocks):
        page_values = [None, 10, 0, [],
                       []]  # marker, limit, offset, sort_keys, sort_dirs
        self._setup_get_manageable_volumes()
        self._mock_volume.get_all_metadata.return_value = (
            self._generate_mock_object_metadata(test_volume))
        sorted_entries = self.driver.get_manageable_volumes([test_volume],
                                                            *page_values)
        self.expected_refs[0]['cinder_id'] = test_volume.id
        self.expected_refs[0]['safe_to_manage'] = False
        self.expected_refs[0]['reason_not_safe'] = 'Already managed by cinder'
        self.expected_refs[0]['extra_info'] = self._generate_extra_info()
        self.assertEqual(sorted_entries, self.expected_refs)

    def test_get_manageable_volumes_no_metadata(self, *mocks):
        page_values = [None, 10, 0, [],
                       []]  # marker, limit, offset, sort_keys, sort_dirs
        self._setup_get_manageable_volumes()
        sorted_entries = self.driver.get_manageable_volumes([test_volume],
                                                            *page_values)
        self.expected_refs[0]['cinder_id'] = test_volume.id
        self.expected_refs[0]['safe_to_manage'] = False
        self.expected_refs[0]['reason_not_safe'] = (
            'Already managed by cinder but has no backend metadata')
        self.assertEqual(sorted_entries, self.expected_refs)

    ###
    # SNAPSHOT TESTS
    ###
    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_manage_existing_snapshot(self, *mocks):
        self.driver.manage_existing_snapshot(
            test_volume, {'source-name': 'existing_volume'})

    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_manage_existing_snapshot_none(self, *mocks):
        self._system.volumes.safe_get.return_value = None
        self.assertRaises(exception.InvalidSnapshot,
                          self.driver.manage_existing_snapshot, test_volume,
                          {'source-name': 'existing_volume'})

    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_manage_existing_snapshot_validate_metadata(self, *mocks):
        self.driver.manage_existing_snapshot(
            test_volume, {'source-name': 'existing_volume'})
        self._validate_object_metadata(self._mock_volume, test_volume)

    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_existing_snapshot_get_size(self, *mocks):
        size = self.driver.manage_existing_snapshot_get_size(
            test_volume, {'source-name': 'existing_volume'})
        self.assertEqual(size, 1)

    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_existing_snapshot_get_size_round_up_correctly(self, *mocks):
        self._mock_volume.get_size.return_value = 1.5 * units.Gi
        size = self.driver.manage_existing_snapshot_get_size(
            test_volume, {'source-name': 'existing_volume'})
        self.assertEqual(size, 2)

    def _setup_get_manageable_snapshots(self):
        self._mock_volume.get_name.return_value = self.driver._make_ds_name(
            test_snapshot, 'snap')
        self._mock_volume.is_snapshot.return_value = True
        self._mock_volume.get_type.return_value = 'SNAPSHOT'
        self._mock_volume.get_qos_policy.return_value = None
        self._mock_volume.get_all_metadata.return_value = None
        self._mock_volume.get_parent.return_value = self._mock_volume

        self.expected_refs = [
            dict(
                cinder_id=None,
                reference={'name': self._mock_volume.get_name()},
                size=self._mock_volume.get_size() / units.Gi,
                extra_info=self._generate_extra_info(),
                safe_to_manage=True,
                reason_not_safe='',
                source_reference={'name': self._mock_volume.get_name()}
            ),
        ]

    def test_get_manageable_snapshots(self, *mocks):
        self._setup_get_manageable_snapshots()
        page_values = [None, 10, 0, [],
                       []]  # marker, limit, offset, sort_keys, sort_dirs
        sorted_entries = self.driver.get_manageable_snapshots([], *page_values)
        self.assertEqual(sorted_entries, self.expected_refs)

    def test_get_manageable_snapshots_none(self, *mocks):
        self._mock_pool.get_volumes.return_value = []
        sorted_entries = self.driver.get_manageable_snapshots([], None, 10, 0,
                                                              [], [])
        self.assertEqual(sorted_entries, [])

    def test_get_manageable_snapshots_already_managed(self, *mocks):
        page_values = [None, 10, 0, [],
                       []]  # marker, limit, offset, sort_keys, sort_dirs
        self._setup_get_manageable_snapshots()
        self._mock_volume.get_all_metadata.return_value = (
            self._generate_mock_object_metadata(test_snapshot))
        sorted_entries = self.driver.get_manageable_snapshots([test_snapshot],
                                                              *page_values)
        self.expected_refs[0]['cinder_id'] = test_snapshot.id
        self.expected_refs[0]['safe_to_manage'] = False
        self.expected_refs[0]['reason_not_safe'] = 'Already managed by cinder'
        self.expected_refs[0]['extra_info'] = self._generate_extra_info()
        self.assertEqual(sorted_entries, self.expected_refs)

    def test_get_manageable_snapshots_managed_no_metadata(self, *mocks):
        page_values = [None, 10, 0, [],
                       []]  # marker, limit, offset, sort_keys, sort_dirs
        self._setup_get_manageable_snapshots()
        sorted_entries = self.driver.get_manageable_snapshots([test_snapshot],
                                                              *page_values)
        self.expected_refs[0]['cinder_id'] = test_snapshot.id
        self.expected_refs[0]['safe_to_manage'] = False
        self.expected_refs[0]['reason_not_safe'] = (
            'Already managed by cinder but has no backend metadata')
        self.assertEqual(sorted_entries, self.expected_refs)
