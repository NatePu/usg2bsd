#!/bin/sh
# Small-packet generator (STOCK_TEST_PLAN.md section 8, netsniff-ng trafgen).
#   sh bench/hosts/trafgen.sh A|B FRAME STREAMS RATE NUM [VID]
# FRAME is the Ethernet frame including FCS (64 ... 1518); STREAMS is 1 or 8
# (source ports 10000-10007); RATE as trafgen takes it (e.g. 100kpps); VID
# injects an 802.1Q tag directly on the parent (topology V). The DUT's
# ingress MAC comes from the neighbour table, so ping the gateway first.
# Validate with NUM=1000 and the receive sink before measuring.
set -eu
. "$(dirname "$0")/../env.sh"
WHO=${1:?A or B}
FRAME=${2:?frame size including FCS}
STREAMS=${3:?1 or 8}
RATE=${4:?rate, e.g. 100kpps}
NUM=${5:?packet count}
VID=${6:-}
if [ "$WHO" = A ]; then SRC=$TEST_A DST=$TEST_B GW=$DUT_A
else SRC=$TEST_B DST=$TEST_A GW=$DUT_B; fi
IF=$HOST_IF
[ -n "$VID" ] && [ "$VID" != 0 ] || VID=
MAC=$(ip neigh show "$GW" | awk '{ for (i = 1; i < NF; i++) if ($i == "lladdr") print $(i + 1) }' | head -1)
[ -n "$MAC" ] || { echo "no neighbour entry for $GW: ping it first" >&2; exit 1; }
# 14-byte Ethernet header (+4 tag), 20 IPv4, 8 UDP, 4 FCS added by the NIC:
# payload = frame - 46 untagged, frame - 50 tagged (STOCK_TEST_PLAN.md 8)
TAG=0
[ -n "$VID" ] && TAG=4
PAYLOAD=$((FRAME - 46 - TAG))
[ "$PAYLOAD" -ge 0 ] || { echo "frame too small" >&2; exit 1; }
CFG=$(mktemp /tmp/trafgen.XXXXXX)
i=0
while [ $i -lt "$STREAMS" ]; do
	{
		echo "{"
		echo "  eth(da=$MAC),"
		[ -n "$VID" ] && echo "  vlan(id=$VID),"
		echo "  ipv4(sa=$SRC, da=$DST, ttl=64),"
		echo "  udp(sp=$((10000 + i)), dp=9000),"
		echo "  fill(0x42, $PAYLOAD)"
		echo "}"
	} >> "$CFG"
	i=$((i + 1))
done
echo "trafgen: $WHO frame $FRAME payload $PAYLOAD streams $STREAMS rate $RATE num $NUM vid ${VID:-none} da $MAC"
trafgen --dev "$IF" --conf "$CFG" --cpus 1 --rate "$RATE" --num "$NUM"
rm -f "$CFG"
