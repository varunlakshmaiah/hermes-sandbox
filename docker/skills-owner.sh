#!/bin/sh
# Runs as root before upstream setup: a fresh hermes_skills volume mounted below
# /opt/data starts root-owned, and upstream only fixes it when /opt/data needs fixing.
set -eu
if [ "$(stat -c %u:%g /opt/data/skills)" != 10000:10000 ]; then
	chown 10000:10000 /opt/data/skills
fi
