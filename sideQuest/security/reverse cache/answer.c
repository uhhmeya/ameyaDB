#define _GNU_SOURCE
#include <stdint.h>
#include <stdio.h>
#include <x86intrin.h>
#include <stdlib.h>
#include <stddef.h>
#include <sched.h>
#include <sys/mman.h>

#define LINE_SIZE   64
#define PAGE_SIZE_B 4096
#define EVICT_SIZE  (4 * 1024 * 1024)
#define EVICT_LINES (EVICT_SIZE / LINE_SIZE)

#define NUM_CANDIDATES 512
#define CAND_SIZE      (NUM_CANDIDATES * LINE_SIZE)
#define NUM_TRIALS     200
#define WARMUP_ROUNDS  20
#define NUM_RESULTS    10

static volatile uint8_t *evict_buf;
static uint32_t evict_order[EVICT_LINES];

static volatile uint8_t *cand_buf;
static uint16_t samples[NUM_CANDIDATES][NUM_TRIALS];

typedef struct {
    int line;
    volatile uint8_t *addr;
    double latency;
} result_t;

static result_t results[NUM_CANDIDATES];

static void pre_fault(volatile uint8_t *buf, size_t size) {
    for (size_t i = 0; i < size; i += PAGE_SIZE_B) {
        buf[i] = 1;
    }
}

static void shuffle(void) {
    for (uint32_t i = 0; i < EVICT_LINES; i++) {
        evict_order[i] = i;
    }
    srand(12345);
    for (uint32_t i = EVICT_LINES - 1; i > 0; i--) {
        uint32_t j = rand() % (i + 1);
        uint32_t tmp = evict_order[i];
        evict_order[i] = evict_order[j];
        evict_order[j] = tmp;
    }
}

static void evict_init(void) {
    evict_buf = mmap(NULL, EVICT_SIZE, PROT_READ | PROT_WRITE,
                     MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (evict_buf == MAP_FAILED) {
        exit(1);
    }
    pre_fault(evict_buf, EVICT_SIZE);
    shuffle();
}

static void cand_init(void) {
    cand_buf = mmap(NULL, CAND_SIZE, PROT_READ | PROT_WRITE,
                    MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (cand_buf == MAP_FAILED) {
        exit(1);
    }
    pre_fault(cand_buf, CAND_SIZE);
}

static inline uint64_t get_cycles(volatile uint8_t *addr) {
    _mm_lfence();
    uint64_t start = __rdtsc();
    _mm_lfence();
    (void)*addr;
    _mm_lfence();
    uint64_t end = __rdtsc();
    _mm_lfence();
    return end - start;
}

static inline void evict(void) {
    for (size_t i = 0; i < EVICT_LINES; i++) {
        (void)evict_buf[(size_t)evict_order[i] * LINE_SIZE];
    }
}

static uint64_t measure_once(volatile uint8_t *TL) {
    (void)*(volatile uint8_t *)TL;
    evict();
    return get_cycles(TL);
}

static void warm_up(void) {
    for (int r = 0; r < WARMUP_ROUNDS; r++) {
        for (int c = 0; c < NUM_CANDIDATES; c++) {
            (void)measure_once(cand_buf + (size_t)c * LINE_SIZE);
        }
    }
}

static void run_trials(void) {
    for (int t = 0; t < NUM_TRIALS; t++) {
        for (int c = 0; c < NUM_CANDIDATES; c++) {
            uint64_t cycles = measure_once(cand_buf + (size_t)c * LINE_SIZE);
            if (cycles > UINT16_MAX) {
                cycles = UINT16_MAX;
            }
            samples[c][t] = (uint16_t)cycles;
        }
    }
}

static int cmp_u16(const void *a, const void *b) {
    uint16_t x = *(const uint16_t *)a;
    uint16_t y = *(const uint16_t *)b;
    return (x > y) - (x < y);
}

static int cmp_result(const void *a, const void *b) {
    double x = ((const result_t *)a)->latency;
    double y = ((const result_t *)b)->latency;
    return (x > y) - (x < y);
}

static double trimmed_mean(uint16_t *s, int n) {
    qsort(s, n, sizeof(uint16_t), cmp_u16);
    int lo = n / 4;
    int hi = 3 * n / 4;
    uint64_t sum = 0;
    for (int i = lo; i < hi; i++) {
        sum += s[i];
    }
    return (double)sum / (hi - lo);
}

static void save_csv(int cpu) {
    char name[64];
    snprintf(name, sizeof(name), "results_cpu%d.csv", cpu);
    FILE *f = fopen(name, "w");
    if (f == NULL) {
        exit(1);
    }
    fprintf(f, "rank,line,address,cycles,selected\n");
    for (int i = 0; i < NUM_CANDIDATES; i++) {
        fprintf(f, "%d,%d,%p,%.3f,%d\n", i + 1, results[i].line,
                (void *)results[i].addr, results[i].latency, i < NUM_RESULTS);
    }
    fclose(f);
    printf("Saved all %d lines to %s\n", NUM_CANDIDATES, name);
}

int main(void) {
    int cpu = sched_getcpu();

    evict_init();
    cand_init();

    warm_up();
    run_trials();

    for (int c = 0; c < NUM_CANDIDATES; c++) {
        results[c].line = c;
        results[c].addr = cand_buf + (size_t)c * LINE_SIZE;
        results[c].latency = trimmed_mean(samples[c], NUM_TRIALS);
    }

    qsort(results, NUM_CANDIDATES, sizeof(result_t), cmp_result);

    printf("Running on CPU %d\n", cpu);
    printf("10 addresses in the local slice...\n");
    for (int i = 0; i < NUM_RESULTS; i++) {
        printf("%2d: %p  %.2f cycles\n", i + 1,
               (void *)results[i].addr, results[i].latency);
    }
    printf("Median of all %d lines: %.2f cycles\n", NUM_CANDIDATES,
           results[NUM_CANDIDATES / 2].latency);

    save_csv(cpu);

    return 0;
}