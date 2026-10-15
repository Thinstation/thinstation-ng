#!/bin/sh
set -eu
# Called inside the assembled image after its native dependencies are collected.
root=/usr/lib64/mcp-fallback
rm -f "$root/qualification.json"
/usr/bin/mcp-selftest qualify "$root" --output "$root/qualification.json"
chmod 0444 "$root/qualification.json"
