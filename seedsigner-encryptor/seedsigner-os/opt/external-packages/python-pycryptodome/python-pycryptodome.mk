################################################################################
#
# python-pycryptodome
#
################################################################################

# The "Crypto" namespace build (Buildroot only packages pycryptodomex, which
# installs as "Cryptodome"). The message crypto code imports Crypto.
PYTHON_PYCRYPTODOME_VERSION = 4.2.0
PYTHON_PYCRYPTODOME_SOURCE = pycryptodome-$(PYTHON_PYCRYPTODOME_VERSION).tar.gz
PYTHON_PYCRYPTODOME_SITE = https://files.pythonhosted.org/packages/33/c7/f9374c8939560ab22db1dd9dbe215b62d20f32634aeb7f259dc03c807b44
PYTHON_PYCRYPTODOME_SETUP_TYPE = setuptools
PYTHON_PYCRYPTODOME_LICENSE = \
	BSD-2-Clause, \
	Public Domain (pycrypto original code), \
	Apache-2.0 or ISC or MIT (mldsa-native, mlkem-native)
PYTHON_PYCRYPTODOME_LICENSE_FILES = LICENSE.rst Doc/LEGAL/COPYRIGHT.pycrypto

# PYCRYPTODOME_NO_SELFTEST leaves Crypto.SelfTest out of the image.
PYTHON_PYCRYPTODOME_ENV = \
	CFLAGS="$(TARGET_CFLAGS) -std=c99" \
	PYCRYPTODOME_NO_SELFTEST=1

$(eval $(python-package))
