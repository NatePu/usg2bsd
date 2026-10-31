/*
 * Stubs and test driver for running sys/net/if_flow.c on a macOS arm64
 * host (tests/flowtable/build.sh).  Compiled as kernel code against the
 * fork's headers; the few libc functions it needs are declared by hand
 * under asm labels so they cannot clash with kernel prototypes.
 *
 * The kernel services here are single-threaded models: mutexes and
 * rwlocks only count, SMR readers never overlap a barrier, and SMR
 * callbacks run at smr_barrier().  The harness therefore checks the table
 * and sysctl logic, not concurrency.
 */

#include "flow.h"

#include <sys/param.h>
#include <sys/systm.h>
#include <sys/mutex.h>
#include <sys/rwlock.h>
#include <sys/pool.h>
#include <sys/smr.h>
#include <sys/percpu.h>
#include <sys/task.h>
#include <sys/timeout.h>
#include <sys/socket.h>
#include <sys/sysctl.h>
#include <sys/stdarg.h>
#include <sys/mbuf.h>

#include <net/if.h>
#include <net/if_var.h>

#include <netinet/in.h>
#include <netinet/if_ether.h>

#include <net/if_flow.h>
#include <net/if_flowvar.h>

void	*libc_calloc(unsigned long, unsigned long) __asm("_calloc");
void	 libc_free(void *) __asm("_free");
int	 libc_posix_memalign(void **, unsigned long, unsigned long)
	    __asm("_posix_memalign");
long	 libc_write(int, const void *, unsigned long) __asm("_write");
int	 libc_vsnprintf(char *, unsigned long, const char *, va_list)
	    __asm("_vsnprintf");
void	 libc_exit(int) __asm("_exit") __attribute__((__noreturn__));
void	 libc_abort(void) __asm("_abort") __attribute__((__noreturn__));
char	*libc_strstr(const char *, const char *) __asm("_strstr");

/* ---- output -------------------------------------------------------- */

static char	 out_buf[8192];
static size_t	 out_len;

int
printf(const char *fmt, ...)
{
	char buf[512];
	va_list ap;
	int n;

	va_start(ap, fmt);
	n = libc_vsnprintf(buf, sizeof(buf), fmt, ap);
	va_end(ap);
	if (n > (int)sizeof(buf) - 1)
		n = sizeof(buf) - 1;
	libc_write(1, buf, n);
	if (out_len + n < sizeof(out_buf)) {
		memcpy(out_buf + out_len, buf, n);
		out_len += n;
		out_buf[out_len] = '\0';
	}
	return (n);
}

void
panic(const char *fmt, ...)
{
	char buf[512];
	va_list ap;
	int n;

	va_start(ap, fmt);
	n = libc_vsnprintf(buf, sizeof(buf), fmt, ap);
	va_end(ap);
	libc_write(2, "panic: ", 7);
	libc_write(2, buf, n);
	libc_write(2, "\n", 1);
	libc_abort();
}

void
explicit_bzero(void *b, size_t len)
{
	volatile char *p = b;

	while (len--)
		*p++ = 0;
}

/* ---- locks: single-threaded, so only depth counting -------------------- */

static int	 mtx_depth;

void
mtx_enter(struct mutex *mtx)
{
	mtx_depth++;
}

void
mtx_leave(struct mutex *mtx)
{
	if (--mtx_depth < 0)
		panic("mtx_leave without mtx_enter");
}

void
rw_enter_write(struct rwlock *rwl)
{
}

void
rw_exit_write(struct rwlock *rwl)
{
}

/* ---- SMR: callbacks run at the barrier ----------------------------------- */

static int		 smr_depth;
static struct smr_entry	*smr_pending;

void
smr_read_enter(void)
{
	smr_depth++;
}

void
smr_read_leave(void)
{
	if (--smr_depth < 0)
		panic("smr_read_leave without smr_read_enter");
}

