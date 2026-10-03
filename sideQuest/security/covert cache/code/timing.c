#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#define KB 1024UL
#define MB (1024UL * 1024UL)
#define LINE 64UL
#define REPS    2
#define SAMPLES 2000

static inline void load(void *addr) {
    asm volatile("mov (%0), %%rax" : : "r"(addr) : "rax", "memory");
}

static inline void flush(void *addr) {
    asm volatile("clflush (%0)" : : "r"(addr) : "memory");
}

static inline uint64_t record(void *addr) {
    uint32_t lo, hi;
    uint64_t start, end;

    asm volatile("mfence\n\tlfence" ::: "memory");
    asm volatile("rdtscp" : "=a"(lo), "=d"(hi) : : "ecx");
    start = ((uint64_t)hi << 32) | lo;

    asm volatile("lfence" ::: "memory");
    load(addr);
    asm volatile("lfence" ::: "memory");

    asm volatile("rdtscp" : "=a"(lo), "=d"(hi) : : "ecx");
    end = ((uint64_t)hi << 32) | lo;

    return end - start;
}

// populate L1 with junk (drop target to L2)
#define EVICT_L1 (128 * KB)

// populate L2 with junk (drop target to L3)
#define EVICT_L2 (4   * MB)

static void evict(uint8_t *trash, size_t size) {
    for (int r = 0; r < REPS; r++)
        for (size_t i = 0; i < size; i += LINE)
            load(trash + i);
}

int main(void) {
    uint8_t *target = (uint8_t *)aligned_alloc(4096, 4096);
    uint8_t *trash  = (uint8_t *)aligned_alloc(4096, EVICT_L2);

    memset(target, 1, 4096);    // prevent page fault
    memset(trash, 1, EVICT_L2);

    uint8_t *target_line = target + 1024;

    uint64_t *l1_times   = (uint64_t *)malloc(SAMPLES * sizeof(uint64_t));
    uint64_t *l2_times   = (uint64_t *)malloc(SAMPLES * sizeof(uint64_t));
    uint64_t *l3_times   = (uint64_t *)malloc(SAMPLES * sizeof(uint64_t));
    uint64_t *dram_times = (uint64_t *)malloc(SAMPLES * sizeof(uint64_t));

    // measure L1
    for (int i = 0; i < SAMPLES; i++) {
        load(target_line);
        l1_times[i] = record(target_line);
    }

    // measure L2
    for (int i = 0; i < SAMPLES; i++) {
        load(target_line);
        asm volatile("mfence" ::: "memory");
        evict(trash, EVICT_L1);
        l2_times[i] = record(target_line);
    }

    // measure L3
    for (int i = 0; i < SAMPLES; i++) {
        load(target_line);
        asm volatile("mfence" ::: "memory");
        evict(trash, EVICT_L2);
        l3_times[i] = record(target_line);
    }

    // measure DRAM
    for (int i = 0; i < SAMPLES; i++) {
        flush(target_line);
        dram_times[i] = record(target_line);
    }

    // publish
    FILE *f = fopen("latencies.csv", "w");
    fprintf(f, "L1,L2,L3,DRAM\n");
    for (int i = 0; i < SAMPLES; i++)
        fprintf(f, "%lu,%lu,%lu,%lu\n",
                (unsigned long)l1_times[i], (unsigned long)l2_times[i],
                (unsigned long)l3_times[i], (unsigned long)dram_times[i]);
    fclose(f);

    printf("wrote %d samples per level to latencies.csv\n", SAMPLES);
    return 0;
}