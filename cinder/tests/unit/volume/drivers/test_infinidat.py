# Copyright 2022 Infinidat Ltd.
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

from cinder import context
from cinder import exception
from cinder.tests.unit import test
from cinder import version
from cinder.volume import configuration
from cinder.volume.drivers import infinidat


TEST_LUN = 1
TEST_WWN_1 = '00:11:22:33:44:55:66:77'
TEST_WWN_2 = '11:11:22:33:44:55:66:77'
TEST_IP_ADDRESS1 = '1.1.1.1'
TEST_IP_ADDRESS2 = '2.2.2.2'
TEST_IP_ADDRESS3 = '3.3.3.3'
TEST_IP_ADDRESS4 = '4.4.4.4'
TEST_INITIATOR_IQN1 = 'iqn.2012-07.org.initiator:01'
TEST_INITIATOR_IQN2 = 'iqn.2012-07.org.initiator:02'
TEST_TARGET_IQN = 'iqn.2012-07.org.target:01'
TEST_ISCSI_TCP_PORT1 = 3261
TEST_ISCSI_TCP_PORT2 = 3262
TEST_ISCSI_NAMESPACE1 = 'netspace1'
TEST_ISCSI_NAMESPACE2 = 'netspace2'
TEST_TARGET_PORTAL1 = '{}:{}'.format(TEST_IP_ADDRESS1, TEST_ISCSI_TCP_PORT1)
TEST_TARGET_PORTAL2 = '{}:{}'.format(TEST_IP_ADDRESS2, TEST_ISCSI_TCP_PORT1)
TEST_TARGET_PORTAL3 = '{}:{}'.format(TEST_IP_ADDRESS3, TEST_ISCSI_TCP_PORT2)
TEST_TARGET_PORTAL4 = '{}:{}'.format(TEST_IP_ADDRESS4, TEST_ISCSI_TCP_PORT2)
TEST_FC_PROTOCOL = 'fc'
TEST_ISCSI_PROTOCOL = 'iscsi'

test_volume = mock.Mock(id=1, _name_id=None, size=1, volume_type_id=1,
                        multiattach=False, volume_attachment=None)
test_volume2 = mock.Mock(id=2, _name_id=None, size=1, volume_type_id=1,
                         multiattach=False, volume_attachment=None)
test_snapshot = mock.Mock(id=2, volume=test_volume, volume_id='1')
test_clone = mock.Mock(id=3, size=1, multiattach=False,
                       volume_attachment=None)
test_group = mock.Mock(id=4)
test_snapgroup = mock.Mock(id=5, group=test_group)
test_connector1 = dict(wwpns=[TEST_WWN_1],
                       initiator=TEST_INITIATOR_IQN1)
test_connector2 = dict(wwpns=[TEST_WWN_2],
                       initiator=TEST_INITIATOR_IQN2)