void
smr_call_impl(struct smr_entry *smr, void (*fn)(void *), void *arg,
    int expedite)
{
	smr->smr_func = fn;
	smr->smr_arg = arg;
	SIMPLEQ_NEXT(smr, smr_list) = smr_pending;
	smr_pending = smr;
}

static unsigned int	 smr_freed;

void
smr_barrier_impl(int expedite)
{
	struct smr_entry *smr;

	if (smr_depth != 0)
		panic("smr_barrier inside a read section");
	while ((smr = smr_pending) != NULL) {
		smr_pending = SIMPLEQ_NEXT(smr, smr_list);
		smr->smr_func(smr->smr_arg);
		smr_freed++;
	}
}

/* ---- pool, counters, taskq, timeout ------------------------------------- */

static size_t		 pool_size;
static unsigned int	 pool_out;

void
pool_init(struct pool *pp, size_t size, u_int align, int ipl, int flags,
    const char *wchan, struct pool_allocator *palloc)
{
	pool_size = size;
}

void *
pool_get(struct pool *pp, int flags)
{
	void *p;

	if (libc_posix_memalign(&p, CACHELINESIZE, pool_size) != 0)
		return (NULL);
	if (flags & PR_ZERO)
		memset(p, 0, pool_size);
	pool_out++;
	return (p);
}

void
pool_put(struct pool *pp, void *p)
{
	pool_out--;
	libc_free(p);
}

struct cpumem *
counters_alloc(unsigned int n)
{
	return (libc_calloc(n + 1, sizeof(uint64_t)));
}

struct taskq *
taskq_create(const char *name, unsigned int nthreads, int ipl,
    unsigned int flags)
{
	static int dummy;

	return ((struct taskq *)&dummy);
}

void
taskq_del_barrier(struct taskq *tq, struct task *t)
{
}

void
task_set(struct task *t, void (*fn)(void *), void *arg)
{
}

void
timeout_set_flags(struct timeout *to, void (*fn)(void *), void *arg,
    int kclock, int flags)
{
}

int
timeout_add_sec(struct timeout *to, int secs)
{
	return (1);
}

int
timeout_del_barrier(struct timeout *to)
{
	return (0);
}

/* sysctl_int_bounded() as kern_sysctl.c has it, with memcpy for copyin/out */
int
sysctl_int_bounded(void *oldp, size_t *oldlenp, void *newp, size_t newlen,
    int *valp, int minimum, int maximum)
{
	int oldval, newval;

	if (newp != NULL && minimum > maximum)
		return (EPERM);
	if (oldp != NULL && *oldlenp < sizeof(int))
		return (ENOMEM);
	if (newp != NULL && newlen != sizeof(int))
		return (EINVAL);
	*oldlenp = sizeof(int);
	if (newp != NULL) {
		memcpy(&newval, newp, sizeof(int));
		if (newval < minimum || maximum < newval)
			return (EINVAL);
	}
	oldval = *valp;
	if (newp != NULL)
		*valp = newval;
	if (oldp != NULL)
		memcpy(oldp, &oldval, sizeof(int));
	return (0);
}

int	 ip_forwarding;		/* netinet/ip_input.c */
extern u_int flow_learn_gate;

/* ---- fake MD operations ---------------------------------------------- */

static int	 md_rx_barriers;
static u_int	 md_mode = 99, md_budget, md_yield;

static int
md_port(struct ifnet *ifp)
{
	return (-1);
}

static void *
md_handle(struct ifnet *ifp)
{
	return (NULL);
}

static void
md_rx_barrier(void)
{
	md_rx_barriers++;
}

static void
md_sched_set(u_int mode, u_int budget, u_int yield)
{
	md_mode = mode;
	md_budget = budget;
	md_yield = yield;
}

static u_int
md_yield_round(u_int usec)
{
	return ((usec + 4) / 5 * 5);		/* a 5 usec granularity */
}

static const struct flow_md_ops md_ops = {
	md_port, md_handle, md_rx_barrier, md_sched_set, md_yield_round
};

