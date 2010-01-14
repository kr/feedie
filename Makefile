
VERSION := $(shell ./version.sh)

all: help

help:
	@echo make package -- generate a deb file
	@echo make help    -- this message

package:
	#dpkg-buildpackage -tc -I.git -us -uc
	git-buildpackage -us -uc --git-ignore-new
