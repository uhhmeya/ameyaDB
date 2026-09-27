#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/stat.h>

#ifndef SHARED_FILE
#define SHARED_FILE "/u/yguo51/276_fall26/shared_file"
#endif

#ifndef THRESHOLD
#define THRESHOLD 200
#endif
#ifndef REPS
#define REPS 2000
#endif
#ifndef VOTES
#define VOTES 5
#endif
#ifndef DEB
#define DEB 5
#endif

#define STRIDE 64
#define LINES  10
#define REQ 0
#define ACK 9

static const int SLOT[LINES] = {2, 37, 13, 53, 7, 43, 23, 59, 17, 31};

static inline void maccess(void *p) {
    asm volatile("mov (%0), %%rax" : : "r"(p) : "rax", "memory");
}

static inline void flush(void *p) {
    asm volatile("clflush (%0)" : : "r"(p) : "memory");
}

static inline uint64_t reload(void *p) {
    uint32_t lo, hi;
    uint64_t start, end;
    asm volatile("mfence\n\tlfence" ::: "memory");
    asm volatile("rdtscp" : "=a"(lo), "=d"(hi) : : "ecx");
    start = ((uint64_t)hi << 32) | lo;
    asm volatile("lfence" ::: "memory");
    maccess(p);
    asm volatile("lfence" ::: "memory");
    asm volatile("rdtscp" : "=a"(lo), "=d"(hi) : : "ecx");
    end = ((uint64_t)hi << 32) | lo;
    return end - start;
}

static inline int sense(void *p) {
    flush(p);
    for (volatile int d = 0; d < 500; d++);
    return reload(p) < THRESHOLD;
}

static void map_lines(void *line[LINES]) {
    int fd = open(SHARED_FILE, O_RDONLY);
    if (fd < 0) { perror("open"); exit(1); }
    struct stat st;
    fstat(fd, &st);
    uint8_t *base = mmap(NULL, st.st_size, PROT_READ, MAP_SHARED, fd, 0);
    if (base == MAP_FAILED) { perror("mmap"); exit(1); }
    for (int i = 0; i < LINES; i++)
        line[i] = base + SLOT[i] * STRIDE;
}