/* ---- test driver ---------------------------------------------------- */

static int	 checks, failures;

static void
check(int ok, const char *what)
{
	checks++;
	if (!ok) {
		failures++;
		printf("FAIL %s\n", what);
	}
}

static int
get(int knob)
{
	int name[1] = { knob }, val = -12345;
	size_t len = sizeof(val);

	if (flow_sysctl(name, 1, &val, &len, NULL, 0) != 0)
		return (-12345);
	return (val);
}

static int
set(int knob, int val)
{
	int name[1] = { knob };
	size_t len = sizeof(val);

	return (flow_sysctl(name, 1, NULL, &len, &val, sizeof(val)));
}

static struct flow *
add_flow(u_int i)
{
	struct flow *f = flow_alloc();

	f->f_key.fk_port = 1;
	f->f_key.fk_src = htonl(0xc0a80000 | i);
	f->f_key.fk_dst = htonl(0xc0a90000 | i);
	f->f_gen = flow_gen;
	mtx_enter(&flow_mtx);
	check(flow_table_add(f) == FLOW_ADD_OK, "add_flow");
	mtx_leave(&flow_mtx);
	return (f);
}

static int
present(u_int i)
{
	struct flow_key k;
	struct flow *f;

	memset(&k, 0, sizeof(k));
	k.fk_port = 1;
	k.fk_src = htonl(0xc0a80000 | i);
	k.fk_dst = htonl(0xc0a90000 | i);
	smr_read_enter();
	f = flow_lookup(&k);
	smr_read_leave();
	return (f != NULL);
}

int	main(void);

