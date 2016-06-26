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
#
#
# INFINIDAT InfiniBox Volume Driver
#
# This base driver uses an external python package
#
# For installation instructions, see
#     https://support.infinidat.com/hc/en-us/articles/202403971
# For configuration instructions, see
#     https://support.infinidat.com/hc/en-us/articles/202403961
# For the complete user guide, see
#     https://support.infinidat.com/hc/en-us/sections/200831822


from cinder import interface
from cinder.volume import driver
from oslo_utils import importutils


try:
    # try to import the external library on the module level to register the
    # external driver configuration
    # (the external driver calls oslo config's cfg.CONF.register_opts).
    # the actual import of the external driver class is in the driver's
    # constructor below.
    import infinidat_openstack.cinder.volume  # noqa
except ImportError:
    pass


@interface.volumedriver
class InfiniboxVolumeDriver(driver.VolumeDriver):
    def __init__(self, *args, **kwargs):
        """Initialize the driver."""
        super(InfiniboxVolumeDriver, self).__init__(*args, **kwargs)

        class_name = "infinidat_openstack.cinder.volume.InfiniboxVolumeDriver"
        proxy_class = importutils.import_class(class_name)

        self.infinibox_proxy = proxy_class(*args, **kwargs)

    def do_setup(self, context):
        """Setup connection to the storage array."""
        return self.infinibox_proxy.do_setup(context)

    def ensure_export(self, context, volume):
        """Synchronously recreates an export for a logical volume."""
        return self.infinibox_proxy.ensure_export(context, volume)

    def create_export(self, context, volume, connector=None):
        """Exports the volume."""
        return self.infinibox_proxy.create_export(context, volume, connector)

    def remove_export(self, context, volume):
        """Removes an export for a logical volume."""
        return self.infinibox_proxy.remove_export(context, volume)

    def check_for_setup_error(self):
        """Returns an error if prerequisites aren't met."""
        return self.infinibox_proxy.check_for_setup_error()

    def create_volume(self, volume):
        """Create a new volume on the backend."""
        return self.infinibox_proxy.create_volume(volume)

    def delete_volume(self, volume):
        """Delete a volume from the backend."""
        return self.infinibox_proxy.delete_volume(volume)

    def initialize_connection(self, volume, connector, initiator_data=None):
        """Map a volume to the host"""
        return self.infinibox_proxy.initialize_connection(
            volume,
            connector,
            initiator_data)

    def terminate_connection(self, volume, connector, force=False, **kwargs):
        """Remove access to a volume."""
        return self.infinibox_proxy.terminate_connection(
            volume, connector, force, **kwargs)

    def create_volume_from_snapshot(self, volume, cinder_snapshot):
        """Creates a volume from a snapshot."""
        return self.infinibox_proxy.create_volume_from_snapshot(
            volume, cinder_snapshot)

    def create_cloned_volume(self, tgt_volume, src_volume):
        """Creates a clone of the specified volume."""
        return self.infinibox_proxy.create_cloned_volume(
            tgt_volume, src_volume)

    def extend_volume(self, volume, new_size):
        """Extend the size of a volume."""
        return self.infinibox_proxy.extend_volume(volume, new_size)

    def migrate_volume(self, context, volume, host):
        """Migrate the volume to the specified host."""
        return self.infinibox_proxy.migrate_volume(context, volume, host)

    def create_snapshot(self, cinder_snapshot):
        """Creates a snapshot."""
        return self.infinibox_proxy.create_snapshot(cinder_snapshot)

    def delete_snapshot(self, cinder_snapshot):
        """Deletes a snapshot."""
        return self.infinibox_proxy.delete_snapshot(cinder_snapshot)

    def get_volume_stats(self, refresh=False):
        """Collects volume backend stats."""
        return self.infinibox_proxy.get_volume_stats(refresh)

    def create_consistencygroup(self, context, cinder_cg):
        """Creates a consistency group."""
        return self.infinibox_proxy.create_consistencygroup(context, cinder_cg)

    def delete_consistencygroup(self, context, cinder_cg, members=None):
        """Deletes a consistency group."""
        return self.infinibox_proxy.delete_consistencygroup(
            context, cinder_cg, members)

    def update_consistencygroup(self, context, cinder_cg,
                                add_volumes=None, remove_volumes=None):
        """Updates a consistency group."""
        return self.infinibox_proxy.update_consistencygroup(
            context, cinder_cg, add_volumes, remove_volumes)

    def create_cgsnapshot(self, context, cgsnapshot):
        """Creates a consisteny group snapshot."""
        return self.infinibox_proxy.create_cgsnapshot(context, cgsnapshot)

    def delete_cgsnapshot(self, context, cgsnapshot, members=None):
        """Deletes a consisteny group snapshot."""
        return self.infinibox_proxy.delete_cgsnapshot(
            context, cgsnapshot, members)