test_attachment1 = mock.Mock(connector=test_connector1)
test_attachment2 = mock.Mock(connector=test_connector2)
test_attachment3 = mock.Mock(connector=None)


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
        self.ctxt = context.get_admin_context()
        # create mock configuration
        self.configuration = mock.Mock(spec=configuration.Configuration)
        self.configuration.infinidat_storage_protocol = TEST_FC_PROTOCOL
        self.configuration.san_ip = 'mockbox'
        self.configuration.infinidat_pool_name = 'mockpool'
        self.configuration.san_thin_provision = True
        self.configuration.san_login = 'user'
        self.configuration.san_password = 'pass'
        self.configuration.driver_use_ssl = True
        self.configuration.driver_ssl_cert_path = '/path/to/CA/bundle'
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
        self._log = self.patch("cinder.volume.drivers.infinidat.LOG")
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
        self._mock_new_volume = mock.Mock()
        self._mock_volume.get_size.return_value = 1 * units.Gi
        self._mock_volume.has_children.return_value = False
        self._mock_volume.get_logical_units.return_value = []
        self._mock_volume.create_snapshot.return_value = self._mock_volume
        self._mock_host = mock.Mock()
        self._mock_host.get_luns.return_value = []
        self._mock_host.map_volume().get_lun.return_value = TEST_LUN
        self._mock_pool = mock.Mock()
        self._mock_pool.get_free_physical_capacity.return_value = units.Gi
        self._mock_pool.get_physical_capacity.return_value = units.Gi
        self._mock_name_space1 = mock.Mock()
        self._mock_name_space2 = mock.Mock()
        self._mock_name_space1.get_ips.return_value = [
            mock.Mock(ip_address=TEST_IP_ADDRESS1, enabled=True)]
        self._mock_name_space2.get_ips.return_value = [
            mock.Mock(ip_address=TEST_IP_ADDRESS3, enabled=True)]
        self._mock_name_space1.get_properties.return_value = mock.Mock(
            iscsi_iqn=TEST_TARGET_IQN, iscsi_tcp_port=TEST_ISCSI_TCP_PORT1)
        self._mock_name_space2.get_properties.return_value = mock.Mock(
            iscsi_iqn=TEST_TARGET_IQN, iscsi_tcp_port=TEST_ISCSI_TCP_PORT2)
        self._mock_group = mock.Mock()
        self._mock_qos_policy = mock.Mock()
        result.volumes.safe_get.return_value = self._mock_volume
        result.volumes.create.return_value = self._mock_volume
        result.pools.safe_get.return_value = self._mock_pool
        result.hosts.safe_get.return_value = self._mock_host
        result.cons_groups.safe_get.return_value = self._mock_group
        result.cons_groups.create.return_value = self._mock_group
        result.hosts.create.return_value = self._mock_host
        result.network_spaces.safe_get.return_value = self._mock_name_space1
        result.components.nodes.get_all.return_value = []
        result.qos_policies.create.return_value = self._mock_qos_policy
        result.qos_policies.safe_get.return_value = None
        return result

    def _raise_infinisdk(self, *args, **kwargs):
        raise FakeInfinisdkException()