int
main(void)
{
	static const int bad[][2] = {
		{ FLOWCTL_MODE, -1 }, { FLOWCTL_MODE, 4 },
		{ FLOWCTL_MAX, 0 }, { FLOWCTL_MAX, 4097 },
		{ FLOWCTL_IDLE, 0 }, { FLOWCTL_IDLE, 3601 },
		{ FLOWCTL_BUDGET, -1 }, { FLOWCTL_BUDGET, 4097 },
		{ FLOWCTL_YIELD, -1 }, { FLOWCTL_YIELD, 100001 },
		{ FLOWCTL_DEBUG, -1 }, { FLOWCTL_DEBUG, 2 },
	};
	u_int g, i;
	int k, before;

	/* T1.0/T1.2: attach runs the table self-test */
	flowattach(1);
	check(libc_strstr(out_buf, "table self-test passed") != NULL,
	    "boot self-test passed");
	smr_barrier();
	check(pool_out == 0, "self-test returned every flow to the pool");

	/* T1.1: defaults and bounds (SPEC 6.1, ERRATA E82) */
	check(get(FLOWCTL_MODE) == 0 && get(FLOWCTL_MAX) == 4096 &&
	    get(FLOWCTL_IDLE) == 30 && get(FLOWCTL_BUDGET) == 64 &&
	    get(FLOWCTL_YIELD) == 0 && get(FLOWCTL_DEBUG) == 0, "defaults");
	for (k = 0; k < (int)nitems(bad); k++) {
		before = get(bad[k][0]);
		check(set(bad[k][0], bad[k][1]) == EINVAL &&
		    get(bad[k][0]) == before, "out-of-range value refused");
	}
	check(set(FLOWCTL_MAX, 1) == 0 && get(FLOWCTL_MAX) == 1 &&
	    set(FLOWCTL_MAX, 4096) == 0, "max in range while off");
	check(set(FLOWCTL_IDLE, 3600) == 0 && set(FLOWCTL_IDLE, 30) == 0,
	    "idle in range");
	check(set(FLOWCTL_DEBUG, 1) == 0 && set(FLOWCTL_DEBUG, 0) == 0,
	    "debug in range");
	check(get(99) == -12345, "unknown name refused");

	/* mode 2 is refused before anything changes */
	g = flow_gen;
	check(set(FLOWCTL_MODE, 2) == EOPNOTSUPP && get(FLOWCTL_MODE) == 0 &&
	    flow_gen == g, "mode 2 refused in mode 0");

	/* without MD ops: budget/yield stored as given */
	check(set(FLOWCTL_YIELD, 7) == 0 && get(FLOWCTL_YIELD) == 7,
	    "yield stored as given without MD rounding");
	check(set(FLOWCTL_YIELD, 0) == 0, "yield reset");

	flow_md_register(&md_ops);

	/* off -> shadow runs a transition: generation bump, MD barrier/set */
	g = flow_gen;
	check(set(FLOWCTL_MODE, 3) == 0 && get(FLOWCTL_MODE) == 3,
	    "mode 3 set");
	check(flow_gen == g + 1, "transition bumped the generation once");
	check(md_rx_barriers == 1 && md_mode == 3 && md_budget == 64,
	    "transition ran the RX barrier and MD scheduling");
	check(set(FLOWCTL_MODE, 3) == 0 && flow_gen == g + 1,
	    "same mode again is a no-op");

	/* max needs mode 0; an unchanged value is fine */
	check(set(FLOWCTL_MAX, 100) == EBUSY && get(FLOWCTL_MAX) == 4096,
	    "max refused with EBUSY in mode 3");
	check(set(FLOWCTL_MAX, 4096) == 0, "unchanged max accepted in mode 3");
	check(set(FLOWCTL_MODE, 2) == EOPNOTSUPP && get(FLOWCTL_MODE) == 3,
	    "mode 2 refused in mode 3, mode unchanged");

	/* active budget/yield changes go through a transition */
	g = flow_gen;
	check(set(FLOWCTL_BUDGET, 32) == 0 && flow_gen == g + 1 &&
	    md_budget == 32 && md_mode == 3, "budget change in mode 3");
	check(set(FLOWCTL_BUDGET, 32) == 0 && flow_gen == g + 1,
	    "unchanged budget runs no transition");
	check(set(FLOWCTL_YIELD, 7) == 0 && get(FLOWCTL_YIELD) == 10 &&
	    md_yield == 10 && flow_gen == g + 2,
	    "yield rounded by the MD op and applied by a transition");

	/* a transition empties the table */
	for (i = 0; i < 10; i++)
		add_flow(i);
	check(present(3), "flows present before mode 0");
	g = flow_gen;
	check(set(FLOWCTL_MODE, 0) == 0 && get(FLOWCTL_MODE) == 0 &&
	    md_mode == 0, "mode 0 restores stock scheduling");
	check(!present(3) && !present(9), "mode 0 emptied the table");
	check(pool_out == 0, "flushed flows went back to the pool");
	check(flow_gen == g + 1, "mode 0 bumped the generation");

	/* while off, budget/yield are stored only */
	g = flow_gen;
	k = md_rx_barriers;
	check(set(FLOWCTL_BUDGET, 48) == 0 && get(FLOWCTL_BUDGET) == 48 &&
	    flow_gen == g && md_rx_barriers == k && md_budget == 32,
	    "budget stored without a transition in mode 0");
	check(set(FLOWCTL_MAX, 100) == 0 && get(FLOWCTL_MAX) == 100,
	    "max changes in mode 0");

	/* T1.3: the learn gate follows net.inet.ip.forwarding (1 only) */
	for (k = 0; k <= 2; k++) {
		ip_forwarding = k;
		flow_gate_update(-1);
		check(flow_learn_gate == (k == 1), "learn gate follows forwarding");
	}
	g = flow_gen;
	flow_gen_bump(FLOW_GEN_ARP);
	check(flow_gen == g + 1, "flow_gen_bump increments the generation");

	check(mtx_depth == 0 && smr_depth == 0, "no lock or SMR section leaked");

	printf("flowtable: %d checks, %d failures\n", checks, failures);
	libc_exit(failures != 0);
}
