# ospfd.conf for bench topology F (STOCK_TEST_PLAN.md section 9; F: ERRATA E87).
# Check with: ospfd -n -f bench/dut/ospfd.conf.F
router-id 192.0.2.1
area 0.0.0.0 {
	interface cnmac1
	interface cnmac2
	interface vlan21
}
