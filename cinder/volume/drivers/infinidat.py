from cinder.volume import driver

# INFINIDAT InfiniBox Volume Driver
#
# This base driver uses an external python package
#
# For installation instructions, see https://support.infinidat.com/hc/en-us/articles/202403971
# For configuration instructions, see https://support.infinidat.com/hc/en-us/articles/202403961
# For the complete user guide, see https://support.infinidat.com/hc/en-us/sections/200831822


MINIMAL_VERSION = '2.3.2'


try:
    from infinidat_openstack.__version__ import __version__
    from infinidat_openstack.cinder.volume import InfiniboxVolumeDriver
    from pkg_resources import parse_version
    assert parse_version(__version__) >= parse_version(MINIMAL_VERSION)
except:
    from cinder.volume.driver import VolumeDriver
    InfiniboxVolumeDriver = VolumeDriver


__all__ = ['InfiniboxVolumeDriver']