class InfiniboxDriverTestCase(InfiniboxDriverTestCaseBase):
    def _generate_mock_object_metadata(self, cinder_object):
        return {"system": "openstack",
                "openstack_version": version.version_info.release_string(),
                "cinder_id": cinder_object.id,
                "cinder_name": cinder_object.name,
                "host.created_by": infinidat._INFINIDAT_CINDER_IDENTIFIER}

    def _validate_object_metadata(self, infinidat_object, cinder_object):
        infinidat_object.set_metadata_from_dict.assert_called_once_with(
            self._generate_mock_object_metadata(cinder_object))

    def _generate_mock_host_metadata(self):
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
        result = self.driver.initialize_connection(test_volume,
                                                   test_connector1)
        self.assertEqual(1, result["data"]["target_lun"])

    def test_initialize_connection_host_exists(self):
        result = self.driver.initialize_connection(test_volume,
                                                   test_connector1)
        self.assertEqual(1, result["data"]["target_lun"])

    def test_initialize_connection_mapping_exists(self):
        mock_mapping = mock.Mock()
        mock_mapping.get_volume.return_value = self._mock_volume
        mock_mapping.get_lun.return_value = 888
        self._mock_host.get_luns.return_value = [mock_mapping]
        result = self.driver.initialize_connection(test_volume,
                                                   test_connector1)
        self.assertEqual(888, result["data"]["target_lun"])

    def test_initialize_connection_volume_doesnt_exist(self):
        self._system.volumes.safe_get.return_value = None
        self.assertRaises(exception.InvalidVolume,
                          self.driver.initialize_connection,
                          test_volume, test_connector1)

    def test_initialize_connection_create_fails(self):
        self._system.hosts.safe_get.return_value = None
        self._system.hosts.create.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          test_volume, test_connector1)

    def test_initialize_connection_map_fails(self):
        self._mock_host.map_volume.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.initialize_connection,
                          test_volume, test_connector1)

    def test_initialize_connection_metadata(self):
        self._system.hosts.safe_get.return_value = None
        self.driver.initialize_connection(test_volume, test_connector1)
        self._validate_host_metadata()

    def test_terminate_connection(self):
        self.driver.terminate_connection(test_volume, test_connector1)

    def test_terminate_connection_delete_host(self):
        self._mock_host.get_luns.return_value = [object()]
        self.driver.terminate_connection(test_volume, test_connector1)
        self.assertEqual(0, self._mock_host.safe_delete.call_count)
        self._mock_host.get_luns.return_value = []
        self.driver.terminate_connection(test_volume, test_connector1)
        self.assertEqual(1, self._mock_host.safe_delete.call_count)

    def test_terminate_connection_volume_doesnt_exist(self):
        self._system.volumes.safe_get.return_value = None
        self.assertRaises(exception.InvalidVolume,
                          self.driver.terminate_connection,
                          test_volume, test_connector1)

    def test_terminate_connection_api_fail(self):
        self._mock_host.unmap_volume.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.terminate_connection,
                          test_volume, test_connector1)

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
    @mock.patch("cinder.volume.volume_utils.brick_get_connector")
    @mock.patch("cinder.volume.volume_utils.brick_get_connector_properties",
                return_value=test_connector1)
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

    @mock.patch("cinder.volume.volume_utils.brick_get_connector_properties",
                return_value=test_connector1)
    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_create_volume_from_snapshot_map_fails(self, *mocks):
        self._mock_host.map_volume.side_effect = self._raise_infinisdk
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume_from_snapshot,
                          test_clone, test_snapshot)

    @mock.patch("cinder.volume.volume_utils.copy_volume")
    @mock.patch("cinder.volume.volume_utils.brick_get_connector")
    @mock.patch("cinder.volume.volume_utils.brick_get_connector_properties",
                return_value=test_connector1)
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
    @mock.patch("cinder.volume.volume_utils.brick_get_connector")
    @mock.patch("cinder.volume.volume_utils.brick_get_connector_properties",
                return_value=test_connector1)
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

    @mock.patch("cinder.volume.volume_utils.brick_get_connector_properties",
                return_value=test_connector1)
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
    @mock.patch("cinder.volume.volume_utils.brick_get_connector")
    @mock.patch("cinder.volume.volume_utils.brick_get_connector_properties",
                return_value=test_connector1)
    @mock.patch('cinder.volume.volume_utils.is_group_a_cg_snapshot_type',
                return_value=True)
    @mock.patch("cinder.volume.volume_types.get_volume_type_qos_specs")
    def test_create_group_from_src_snaps(self, *mocks):
        self.driver.create_group_from_src(None, test_group, [test_volume],
                                          test_snapgroup, [test_snapshot],
                                          None, None)

    @mock.patch("cinder.volume.volume_utils.copy_volume")
    @mock.patch("cinder.volume.volume_utils.brick_get_connector")
    @mock.patch("cinder.volume.volume_utils.brick_get_connector_properties",
                return_value=test_connector1)
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

    def test_terminate_connection_no_attachment_connector(self):
        test_volume.multiattach = True
        test_volume.volume_attachment = [test_attachment3]
        self.driver.terminate_connection(test_volume, test_connector1)

    def test_terminate_connection_no_host(self):
        self._system.hosts.safe_get.return_value = None
        self.driver.terminate_connection(test_volume, test_connector1)

    def test_terminate_connection_no_mapping(self):
        self._mock_host.unmap_volume.side_effect = KeyError
        self.driver.terminate_connection(test_volume, test_connector1)

    def test_update_migrated_volume_new_volume_not_found(self):
        self._system.volumes.safe_get.side_effect = [
            None, self._mock_volume]
        update = self.driver.update_migrated_volume(self.ctxt,
                                                    test_volume,
                                                    test_volume2,
                                                    'available')
        self.assertEqual(2, self._log.error.call_count)
        self.assertEqual({'_name_id': test_volume2.id}, update)

    def test_update_migrated_volume_volume_not_found(self):
        self._system.volumes.safe_get.side_effect = [
            self._mock_new_volume, None]
        update = self.driver.update_migrated_volume(self.ctxt,
                                                    test_volume,
                                                    test_volume2,
                                                    'available')
        self.assertEqual(1, self._log.error.call_count)
        self.assertEqual({'_name_id': None}, update)

    def test_update_migrated_volume_rename_error(self):
        self._system.volumes.safe_get.side_effect = [
            self._mock_new_volume, self._mock_volume]
        self._mock_volume.update_name.side_effect = [
            FakeInfinisdkException]
        update = self.driver.update_migrated_volume(self.ctxt,
                                                    test_volume,
                                                    test_volume2,
                                                    'available')
        self.assertEqual(1, self._log.error.call_count)
        self.assertEqual({'_name_id': test_volume2.id}, update)

    def test_update_migrated_new_volume_rename_error(self):
        self._system.volumes.safe_get.side_effect = [
            self._mock_new_volume, self._mock_volume]
        self._mock_volume.update_name.side_effect = [
            None]
        self._mock_new_volume.update_name.side_effect = [
            FakeInfinisdkException]
        update = self.driver.update_migrated_volume(self.ctxt,
                                                    test_volume,
                                                    test_volume2,
                                                    'available')
        self.assertEqual(1, self._log.error.call_count)
        self.assertEqual({'_name_id': test_volume2.id}, update)

    def test_update_migrated_volume_restore_error(self):
        self._system.volumes.safe_get.side_effect = [
            self._mock_new_volume, self._mock_volume]
        self._mock_volume.update_name.side_effect = [
            None, FakeInfinisdkException]
        self._mock_new_volume.update_name.side_effect = [
            None]
        update = self.driver.update_migrated_volume(self.ctxt,
                                                    test_volume,
                                                    test_volume2,
                                                    'available')
        self.assertEqual(1, self._log.error.call_count)
        self.assertEqual({'_name_id': None}, update)

    def test_update_migrated(self):
        self._system.volumes.safe_get.side_effect = [
            self._mock_new_volume, self._mock_volume]
        self._mock_volume.update_name.side_effect = [
            None, None]
        self._mock_new_volume.update_name.side_effect = [
            None]
        update = self.driver.update_migrated_volume(self.ctxt,
                                                    test_volume,
                                                    test_volume2,
                                                    'available')
        self.assertEqual(0, self._log.error.call_count)
        self.assertEqual({'_name_id': None}, update)

    def test_snapshot_revert_use_temp_snapshot(self):
        result = self.driver.snapshot_revert_use_temp_snapshot()
        self.assertFalse(result)

    def test_revert_to_snapshot(self):
        self._mock_volume.restore.side_effect = None
        self.driver.revert_to_snapshot(self.ctxt, test_volume, test_snapshot)

    def test_revert_to_snapshot_resize(self):
        test_snapshot.volume.size = 2
        self.driver.revert_to_snapshot(self.ctxt, test_volume, test_snapshot)
        self._mock_volume.resize.assert_called_with(units.Gi)


