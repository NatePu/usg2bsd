# Bench address plan, sourced by every bench script (T0.3).
# Source of truth: STOCK_TEST_PLAN.md section 2, plus topology F (ERRATA E87).
#
#   U  untagged:   A enp1s0 -- cnmac1 [DUT] cnmac2 -- enp1s0 B
#   V  tagged:     A enp1s0.10 -- vlan10/cnmac1 [DUT] vlan20/cnmac2 -- enp1s0.20 B
#   H  one trunk:  A (switch access VLAN 10) -+- trunk 10,20 -- cnmac1 [DUT]
#                  B (switch access VLAN 20) -+   (vlan10 and vlan20 on cnmac1)
#   F  failover:   U plus B enp1s0.21 -- vlan21/cnmac2, a second OSPF path to B
#
# cnmac0 is management/TFTP only. Override any value in the environment.

: ${DUT_A_PORT:=cnmac1}		# DUT port facing A (and the H trunk)
: ${DUT_B_PORT:=cnmac2}		# DUT port facing B
: ${HOST_IF:=enp1s0}		# Linux endpoint NIC on A and B
: ${VID_A:=10}
: ${VID_B:=20}
: ${VID_B2:=21}			# topology F only

: ${DUT_A:=10.250.1.1}		# /30 transits
: ${HOST_A:=10.250.1.2}
: ${DUT_B:=10.250.2.1}
: ${HOST_B:=10.250.2.2}
: ${DUT_B2:=10.250.3.1}
: ${HOST_B2:=10.250.3.2}
: ${MASK:=255.255.255.252}

: ${TEST_A:=198.18.0.1}		# test addresses on the hosts' loopbacks
: ${TEST_B:=198.19.0.1}
: ${RID_DUT:=192.0.2.1}		# OSPF router IDs
: ${RID_A:=198.18.0.1}
: ${RID_B:=198.19.0.1}

: ${RESULTS:=./results}		# where every script writes its output

# logical DUT interfaces for a topology: dut_ifs TOPO -> "IF_A IF_B [IF_B2]"
dut_ifs() {
	case $1 in
	U)	echo "$DUT_A_PORT $DUT_B_PORT" ;;
	V|H)	echo "vlan$VID_A vlan$VID_B" ;;
	F)	echo "$DUT_A_PORT $DUT_B_PORT vlan$VID_B2" ;;
	*)	echo "unknown topology $1 (U, V, H or F)" >&2; return 1 ;;
	esac
}
