# ospfd.conf for bench topology H (STOCK_TEST_PLAN.md section 9; F: ERRATA E87).
# Check with: ospfd -n -f bench/dut/ospfd.conf.H
router-id 192.0.2.1
area 0.0.0.0 {
	interface vlan10
	interface vlan20
}
