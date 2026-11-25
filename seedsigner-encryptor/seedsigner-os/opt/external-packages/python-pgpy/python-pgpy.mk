################################################################################
#
# python-pgpy
#
################################################################################

PYTHON_PGPY_VERSION = 0.6.0
PYTHON_PGPY_SOURCE = PGPy-$(PYTHON_PGPY_VERSION).tar.gz
PYTHON_PGPY_SITE = https://files.pythonhosted.org/packages/f8/68/5e285ba9465550a48e837b08b27fa99ef238618f6085a1464afaa4dc8426
PYTHON_PGPY_SETUP_TYPE = setuptools
PYTHON_PGPY_LICENSE = BSD-3-Clause
PYTHON_PGPY_LICENSE_FILES = LICENSE

$(eval $(python-package))