class InfiniboxDriverTestCaseFC(InfiniboxDriverTestCaseBase):
    def test_initialize_connection_multiple_wwpns(self):
        connector = {'wwpns': [TEST_WWN_1, TEST_WWN_2]}
        result = self.driver.initialize_connection(test_volume, connector)
        self.assertEqual(1, result["data"]["target_lun"])

    def test_validate_connector(self):
        fc_connector = {'wwpns': [TEST_WWN_1, TEST_WWN_2]}
        iscsi_connector = {'initiator': TEST_INITIATOR_IQN1}
        self.driver.validate_connector(fc_connector)
        self.assertRaises(exception.InvalidConnectorException,
                          self.driver.validate_connector, iscsi_connector)

    def test_terminate_connection_multiattached_volume(self):
        test_volume.multiattach = True
        test_volume.volume_attachment = [test_attachment1,
                                         test_attachment1]
        self.driver.terminate_connection(test_volume, test_connector1)


class InfiniboxDriverTestCaseISCSI(InfiniboxDriverTestCaseBase):
    def setUp(self):
        super(InfiniboxDriverTestCaseISCSI, self).setUp()
        self.configuration.infinidat_storage_protocol = TEST_ISCSI_PROTOCOL
        self.configuration.infinidat_iscsi_netspaces = [TEST_ISCSI_NAMESPACE1]
        self.configuration.use_chap_auth = False
        self.driver.do_setup(None)

    def test_setup_without_netspaces_configured(self):
        self.configuration.infinidat_iscsi_netspaces = []
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.do_setup, None)

    def test_initialize_connection(self):
        result = self.driver.initialize_connection(test_volume,
                                                   test_connector1)
        expected = {
            'driver_volume_type': TEST_ISCSI_PROTOCOL,
            'data': {
                'target_discovered': True,
                'target_portal': TEST_TARGET_PORTAL1,
                'target_iqn': TEST_TARGET_IQN,
                'target_lun': TEST_LUN,
                'target_portals': [
                    TEST_TARGET_PORTAL1
                ],
                'target_iqns': [
                    TEST_TARGET_IQN
                ],
                'target_luns': [
                    TEST_LUN
                ]
            }
        }
        self.assertEqual(expected, result)

    def test_initialize_netspace_does_not_exist(self):
        self._system.network_spaces.safe_get.return_value = None
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.initialize_connection,
                          test_volume, test_connector1)

    def test_initialize_netspace_has_no_ips(self):
        self._mock_name_space1.get_ips.return_value = []
        self.assertRaises(exception.VolumeDriverException,
                          self.driver.initialize_connection,
                          test_volume, test_connector1)

    def test_initialize_connection_with_chap(self):
        self.configuration.use_chap_auth = True
        result = self.driver.initialize_connection(test_volume,
                                                   test_connector1)
        self.assertEqual(1, result['data']['target_lun'])
        self.assertEqual('CHAP', result['data']['auth_method'])
        self.assertIn('auth_username', result['data'])
        self.assertIn('auth_password', result['data'])

    def test_initialize_connection_multiple_netspaces(self):
        self.configuration.infinidat_iscsi_netspaces = [
            TEST_ISCSI_NAMESPACE1, TEST_ISCSI_NAMESPACE2]
        self._system.network_spaces.safe_get.side_effect = [
            self._mock_name_space1, self._mock_name_space2]
        result = self.driver.initialize_connection(test_volume,
                                                   test_connector1)
        expected = {
            'driver_volume_type': TEST_ISCSI_PROTOCOL,
            'data': {
                'target_discovered': True,
                'target_portal': TEST_TARGET_PORTAL1,
                'target_iqn': TEST_TARGET_IQN,
                'target_lun': TEST_LUN,
                'target_portals': [
                    TEST_TARGET_PORTAL1,
                    TEST_TARGET_PORTAL3
                ],
                'target_iqns': [
                    TEST_TARGET_IQN,
                    TEST_TARGET_IQN
                ],
                'target_luns': [
                    TEST_LUN,
                    TEST_LUN
                ]
            }
        }
        self.assertEqual(expected, result)

    def test_initialize_connection_multiple_netspaces_multipath(self):
        self.configuration.infinidat_iscsi_netspaces = [
            TEST_ISCSI_NAMESPACE1, TEST_ISCSI_NAMESPACE2]
        self._system.network_spaces.safe_get.side_effect = [
            self._mock_name_space1, self._mock_name_space2]
        self._mock_name_space1.get_ips.return_value = [
            mock.Mock(ip_address=TEST_IP_ADDRESS1, enabled=True),
            mock.Mock(ip_address=TEST_IP_ADDRESS2, enabled=True)]
        self._mock_name_space2.get_ips.return_value = [
            mock.Mock(ip_address=TEST_IP_ADDRESS3, enabled=True),
            mock.Mock(ip_address=TEST_IP_ADDRESS4, enabled=True)]
        result = self.driver.initialize_connection(test_volume,
                                                   test_connector1)
        expected = {
            'driver_volume_type': TEST_ISCSI_PROTOCOL,
            'data': {
                'target_discovered': True,
                'target_portal': TEST_TARGET_PORTAL1,
                'target_iqn': TEST_TARGET_IQN,
                'target_lun': TEST_LUN,
                'target_portals': [
                    TEST_TARGET_PORTAL1,
                    TEST_TARGET_PORTAL2,
                    TEST_TARGET_PORTAL3,
                    TEST_TARGET_PORTAL4
                ],
                'target_iqns': [
                    TEST_TARGET_IQN,
                    TEST_TARGET_IQN,
                    TEST_TARGET_IQN,
                    TEST_TARGET_IQN
                ],
                'target_luns': [
                    TEST_LUN,
                    TEST_LUN,
                    TEST_LUN,
                    TEST_LUN
                ]
            }
        }
        self.assertEqual(expected, result)

    def test_initialize_connection_disabled_interface(self):
        self._mock_name_space1.get_ips.return_value = [
            mock.Mock(ip_address=TEST_IP_ADDRESS1, enabled=False),
            mock.Mock(ip_address=TEST_IP_ADDRESS2, enabled=True)]
        result = self.driver.initialize_connection(test_volume,
                                                   test_connector1)
        expected = {
            'driver_volume_type': TEST_ISCSI_PROTOCOL,
            'data': {
                'target_discovered': True,
                'target_portal': TEST_TARGET_PORTAL2,
                'target_iqn': TEST_TARGET_IQN,
                'target_lun': TEST_LUN,
                'target_portals': [
                    TEST_TARGET_PORTAL2
                ],
                'target_iqns': [
                    TEST_TARGET_IQN
                ],
                'target_luns': [
                    TEST_LUN
                ]
            }
        }
        self.assertEqual(expected, result)

    def test_initialize_connection_multiple_interfaces(self):
        self._mock_name_space1.get_ips.return_value = [
            mock.Mock(ip_address=TEST_IP_ADDRESS1, enabled=True),
            mock.Mock(ip_address=TEST_IP_ADDRESS2, enabled=True)]
        self._mock_name_space1.get_properties.return_value = mock.Mock(
            iscsi_iqn=TEST_TARGET_IQN, iscsi_tcp_port=TEST_ISCSI_TCP_PORT1)
        result = self.driver.initialize_connection(test_volume,
                                                   test_connector1)
        expected = {
            'driver_volume_type': TEST_ISCSI_PROTOCOL,
            'data': {
                'target_discovered': True,
                'target_portal': TEST_TARGET_PORTAL1,
                'target_iqn': TEST_TARGET_IQN,
                'target_lun': TEST_LUN,
                'target_portals': [
                    TEST_TARGET_PORTAL1,
                    TEST_TARGET_PORTAL2
                ],
                'target_iqns': [
                    TEST_TARGET_IQN,
                    TEST_TARGET_IQN
                ],
                'target_luns': [
                    TEST_LUN,
                    TEST_LUN
                ]
            }
        }
        self.assertEqual(expected, result)

    def test_terminate_connection(self):
        self.driver.terminate_connection(test_volume, test_connector1)

    def test_validate_connector(self):
        fc_connector = {'wwpns': [TEST_WWN_1, TEST_WWN_2]}
        iscsi_connector = {'initiator': TEST_INITIATOR_IQN1}
        self.driver.validate_connector(iscsi_connector)
        self.assertRaises(exception.InvalidConnectorException,
                          self.driver.validate_connector, fc_connector)

    def test_terminate_connection_multiattached_volume(self):
        test_volume.multiattach = True
        test_volume.volume_attachment = [test_attachment2, test_attachment2]
        self.driver.terminate_connection(test_volume, test_connector2)


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
